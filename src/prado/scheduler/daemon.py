"""
Cross-platform Background Daemon and Scheduler Manager for PradoOS.

Supports:
- macOS: launchd agent (~/Library/LaunchAgents/es.ugr.prado.plist)
- Linux: systemd user units (~/.config/systemd/user/prado.service & prado.timer)
- Linux Fallback: user crontab (crontab -l / crontab -)
- Windows: Task Scheduler via schtasks.exe
"""

from __future__ import annotations

import abc
import csv
from dataclasses import asdict, dataclass
import io
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional

from prado.config import get_config_dir


@dataclass
class DaemonStatus:
    """Structured status metadata of the background sync daemon."""
    installed: bool
    active: bool
    platform: str
    backend: str
    schedule: str
    target_command: List[str]
    config_path: Optional[str] = None
    log_file: Optional[str] = None
    last_run: Optional[str] = None
    next_run: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def format_terminal(self) -> str:
        status_symbol = (
            "✓ Active" if self.active else ("⚠ Installed (Inactive)" if self.installed else "○ Not Installed")
        )
        lines = [
            f"Daemon Status: {status_symbol}",
            f"Backend      : {self.backend} ({self.platform})",
            f"Schedule     : {self.schedule}",
            f"Command      : {' '.join(self.target_command)}",
        ]
        if self.config_path:
            lines.append(f"Config File  : {self.config_path}")
        if self.log_file:
            lines.append(f"Log Output   : {self.log_file}")
        if self.last_run:
            lines.append(f"Last Run     : {self.last_run}")
        if self.next_run:
            lines.append(f"Next Run     : {self.next_run}")
        if self.error:
            lines.append(f"Error Note   : {self.error}")
        return "\n".join(lines)


def get_default_daemon_command() -> List[str]:
    """
    Returns the command list for background invocation.
    Uses sys.executable to guarantee virtualenv interpreter fidelity.
    """
    return [sys.executable, "-m", "prado", "sync", "--no-interactive"]


class BaseDaemonBackend(abc.ABC):
    """Abstract base class for OS-specific daemon managers."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Name of backend (launchd, systemd, crontab, schtasks)."""
        pass

    @abc.abstractmethod
    def install(self, interval_seconds: int = 3600) -> bool:
        """Installs and enables the background service."""
        pass

    @abc.abstractmethod
    def uninstall(self) -> bool:
        """Disables and removes the background service."""
        pass

    @abc.abstractmethod
    def start(self) -> bool:
        """Starts or unpauses the scheduled job."""
        pass

    @abc.abstractmethod
    def stop(self) -> bool:
        """Stops or pauses the scheduled job."""
        pass

    @abc.abstractmethod
    def status(self) -> DaemonStatus:
        """Queries and returns the current status metadata."""
        pass


