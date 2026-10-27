"""
Unit tests for PradoOS cross-platform background daemon manager.
"""

from __future__ import annotations

from pathlib import Path
import plistlib
import subprocess
import sys
import pytest

from prado.scheduler.daemon import (
    CrontabBackend,
    DaemonManager,
    DaemonStatus,
    LaunchdBackend,
    SchtasksBackend,
    SystemdBackend,
    get_default_daemon_command,
)


def test_default_daemon_command():
    cmd = get_default_daemon_command()
    assert cmd[0] == sys.executable
    assert cmd[1:4] == ["-m", "prado", "sync"]
    assert "--no-interactive" in cmd


def test_launchd_plist_generation(tmp_path):
    plist_dir = tmp_path / "LaunchAgents"
    log_dir = tmp_path / "logs"
    backend = LaunchdBackend(plist_dir=plist_dir, log_dir=log_dir)

    plist_data = backend._generate_plist_dict(3600, ["python", "-m", "prado", "sync"])
    assert plist_data["Label"] == "es.ugr.prado"
    assert plist_data["StartInterval"] == 3600
    assert plist_data["RunAtLoad"] is True
    assert plist_data["ProgramArguments"] == ["python", "-m", "prado", "sync"]
    assert "daemon.log" in plist_data["StandardOutPath"]


def test_systemd_unit_file_generation(tmp_path, monkeypatch):
    unit_dir = tmp_path / "systemd" / "user"
    backend = SystemdBackend(unit_dir=unit_dir)

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout="active\n"),
    )

    success = backend.install(interval_seconds=1800)
    assert success is True
    assert backend.service_path.exists()
    assert backend.timer_path.exists()

    service_txt = backend.service_path.read_text(encoding="utf-8")
    assert "ExecStart=" in service_txt
    assert "Type=oneshot" in service_txt

    timer_txt = backend.timer_path.read_text(encoding="utf-8")
    assert "OnUnitActiveSec=1800s" in timer_txt


def test_crontab_injection_and_removal(tmp_path, monkeypatch):
    backend = CrontabBackend(log_dir=tmp_path)

    existing_cron = "# Existing user job\n30 2 * * * /backup.sh\n"
    state = {"cron": existing_cron}

    def mock_run(cmd, *args, **kwargs):
        if cmd == ["crontab", "-l"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=state["cron"])
        elif cmd == ["crontab", "-"]:
            state["cron"] = kwargs.get("input", "")
            return subprocess.CompletedProcess(cmd, 0)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", mock_run)

    # 1. Install
    assert backend.install(interval_seconds=3600) is True
    assert CrontabBackend.TAG_START in state["cron"]
    assert "prado" in state["cron"]
    assert "/backup.sh" in state["cron"]

    # 2. Status
    status = backend.status()
    assert status.installed is True
    assert status.active is True
    assert status.backend == "crontab"

    # 3. Uninstall
    assert backend.uninstall() is True
    assert CrontabBackend.TAG_START not in state["cron"]
    assert "/backup.sh" in state["cron"]


def test_schtasks_backend_commands(monkeypatch):
    backend = SchtasksBackend()
    captured_commands = []

    def mock_run(cmd, *args, **kwargs):
        captured_commands.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="TaskName,Next Run Time,Status\nPradoSync,10/28/2026,Ready\n")

    monkeypatch.setattr(subprocess, "run", mock_run)

    assert backend.install(interval_seconds=7200) is True
    # Verify schtasks /create args
    create_call = captured_commands[-1]
    assert create_call[0] == "schtasks.exe"
    assert "/create" in create_call
    assert "/tn" in create_call
    assert "PradoSync" in create_call
    assert "/mo" in create_call
    assert "2" in create_call  # 7200s // 3600 = 2 hours

    status = backend.status()
    assert status.installed is True
    assert status.backend == "schtasks"
    assert status.platform == "windows"


def test_daemon_manager_platform_dispatch():
    darwin_mgr = DaemonManager(platform_override="darwin")
    assert isinstance(darwin_mgr.backend, LaunchdBackend)

    win_mgr = DaemonManager(platform_override="win32")
    assert isinstance(win_mgr.backend, SchtasksBackend)


def test_daemon_status_to_dict():
    stat = DaemonStatus(
        installed=True,
        active=True,
        platform="darwin",
        backend="launchd",
        schedule="every 3600s",
        target_command=["python", "-m", "prado", "sync"],
    )
    d = stat.to_dict()
    assert d["installed"] is True
    assert d["backend"] == "launchd"
    text = stat.format_terminal()
    assert "Active" in text
    assert "launchd" in text
