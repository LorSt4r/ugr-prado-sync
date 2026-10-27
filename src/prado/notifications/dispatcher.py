"""
Unified Notification Dispatcher for PradoOS.

Aggregates:
- Desktop alerts (macOS, Linux, Windows)
- Telegram Bot API
- Discord Webhooks
- SMTP Email
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from prado.config import PradoConfig, load_config
from prado.core.downloader import SyncSummary
from prado.notifications.desktop import DesktopNotifier
from prado.notifications.email import SmtpConfig, SmtpEmailSender
from prado.notifications.webhooks import (
    DiscordWebhookSender,
    NotificationResult,
    TelegramWebhookSender,
)


@dataclass
class DesktopNotificationConfig:
    enabled: bool = True
    sound: bool = True
    urgency: str = "normal"


@dataclass
class TelegramNotificationConfig:
    enabled: bool = False
    bot_token: Optional[str] = None
    chat_id: Optional[str] = None
    parse_mode: str = "HTML"


@dataclass
class DiscordNotificationConfig:
    enabled: bool = False
    webhook_url: Optional[str] = None
    username: str = "PradoOS"


@dataclass
class EmailNotificationConfig:
    enabled: bool = False
    smtp_host: str = "smtp.ugr.es"
    smtp_port: int = 587
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None
    use_tls: bool = True
    use_ssl: bool = False
    from_address: Optional[str] = None
    to_addresses: List[str] = field(default_factory=list)


@dataclass
class NotificationConfig:
    enabled: bool = True
    notify_on_new_files: bool = True
    notify_on_updated_files: bool = True
    notify_on_conflicts: bool = True
    notify_on_deadlines: bool = True
    notify_on_forum_posts: bool = True
    desktop: DesktopNotificationConfig = field(default_factory=DesktopNotificationConfig)
    telegram: TelegramNotificationConfig = field(default_factory=TelegramNotificationConfig)
    discord: DiscordNotificationConfig = field(default_factory=DiscordNotificationConfig)
    email: EmailNotificationConfig = field(default_factory=EmailNotificationConfig)


class NotificationDispatcher:
    """Unified dispatcher sending events across enabled notification channels."""

    def __init__(
        self,
        config: Optional[NotificationConfig] = None,
        prado_config: Optional[PradoConfig] = None,
    ):
        if config is not None:
            self.cfg = config
        elif prado_config is not None and hasattr(prado_config, "notifications"):
            self.cfg = getattr(prado_config, "notifications")
        else:
            self.cfg = NotificationConfig()

        self.desktop = DesktopNotifier(app_name="PradoOS")

        self.telegram: Optional[TelegramWebhookSender] = None
        if self.cfg.telegram.enabled and self.cfg.telegram.bot_token and self.cfg.telegram.chat_id:
            self.telegram = TelegramWebhookSender(self.cfg.telegram.bot_token, self.cfg.telegram.chat_id)

        self.discord: Optional[DiscordWebhookSender] = None
        if self.cfg.discord.enabled and self.cfg.discord.webhook_url:
            self.discord = DiscordWebhookSender(
                self.cfg.discord.webhook_url, username=self.cfg.discord.username
            )

        self.email: Optional[SmtpEmailSender] = None
        if self.cfg.email.enabled and self.cfg.email.to_addresses:
            smtp_cfg = SmtpConfig(
                host=self.cfg.email.smtp_host,
                port=self.cfg.email.smtp_port,
                username=self.cfg.email.smtp_username,
                password=self.cfg.email.smtp_password,
                use_tls=self.cfg.email.use_tls,
                use_ssl=self.cfg.email.use_ssl,
                from_address=self.cfg.email.from_address,
                to_addresses=self.cfg.email.to_addresses,
            )
            self.email = SmtpEmailSender(smtp_cfg)

    def dispatch_sync_summary(self, summary: SyncSummary) -> List[NotificationResult]:
        results: List[NotificationResult] = []
        if not self.cfg.enabled:
            return results

        # 1. Desktop notification
        if self.cfg.desktop.enabled:
            n_files = len(summary.downloaded_files)
            n_deadlines = len(summary.deadlines)
            n_conflicts = len(summary.conflict_files)
            title = "PradoOS Sync Finished"
            body = f"{n_files} new files, {n_deadlines} deadlines"
            if n_conflicts > 0:
                body += f", {n_conflicts} protected conflicts"
            urgency = "critical" if n_conflicts else self.cfg.desktop.urgency
            sent = self.desktop.notify(
                title=title,
                message=body,
                urgency=urgency,
                sound=self.cfg.desktop.sound,
            )
            results.append(
                NotificationResult(channel="desktop", success=sent, message="Desktop alert processed")
            )

        # 2. Telegram webhook
        if self.telegram and self.cfg.telegram.enabled:
            text = self.telegram.format_sync_summary(summary)
            results.append(self.telegram.send_message(text))

        # 3. Discord webhook
        if self.discord and self.cfg.discord.enabled:
            embeds = self.discord.format_sync_summary_embeds(summary)
            results.append(self.discord.send_embeds(embeds))

        # 4. SMTP email
        if self.email and self.cfg.email.enabled:
            n_dl = len(summary.downloaded_files)
            n_dl_str = f"{n_dl} new file(s)"
            subject = f"[PradoOS] Academic Sync Report: {n_dl_str}"
            text_body = f"PradoOS Sync Summary:\n{n_dl} new files.\n{len(summary.deadlines)} deadlines."
            results.append(self.email.send_email(subject=subject, text_body=text_body))

        return results

    def send_alert(
        self,
        title: str,
        message: str,
        urgency: str = "normal",
    ) -> List[NotificationResult]:
        """Dispatches an urgent text alert across all active channels."""
        results: List[NotificationResult] = []
        if not self.cfg.enabled:
            return results

        if self.cfg.desktop.enabled:
            sent = self.desktop.notify(title=title, message=message, urgency=urgency)
            results.append(NotificationResult(channel="desktop", success=sent, message="Desktop alert"))

        if self.telegram and self.cfg.telegram.enabled:
            results.append(self.telegram.send_message(f"<b>{title}</b>\n{message}"))

        if self.discord and self.cfg.discord.enabled:
            results.append(self.discord.send_embeds([{"title": title, "description": message}]))

        if self.email and self.cfg.email.enabled:
            results.append(self.email.send_email(subject=f"[PradoOS] {title}", text_body=message))

        return results