class LaunchdBackend(BaseDaemonBackend):
    """macOS launchd agent backend using ~/Library/LaunchAgents/es.ugr.prado.plist."""

    LABEL = "es.ugr.prado"

    def __init__(self, plist_dir: Optional[Path] = None, log_dir: Optional[Path] = None):
        self.plist_dir = plist_dir or (Path.home() / "Library" / "LaunchAgents")
        self.plist_file = self.plist_dir / f"{self.LABEL}.plist"
        self.log_dir = log_dir or get_config_dir()
        self.stdout_log = self.log_dir / "daemon.log"
        self.stderr_log = self.log_dir / "daemon.err"

    @property
    def name(self) -> str:
        return "launchd"

    def _generate_plist_dict(self, interval_seconds: int, command: List[str]) -> Dict[str, Any]:
        safe_interval = max(60, int(interval_seconds))
        return {
            "Label": self.LABEL,
            "ProgramArguments": command,
            "StartInterval": safe_interval,
            "RunAtLoad": True,
            "StandardOutPath": str(self.stdout_log),
            "StandardErrorPath": str(self.stderr_log),
            "ProcessType": "Background",
            "EnvironmentVariables": {
                "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
                "LANG": "en_US.UTF-8",
                "LC_ALL": "en_US.UTF-8",
            },
        }

    def install(self, interval_seconds: int = 3600) -> bool:
        self.plist_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Unload if already loaded
        if self.plist_file.exists():
            self.uninstall()

        command = get_default_daemon_command()
        plist_data = self._generate_plist_dict(interval_seconds, command)

        with open(self.plist_file, "wb") as f:
            plistlib.dump(plist_data, f)

        # Load with launchctl
        res = subprocess.run(["launchctl", "load", str(self.plist_file)], capture_output=True, text=True)
        return res.returncode == 0

    def uninstall(self) -> bool:
        if self.plist_file.exists():
            subprocess.run(["launchctl", "unload", str(self.plist_file)], capture_output=True, text=True)
            try:
                self.plist_file.unlink()
            except OSError:
                pass
            return True
        return False

    def start(self) -> bool:
        res = subprocess.run(["launchctl", "start", self.LABEL], capture_output=True, text=True)
        return res.returncode == 0

    def stop(self) -> bool:
        res = subprocess.run(["launchctl", "stop", self.LABEL], capture_output=True, text=True)
        return res.returncode == 0

    def status(self) -> DaemonStatus:
        installed = self.plist_file.exists()
        active = False
        last_exit = None
        schedule = "3600s"
        target_command = get_default_daemon_command()

        if installed:
            try:
                with open(self.plist_file, "rb") as f:
                    plist = plistlib.load(f)
                    interval = plist.get("StartInterval", 3600)
                    schedule = f"every {interval}s"
                    target_command = plist.get("ProgramArguments", target_command)
            except Exception:
                pass

            # Query launchctl list
            res = subprocess.run(["launchctl", "list", self.LABEL], capture_output=True, text=True)
            if res.returncode == 0:
                active = True
                for line in res.stdout.splitlines():
                    if "LastExitStatus" in line:
                        last_exit = line.strip()

        return DaemonStatus(
            installed=installed,
            active=active,
            platform="darwin",
            backend=self.name,
            schedule=schedule,
            target_command=target_command,
            config_path=str(self.plist_file) if installed else None,
            log_file=str(self.stdout_log) if self.stdout_log.exists() else None,
            error=last_exit,
        )


class SystemdBackend(BaseDaemonBackend):
    """Linux systemd --user service and timer backend."""

    SERVICE_NAME = "prado.service"
    TIMER_NAME = "prado.timer"

    def __init__(self, unit_dir: Optional[Path] = None):
        self.unit_dir = unit_dir or (Path.home() / ".config" / "systemd" / "user")
        self.service_path = self.unit_dir / self.SERVICE_NAME
        self.timer_path = self.unit_dir / self.TIMER_NAME

    @property
    def name(self) -> str:
        return "systemd"

    @classmethod
    def is_available(cls) -> bool:
        """Verifies if systemctl --user is functional on this system."""
        if not shutil.which("systemctl"):
            return False
        try:
            res = subprocess.run(["systemctl", "--user", "list-units"], capture_output=True, timeout=2.0)
            return res.returncode == 0
        except Exception:
            return False

    def install(self, interval_seconds: int = 3600) -> bool:
        self.unit_dir.mkdir(parents=True, exist_ok=True)
        cmd_str = " ".join(f'"{c}"' if " " in c else c for c in get_default_daemon_command())

        service_content = f"""[Unit]
Description=PradoOS Moodle Background Sync
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart={cmd_str}
StandardOutput=journal
StandardError=journal
"""
        timer_content = f"""[Unit]
Description=PradoOS Moodle Sync Timer

[Timer]
OnBootSec=5min
OnUnitActiveSec={interval_seconds}s
Persistent=true

[Install]
WantedBy=timers.target
"""
        self.service_path.write_text(service_content, encoding="utf-8")
        self.timer_path.write_text(timer_content, encoding="utf-8")

        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
        res = subprocess.run(["systemctl", "--user", "enable", "--now", self.TIMER_NAME], capture_output=True)
        return res.returncode == 0

    def uninstall(self) -> bool:
        subprocess.run(["systemctl", "--user", "disable", "--now", self.TIMER_NAME], capture_output=True)
        if self.service_path.exists():
            self.service_path.unlink()
        if self.timer_path.exists():
            self.timer_path.unlink()
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
        return True

    def start(self) -> bool:
        res = subprocess.run(["systemctl", "--user", "start", self.TIMER_NAME], capture_output=True)
        return res.returncode == 0

    def stop(self) -> bool:
        res = subprocess.run(["systemctl", "--user", "stop", self.TIMER_NAME], capture_output=True)
        return res.returncode == 0

    def status(self) -> DaemonStatus:
        installed = self.timer_path.exists() and self.service_path.exists()
        active = False
        schedule = "hourly"
        next_run = None
        last_run = None

        if installed:
            res = subprocess.run(["systemctl", "--user", "is-active", self.TIMER_NAME], capture_output=True, text=True)
            active = res.stdout.strip() == "active"

            timer_show = subprocess.run(
                ["systemctl", "--user", "show", self.TIMER_NAME, "--property=NextElapseUSecRealtime,LastTriggerUSec"],
                capture_output=True,
                text=True,
            )
            for line in timer_show.stdout.splitlines():
                if line.startswith("NextElapseUSecRealtime="):
                    next_run = line.split("=", 1)[1] or None
                elif line.startswith("LastTriggerUSec="):
                    last_run = line.split("=", 1)[1] or None

        return DaemonStatus(
            installed=installed,
            active=active,
            platform="linux",
            backend=self.name,
            schedule=schedule,
            target_command=get_default_daemon_command(),
            config_path=str(self.timer_path) if installed else None,
            next_run=next_run,
            last_run=last_run,
        )


