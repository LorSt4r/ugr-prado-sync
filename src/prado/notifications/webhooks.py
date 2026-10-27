"""
Webhook Integrations for PradoOS (Telegram Bot API & Discord Incoming Webhooks).

Features:
- Telegram Bot API with HTML/Markdown parsing and length limits (4096 chars)
- Discord Webhook integration with formatted embed cards and status coloring
- Credential masking (***) in logs and error reports to prevent secret leakage
"""

from __future__ import annotations

from dataclasses import dataclass
import html
import re
from typing import Any, Dict, List, Optional

import requests

from prado.core.downloader import SyncSummary


@dataclass
class NotificationResult:
    """Outcome of an attempted notification dispatch."""
    channel: str  # "desktop", "telegram", "discord", "email"
    success: bool
    message: str
    error: Optional[str] = None
    status_code: Optional[int] = None


def mask_secret(secret: str, keep_start: int = 4, keep_end: int = 4) -> str:
    """Masks secrets and tokens to prevent leakage in log outputs and error reports."""
    if not secret:
        return ""
    if len(secret) <= (keep_start + keep_end):
        return "***"
    return f"{secret[:keep_start]}***{secret[-keep_end:]}"


class TelegramWebhookSender:
    """Dispatches notifications to a Telegram chat or channel via Bot API."""

    MAX_MESSAGE_LENGTH: int = 4096

    def __init__(self, bot_token: str, chat_id: str, timeout_seconds: float = 10.0):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.timeout_seconds = timeout_seconds

    @property
    def api_url(self) -> str:
        return f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

    def send_message(
        self,
        text: str,
        parse_mode: str = "HTML",
        disable_preview: bool = True,
    ) -> NotificationResult:
        if len(text) > (self.MAX_MESSAGE_LENGTH - 100):
            text = (
                text[: (self.MAX_MESSAGE_LENGTH - 150)]
                + "\n\n<i>[Content truncated due to size limits]</i>"
            )

        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_preview,
        }

        try:
            resp = requests.post(self.api_url, json=payload, timeout=self.timeout_seconds)
            if resp.status_code == 200 and resp.json().get("ok"):
                return NotificationResult(
                    channel="telegram",
                    success=True,
                    message="Telegram alert delivered successfully",
                    status_code=resp.status_code,
                )
            return NotificationResult(
                channel="telegram",
                success=False,
                message="Telegram API returned non-OK response",
                error=resp.text,
                status_code=resp.status_code,
            )
        except requests.RequestException as e:
            masked_url = f"https://api.telegram.org/bot{mask_secret(self.bot_token)}/sendMessage"
            return NotificationResult(
                channel="telegram",
                success=False,
                message="Network error connecting to Telegram",
                error=f"{type(e).__name__} on {masked_url}",
            )

    def format_sync_summary(self, summary: SyncSummary) -> str:
        lines = ["🚀 <b>PradoOS Academic Sync Update</b>\n"]

        if summary.downloaded_files:
            lines.append(f"📥 <b>New Files Downloaded ({len(summary.downloaded_files)}):</b>")
            for f in summary.downloaded_files[:5]:
                course_tag = f" <i>({html.escape(str(f.course_id))})</i>" if f.course_id else ""
                lines.append(f"• <code>{html.escape(f.path.name)}</code>{course_tag}")
            if len(summary.downloaded_files) > 5:
                lines.append(f"• <i>... and {len(summary.downloaded_files) - 5} more files</i>")
            lines.append("")

        if summary.conflict_files:
            lines.append(f"⚠️ <b>Student Overwrite Protection Active ({len(summary.conflict_files)}):</b>")
            for c in summary.conflict_files[:3]:
                lines.append(
                    f"• <code>{html.escape(c.original_path.name)}</code> preserved locally; server update saved as <code>{html.escape(c.forked_path.name)}</code>"
                )
            lines.append("")

        if summary.deadlines:
            lines.append(f"⏰ <b>Upcoming Deadlines ({len(summary.deadlines)}):</b>")
            for d in summary.deadlines[:5]:
                due_str = d.due_date.strftime("%d/%m/%Y %H:%M") if d.due_date else "TBD"
                lines.append(f"• <b>{html.escape(str(d.course))}:</b> {html.escape(str(d.title))} (<i>{html.escape(due_str)}</i>)")
            lines.append("")

        if summary.forum_announcements:
            lines.append(f"💬 <b>Forum Notices ({len(summary.forum_announcements)}):</b>")
            for p in summary.forum_announcements[:3]:
                author = f" by {html.escape(str(p.author))}" if p.author else ""
                lines.append(f"• <b>{html.escape(str(p.subject))}</b>{author}")
            lines.append("")

        return "\n".join(lines).strip()


class DiscordWebhookSender:
    """Dispatches notifications via Discord incoming webhooks with rich embeds."""

    MAX_CONTENT_LENGTH: int = 2000

    def __init__(
        self,
        webhook_url: str,
        username: str = "PradoOS",
        avatar_url: Optional[str] = None,
        timeout_seconds: float = 10.0,
    ):
        self.webhook_url = webhook_url
        self.username = username
        self.avatar_url = avatar_url
        self.timeout_seconds = timeout_seconds

    def send_embeds(
        self,
        embeds: List[Dict[str, Any]],
        content: Optional[str] = None,
    ) -> NotificationResult:
        payload: Dict[str, Any] = {
            "username": self.username,
            "embeds": embeds,
        }
        if self.avatar_url:
            payload["avatar_url"] = self.avatar_url
        if content:
            payload["content"] = content[: self.MAX_CONTENT_LENGTH]

        try:
            resp = requests.post(self.webhook_url, json=payload, timeout=self.timeout_seconds)
            if resp.status_code in (200, 204):
                return NotificationResult(
                    channel="discord",
                    success=True,
                    message="Discord alert delivered successfully",
                    status_code=resp.status_code,
                )
            return NotificationResult(
                channel="discord",
                success=False,
                message="Discord webhook error",
                error=resp.text,
                status_code=resp.status_code,
            )
        except requests.RequestException as e:
            masked_url = re.sub(
                r"/webhooks/\d+/[^/]+",
                f"/webhooks/{mask_secret(self.webhook_url)}",
                self.webhook_url,
            )
            return NotificationResult(
                channel="discord",
                success=False,
                message="Network error connecting to Discord",
                error=f"{type(e).__name__} on {masked_url}",
            )

    def format_sync_summary_embeds(self, summary: SyncSummary) -> List[Dict[str, Any]]:
        embeds = []
        # Color coding: Green = normal, Amber = deadlines, Red = overwrite conflict
        color = 0x2ECC71  # Green
        if summary.conflict_files:
            color = 0xE74C3C  # Red
        elif summary.deadlines:
            color = 0xE67E22  # Amber

        fields = [
            {"name": "New Files", "value": str(len(summary.downloaded_files)), "inline": True},
            {"name": "Updated Files", "value": str(len(summary.updated_files)), "inline": True},
            {"name": "Protected Files", "value": str(len(summary.conflict_files)), "inline": True},
            {"name": "Active Deadlines", "value": str(len(summary.deadlines)), "inline": True},
            {"name": "Forum Announcements", "value": str(len(summary.forum_announcements)), "inline": True},
        ]

        embeds.append(
            {
                "title": "📚 PradoOS Sync Summary",
                "color": color,
                "fields": fields,
                "footer": {"text": "PradoOS Academic Engine"},
            }
        )
        return embeds
