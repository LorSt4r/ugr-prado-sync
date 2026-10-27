"""
Cross-platform, Zero-dependency Desktop Notifications for PradoOS.

Supports:
- macOS: /usr/bin/osascript using on run argv (safe against injection)
- Linux: notify-send (with display/dbus presence checks)
- Windows: PowerShell System.Windows.Forms.NotifyIcon / WinRT Toast
- Headless / CI safe: cleanly no-ops when no display server is available
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import shutil
import subprocess
import sys
from typing import Optional


@dataclass
class DesktopNotification:
    title: str
    message: str
    subtitle: Optional[str] = None
    urgency: str = "normal"  # "low", "normal", "critical"
    sound: bool = True
    timeout_ms: int = 5000


def is_headless_environment() -> bool:
    """Returns True if running in a headless or CI environment without GUI capabilities."""
    if os.environ.get("PRADO_HEADLESS") == "1":
        return True
    if os.environ.get("CI") == "true" or os.environ.get("GITHUB_ACTIONS") == "true":
        return True
    if sys.platform.startswith("linux"):
        has_display = bool(
            os.environ.get("DISPLAY")
            or os.environ.get("WAYLAND_DISPLAY")
            or os.environ.get("DBUS_SESSION_BUS_ADDRESS")
        )
        return not has_display
    return False


class DesktopNotifier:
    """Cross-platform zero-dependency desktop notification engine."""

    def __init__(self, app_name: str = "PradoOS"):
        self.app_name = app_name

    def is_available(self) -> bool:
        if is_headless_environment():
            return False
        sys_plat = sys.platform
        if sys_plat == "darwin":
            return bool(shutil.which("osascript"))
        elif sys_plat.startswith("linux"):
            return bool(shutil.which("notify-send"))
        elif sys_plat in ("win32", "cygwin"):
            return bool(shutil.which("powershell") or shutil.which("pwsh"))
        return False

    def notify(
        self,
        title: str,
        message: str,
        subtitle: Optional[str] = None,
        urgency: str = "normal",
        sound: bool = True,
        timeout_ms: int = 5000,
    ) -> bool:
        """
        Sends native desktop notification.
        Never raises exceptions; returns True if sent successfully, False otherwise.
        """
        title = title or self.app_name
        # Message clamping for desktop display
        if len(message) > 250:
            message = message[:250] + "..."

        if not self.is_available():
            return False

        sys_plat = sys.platform
        try:
            if sys_plat == "darwin":
                return self._notify_macos(title, message, subtitle, sound)
            elif sys_plat.startswith("linux"):
                return self._notify_linux(title, message, subtitle, urgency, timeout_ms)
            elif sys_plat in ("win32", "cygwin"):
                return self._notify_windows(title, message, subtitle, timeout_ms)
            return False
        except (subprocess.SubprocessError, OSError):
            return False

    def _notify_macos(self, title: str, message: str, subtitle: Optional[str], sound: bool) -> bool:
        script = """on run argv
    set notifTitle to item 1 of argv
    set notifMsg to item 2 of argv
    set notifSubtitle to item 3 of argv
    set playSound to item 4 of argv
    if notifSubtitle is not "" then
        if playSound is "true" then
            display notification notifMsg with title notifTitle subtitle notifSubtitle sound name "default"
        else
            display notification notifMsg with title notifTitle subtitle notifSubtitle
        end if
    else
        if playSound is "true" then
            display notification notifMsg with title notifTitle sound name "default"
        else
            display notification notifMsg with title notifTitle
        end if
    end if
end run"""
        cmd = [
            "osascript",
            "-e",
            script,
            title,
            message,
            subtitle or "",
            "true" if sound else "false",
        ]
        res = subprocess.run(cmd, check=False, timeout=5.0, capture_output=True)
        return res.returncode == 0

    def _notify_linux(self, title: str, message: str, subtitle: Optional[str], urgency: str, timeout_ms: int) -> bool:
        body = f"{subtitle}\n{message}" if subtitle else message
        urgency_flag = urgency if urgency in ("low", "normal", "critical") else "normal"
        cmd = [
            "notify-send",
            f"--app-name={self.app_name}",
            f"--urgency={urgency_flag}",
            "-t",
            str(timeout_ms),
            title,
            body,
        ]
        res = subprocess.run(cmd, check=False, timeout=5.0, capture_output=True)
        return res.returncode == 0

    def _notify_windows(self, title: str, message: str, subtitle: Optional[str], timeout_ms: int) -> bool:
        try:
            ps_cmd = shutil.which("powershell") or shutil.which("pwsh") or "powershell.exe"
        except Exception:
            ps_cmd = "powershell.exe"
        safe_timeout = max(1000, min(int(timeout_ms), 30000))
        clean_title = title.replace("\x00", "")
        raw_body = f"{subtitle} - {message}" if subtitle else message
        clean_body = raw_body.replace("\x00", "")
        env = os.environ.copy()
        env["PRADO_NOTIFY_TITLE"] = clean_title
        env["PRADO_NOTIFY_BODY"] = clean_body
        env["PRADO_NOTIFY_TIMEOUT"] = str(safe_timeout)
        ps_script = (
            "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; "
            "$notify = New-Object System.Windows.Forms.NotifyIcon; "
            "$notify.Icon = [System.Drawing.SystemIcons]::Information; "
            "$notify.BalloonTipTitle = $env:PRADO_NOTIFY_TITLE; "
            "$notify.BalloonTipText = $env:PRADO_NOTIFY_BODY; "
            "$notify.Visible = $True; "
            "$notify.ShowBalloonTip([int]$env:PRADO_NOTIFY_TIMEOUT); "
            "Start-Sleep -Milliseconds 300; "
            "$notify.Dispose()"
        )
        cmd = [ps_cmd, "-NoProfile", "-NonInteractive", "-Command", ps_script]
        res = subprocess.run(cmd, env=env, check=False, timeout=7.0, capture_output=True)
        return res.returncode == 0
