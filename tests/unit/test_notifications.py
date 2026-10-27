"""
Unit tests for PradoOS cross-platform notifications and webhook engine.
"""

from __future__ import annotations

import datetime
from pathlib import Path
import subprocess
import sys
from unittest.mock import MagicMock, patch
import pytest
import requests

from prado.core.downloader import (
    ConflictFile,
    DeadlineItem,
    DownloadedFile,
    ForumPost,
    SyncSummary,
)
from prado.notifications.desktop import (
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


# =============================================================================
# Desktop Notifier Tests
# =============================================================================

def test_desktop_notify_macos(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("PRADO_HEADLESS", "0")
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

    notifier = DesktopNotifier()
    monkeypatch.setattr(notifier, "is_available", lambda: True)

    mock_run = MagicMock(return_value=subprocess.CompletedProcess(args=[], returncode=0))
    monkeypatch.setattr(subprocess, "run", mock_run)

    success = notifier.notify(
        title="PradoOS",
        message="Sync complete",
        subtitle="ED Course",
        sound=True,
    )
    assert success is True
    assert mock_run.called
    cmd_args = mock_run.call_args[0][0]
    assert cmd_args[0] == "osascript"
    assert "PradoOS" in cmd_args
    assert "Sync complete" in cmd_args


def test_desktop_notify_linux(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("PRADO_HEADLESS", "0")
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

    notifier = DesktopNotifier()
    monkeypatch.setattr(notifier, "is_available", lambda: True)

    mock_run = MagicMock(return_value=subprocess.CompletedProcess(args=[], returncode=0))
    monkeypatch.setattr(subprocess, "run", mock_run)

    success = notifier.notify(
        title="PradoOS",
        message="3 files downloaded",
        urgency="critical",
    )
    assert success is True
    assert mock_run.called
    cmd_args = mock_run.call_args[0][0]
    assert cmd_args[0] == "notify-send"
    assert "--urgency=critical" in cmd_args


def test_desktop_notify_headless(monkeypatch):
    monkeypatch.setenv("PRADO_HEADLESS", "1")
    assert is_headless_environment() is True

    notifier = DesktopNotifier()
    assert notifier.is_available() is False
    assert notifier.notify("Title", "Message") is False


def test_desktop_notify_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    notifier = DesktopNotifier()
    monkeypatch.setattr(notifier, "is_available", lambda: True)

    mock_run = MagicMock(return_value=subprocess.CompletedProcess(args=[], returncode=0))
    monkeypatch.setattr(subprocess, "run", mock_run)

    success = notifier.notify("PradoOS", "Windows message")
    assert success is True
    assert mock_run.called
    cmd_args = mock_run.call_args[0][0]
    assert "powershell" in cmd_args[0].lower()


def test_desktop_notify_timeout(monkeypatch):
    notifier = DesktopNotifier()
    monkeypatch.setattr(notifier, "is_available", lambda: True)
    monkeypatch.setattr(sys, "platform", "darwin")

    def mock_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="osascript", timeout=5.0)

    monkeypatch.setattr(subprocess, "run", mock_timeout)

    success = notifier.notify("PradoOS", "Hanging alert")
    assert success is False


# =============================================================================
# Webhook Tests (Telegram & Discord)
# =============================================================================

def test_telegram_webhook_success(monkeypatch):
    sender = TelegramWebhookSender(bot_token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11", chat_id="987654321")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"ok": True, "result": {"message_id": 1}}
    monkeypatch.setattr(requests, "post", lambda url, json, timeout: mock_resp)

    res = sender.send_message("<b>Test Message</b>")
    assert res.success is True
    assert res.channel == "telegram"
    assert res.status_code == 200


def test_telegram_token_masking():
    token = "1234567890:ABCDEFGHIJ_abcdefghijk12345678"
    masked = mask_secret(token)
    assert masked.startswith("1234***")
    assert masked.endswith("5678")
    assert "ABCDEF" not in masked


def test_telegram_truncation(monkeypatch):
    sender = TelegramWebhookSender(bot_token="token", chat_id="123")
    captured_payload = {}

    def mock_post(url, json, timeout):
        captured_payload.update(json)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True}
        return mock_resp

    monkeypatch.setattr(requests, "post", mock_post)

    huge_message = "A" * 6000
    sender.send_message(huge_message)
    assert len(captured_payload["text"]) <= 4096
    assert "[Content truncated" in captured_payload["text"]


def test_discord_webhook_embeds(monkeypatch):
    sender = DiscordWebhookSender(webhook_url="https://discord.com/api/webhooks/123/token456")
    captured_payload = {}

    def mock_post(url, json, timeout):
        captured_payload.update(json)
        mock_resp = MagicMock()
        mock_resp.status_code = 204
        return mock_resp

    monkeypatch.setattr(requests, "post", mock_post)

    summary = SyncSummary(
        downloaded_files=[
            DownloadedFile(path=Path("doc.pdf"), url="u", sha256="s", size_bytes=100)
        ],
        conflict_files=[
            ConflictFile(
                original_path=Path("orig.py"),
                forked_path=Path("fork.py"),
                server_sha256="1",
                local_sha256="2",
            )
        ],
    )
    embeds = sender.format_sync_summary_embeds(summary)
    res = sender.send_embeds(embeds)

    assert res.success is True
    assert res.channel == "discord"
    assert len(captured_payload["embeds"]) == 1
    # Conflict file triggers red color (0xE74C3C)
    assert captured_payload["embeds"][0]["color"] == 0xE74C3C


# =============================================================================
# SMTP Email Sender Tests
# =============================================================================

def test_smtp_email_starttls(monkeypatch):
    cfg = SmtpConfig(
        host="smtp.ugr.es",
        port=587,
        username="user@ugr.es",
        password="secretpassword",
        use_tls=True,
        to_addresses=["dest@example.com"],
    )
    sender = SmtpEmailSender(cfg)

    mock_server = MagicMock()
    monkeypatch.setattr("smtplib.SMTP", lambda host, port, timeout: mock_server)
    mock_server.__enter__.return_value = mock_server

    res = sender.send_email(subject="Test Subject", text_body="Test Body")
    assert res.success is True
    assert res.channel == "email"
    assert mock_server.starttls.called
    assert mock_server.login.called
    assert mock_server.send_message.called


def test_smtp_email_ssl(monkeypatch):
    cfg = SmtpConfig(
        host="smtp.ugr.es",
        port=465,
        username="user@ugr.es",
        password="secretpassword",
        use_ssl=True,
        to_addresses=["dest@example.com"],
    )
    sender = SmtpEmailSender(cfg)

    mock_server = MagicMock()
    monkeypatch.setattr("smtplib.SMTP_SSL", lambda host, port, timeout: mock_server)
    mock_server.__enter__.return_value = mock_server

    res = sender.send_email(subject="Test Subject", text_body="Test Body")
    assert res.success is True
    assert res.channel == "email"
    assert mock_server.send_message.called


# =============================================================================
# Notification Dispatcher Tests
# =============================================================================

def test_dispatcher_sync_summary(monkeypatch):
    cfg = NotificationConfig(
        enabled=True,
        desktop=DesktopNotificationConfig(enabled=True),
        telegram=TelegramNotificationConfig(enabled=True, bot_token="tok", chat_id="123"),
        discord=DiscordNotificationConfig(enabled=True, webhook_url="https://discord.com/hook"),
        email=EmailNotificationConfig(enabled=True, to_addresses=["user@ugr.es"]),
    )
    dispatcher = NotificationDispatcher(config=cfg)

    # Mock desktop
    monkeypatch.setattr(dispatcher.desktop, "notify", lambda **kwargs: True)

    # Mock webhooks
    monkeypatch.setattr(
        dispatcher.telegram,
        "send_message",
        lambda text: NotificationResult(channel="telegram", success=True, message="OK"),
    )
    monkeypatch.setattr(
        dispatcher.discord,
        "send_embeds",
        lambda embeds: NotificationResult(channel="discord", success=True, message="OK"),
    )
    monkeypatch.setattr(
        dispatcher.email,
        "send_email",
        lambda **kwargs: NotificationResult(channel="email", success=True, message="OK"),
    )

    summary = SyncSummary(
        downloaded_files=[
            DownloadedFile(path=Path("f.pdf"), url="u", sha256="s", size_bytes=50)
        ]
    )
    results = dispatcher.dispatch_sync_summary(summary)

    assert len(results) == 4
    channels = [r.channel for r in results]
    assert "desktop" in channels
    assert "telegram" in channels
    assert "discord" in channels
    assert "email" in channels
    assert all(r.success for r in results)