class CrontabBackend(BaseDaemonBackend):
    """Linux user crontab fallback backend."""

    TAG_START = "# >>> prado-sync daemon >>>"
    TAG_END = "# <<< prado-sync daemon <<<"

    def __init__(self, log_dir: Optional[Path] = None):
        self.log_dir = log_dir or get_config_dir()
        self.log_file = self.log_dir / "daemon.log"

    @property
    def name(self) -> str:
        return "crontab"

    def _read_crontab(self) -> str:
        res = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        if res.returncode != 0:
            return ""
        return res.stdout

    def _write_crontab(self, content: str) -> bool:
        res = subprocess.run(["crontab", "-"], input=content, text=True, capture_output=True)
        return res.returncode == 0

    def install(self, interval_seconds: int = 3600) -> bool:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.uninstall()

        if interval_seconds <= 1800:
            cron_expr = "*/30 * * * *"
        elif interval_seconds <= 3600:
            cron_expr = "0 * * * *"
        elif interval_seconds >= 86400:
            days = max(1, min(31, int(interval_seconds) // 86400))
            cron_expr = "0 0 * * *" if days == 1 else f"0 0 */{days} * *"
        else:
            hours = max(1, min(23, int(interval_seconds) // 3600))
            cron_expr = f"0 */{hours} * * *"

        cmd_str = " ".join(f'"{c}"' if " " in c else c for c in get_default_daemon_command())
        job_line = f"{cron_expr} {cmd_str} >> {self.log_file} 2>&1"

        current = self._read_crontab()
        new_crontab = (current.rstrip() + f"\n\n{self.TAG_START}\n{job_line}\n{self.TAG_END}\n").lstrip()
        return self._write_crontab(new_crontab)

    def uninstall(self) -> bool:
        current = self._read_crontab()
        if self.TAG_START not in current:
            return True

        pattern = re.compile(rf"{re.escape(self.TAG_START)}.*?{re.escape(self.TAG_END)}\n?", re.DOTALL)
        cleaned = pattern.sub("", current)
        return self._write_crontab(cleaned.strip() + "\n" if cleaned.strip() else "")

    def start(self) -> bool:
        return True

    def stop(self) -> bool:
        return self.uninstall()

    def status(self) -> DaemonStatus:
        current = self._read_crontab()
        installed = self.TAG_START in current
        schedule = "hourly"
        if installed:
            match = re.search(
                rf"{re.escape(self.TAG_START)}\n(.*?)\s+.*?{re.escape(self.TAG_END)}",
                current,
                re.DOTALL,
            )
            if match:
                schedule = match.group(1).strip()

        return DaemonStatus(
            installed=installed,
            active=installed,
            platform="linux",
            backend=self.name,
            schedule=schedule,
            target_command=get_default_daemon_command(),
            config_path="crontab -l",
            log_file=str(self.log_file) if self.log_file.exists() else None,
        )


class SchtasksBackend(BaseDaemonBackend):
    """Windows Task Scheduler backend using schtasks.exe."""

    TASK_NAME = "PradoSync"

    @property
    def name(self) -> str:
        return "schtasks"

    def install(self, interval_seconds: int = 3600) -> bool:
        self.uninstall()
        cmd_args = get_default_daemon_command()
        tr_command = f'"{cmd_args[0]}" ' + " ".join(f'"{arg}"' if " " in arg else arg for arg in cmd_args[1:])

        if interval_seconds >= 86400:
            days = max(1, min(365, int(interval_seconds) // 86400))
            schedule_type = "DAILY"
            modifier = days
        else:
            schedule_type = "HOURLY"
            modifier = max(1, min(23, int(interval_seconds) // 3600))
        args = [
            "schtasks.exe",
            "/create",
            "/tn",
            self.TASK_NAME,
            "/tr",
            tr_command,
            "/sc",
            schedule_type,
            "/mo",
            str(modifier),
            "/f",
        ]
        res = subprocess.run(args, capture_output=True, text=True)
        return res.returncode == 0

    def uninstall(self) -> bool:
        args = ["schtasks.exe", "/delete", "/tn", self.TASK_NAME, "/f"]
        res = subprocess.run(args, capture_output=True, text=True)
        return res.returncode == 0

    def start(self) -> bool:
        args = ["schtasks.exe", "/run", "/tn", self.TASK_NAME]
        res = subprocess.run(args, capture_output=True, text=True)
        return res.returncode == 0

    def stop(self) -> bool:
        args = ["schtasks.exe", "/end", "/tn", self.TASK_NAME]
        res = subprocess.run(args, capture_output=True, text=True)
        return res.returncode == 0

    def status(self) -> DaemonStatus:
        args = ["schtasks.exe", "/query", "/tn", self.TASK_NAME, "/fo", "CSV", "/v"]
        res = subprocess.run(args, capture_output=True, text=True)
        installed = res.returncode == 0
        active = False
        last_run = None
        next_run = None

        if installed:
            active = True
            try:
                reader = csv.DictReader(io.StringIO(res.stdout))
                for row in reader:
                    next_run = row.get("Next Run Time") or None
                    last_run = row.get("Last Run Time") or None
                    status_str = row.get("Status", "").lower()
                    if "disabled" in status_str:
                        active = False
            except Exception:
                pass

        return DaemonStatus(
            installed=installed,
            active=active,
            platform="windows",
            backend=self.name,
            schedule="hourly",
            target_command=get_default_daemon_command(),
            config_path=f"Task Scheduler: {self.TASK_NAME}",
            next_run=next_run,
            last_run=last_run,
        )


class DaemonManager:
    """
    Unified cross-platform daemon manager.
    Automatically detects OS and dispatches to Launchd, Systemd (with Crontab fallback),
    or Schtasks.
    """

    def __init__(self, platform_override: Optional[str] = None):
        self.target_os = platform_override or sys.platform
        self.backend = self._resolve_backend()

    def _resolve_backend(self) -> BaseDaemonBackend:
        if self.target_os == "darwin":
            return LaunchdBackend()
        elif self.target_os.startswith("linux"):
            if SystemdBackend.is_available():
                return SystemdBackend()
            return CrontabBackend()
        elif self.target_os in ("win32", "windows"):
            return SchtasksBackend()
        else:
            return CrontabBackend()

    def install(self, interval_seconds: int = 3600) -> bool:
        return self.backend.install(interval_seconds=interval_seconds)

    def uninstall(self) -> bool:
        return self.backend.uninstall()

    def start(self) -> bool:
        return self.backend.start()

    def stop(self) -> bool:
        return self.backend.stop()

    def status(self) -> DaemonStatus:
        return self.backend.status()
