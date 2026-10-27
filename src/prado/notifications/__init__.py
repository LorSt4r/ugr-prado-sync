"""
PradoOS Notifications Module.

Exports:
- DesktopNotifier, is_headless_environment, DesktopNotification
- TelegramWebhookSender, DiscordWebhookSender, NotificationResult, mask_secret
- SmtpEmailSender, SmtpConfig
- NotificationDispatcher, NotificationConfig, DesktopNotificationConfig,
  TelegramNotificationConfig, DiscordNotificationConfig, EmailNotificationConfig
"""

from prado.notifications.desktop import (
    DesktopNotification,
    DesktopNotifier,
    is_headless_environment,
)
from prado.notifications.dispatcher import (
    DesktopNotificationConfig,
    DiscordNotificationConfig,
    EmailNotificationConfig,
    NotificationConfig,
    NotificationDispatcher,
    TelegramNotificationConfig,
)
from prado.notifications.email import SmtpConfig, SmtpEmailSender
from prado.notifications.webhooks import (
    DiscordWebhookSender,
    NotificationResult,
    TelegramWebhookSender,
    mask_secret,
)

__all__ = [
    "DesktopNotification",
    "DesktopNotificationConfig",
    "DesktopNotifier",
    "DiscordNotificationConfig",
    "DiscordWebhookSender",
    "EmailNotificationConfig",
    "NotificationConfig",
    "NotificationDispatcher",
    "NotificationResult",
    "SmtpConfig",
    "SmtpEmailSender",
    "TelegramNotificationConfig",
    "TelegramWebhookSender",
    "is_headless_environment",
    "mask_secret",
]
