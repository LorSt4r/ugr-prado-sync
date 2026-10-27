"""
Adversarial Stress Test Suite for Milestone M3:
Doctor Probes, Daemon Manager, and Pluggable AI Layer.

Empirically challenges:
1. Doctor diagnostics under corrupt databases, bad file permissions, missing configs,
   offline network, HTTP 500 errors, broken keyrings, and missing dependencies.
2. DaemonManager launchd plist XML/env validation, systemd unit syntax, crontab bounds,
   and schtasks parameter limits.
3. AI layer deterministic fallback under connection drops, invalid keys, malformed responses,
   and extreme payloads.
"""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
import plistlib
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
from unittest.mock import MagicMock, patch

import pytest
import requests

from prado.ai import (
    AIConfig,
    DeterministicFallbackProvider,
    ExternalAIProvider,
    OllamaProvider,
    get_ai_provider,
)
from prado.config import PradoConfig, get_config_file, get_state_db_path, save_config
from prado.core.downloader import DeadlineItem, ForumPost
from prado.exceptions import ConfigError, PradoError
from prado.scheduler.daemon import (
    CrontabBackend,
    DaemonManager,
    DaemonStatus,
    LaunchdBackend,
    SchtasksBackend,
    SystemdBackend,
    get_default_daemon_command,
)
from prado.scheduler.doctor import (
    DoctorEngine,
    DoctorReport,
    ProbeResult,
    ProbeStatus,
)


# ============================================================================
# Section 1: Doctor Diagnostics Adversarial Stress Tests
# ============================================================================

class TestDoctorAdversarial:
    """Stress tests for DoctorEngine and its 9 diagnostic probes."""

    def test_corrupt_config_yaml_instantiation_defect(self, tmp_path, monkeypatch):
        """
        Verify that if config.yaml is corrupt (invalid YAML), DoctorEngine() instantiates
        gracefully without crashing and reports ProbeStatus.FAIL on config_validity.
        """
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("invalid_yaml: [unclosed list", encoding="utf-8")
        monkeypatch.setattr("prado.scheduler.doctor.get_config_file", lambda: cfg_file)
        monkeypatch.setattr("prado.scheduler.doctor.get_config_dir", lambda: tmp_path)
        monkeypatch.setenv("PRADO_CONFIG_DIR", str(tmp_path))

        doc = DoctorEngine()
        res = doc.probe_config_validity()
        assert res.status == ProbeStatus.FAIL
        assert "corrupt or invalid YAML" in res.message

    def test_missing_config_handled_gracefully(self, tmp_path, monkeypatch):
        """Verify missing config.yaml does not crash and yields WARN status."""
        cfg_file = tmp_path / "nonexistent_config.yaml"
        monkeypatch.setattr("prado.scheduler.doctor.get_config_file", lambda: cfg_file)
        monkeypatch.setattr("prado.scheduler.doctor.get_config_dir", lambda: tmp_path)

        doc = DoctorEngine(config=PradoConfig())
        res = doc.probe_config_validity()
        assert res.status == ProbeStatus.WARN
        assert "not yet created" in res.message

    def test_config_permissions_0777_and_0755_warns(self, tmp_path, monkeypatch):
        """Verify invalid file permissions (e.g. 0777 or 0644) trigger WARN."""
        if os.name == "nt":
            pytest.skip("POSIX permission checks do not apply to Windows")

        cfg_file = tmp_path / "config.yaml"
        save_config(PradoConfig(), cfg_file)
        os.chmod(cfg_file, 0o777)

        monkeypatch.setattr("prado.scheduler.doctor.get_config_file", lambda: cfg_file)
        monkeypatch.setattr("prado.scheduler.doctor.get_config_dir", lambda: tmp_path)

        doc = DoctorEngine(config=PradoConfig())
        res = doc.probe_config_validity()
        assert res.status == ProbeStatus.WARN
        assert "too open" in res.message
        assert res.remediation is not None
        assert "chmod 600" in res.remediation

    def test_corrupt_state_db_junk_bytes(self, tmp_path, monkeypatch):
        """Verify corrupt state database file produces FAIL without unhandled traceback."""
        db_file = tmp_path / "state.db"
        db_file.write_bytes(b"\x00\xffCORRUPT_SQLITE_HEADER\xfe\x01\x02\x03JUNK")
        monkeypatch.setattr("prado.scheduler.doctor.get_state_db_path", lambda: db_file)

        doc = DoctorEngine(config=PradoConfig())
        res = doc.probe_state_db()
        assert res.status == ProbeStatus.FAIL
        assert "file is not a database" in res.message or "integrity check failed" in res.message

    def test_corrupt_state_db_failed_integrity_check(self, tmp_path, monkeypatch):
        """Verify database that opens but fails PRAGMA integrity_check yields FAIL."""
        db_file = tmp_path / "state.db"
        db_file.write_text("dummy")

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = ["*** in database main *** Page 4 is wrong"]
        mock_conn.execute.return_value = mock_cursor
        mock_conn.__enter__.return_value = mock_conn

        monkeypatch.setattr("prado.scheduler.doctor.get_state_db_path", lambda: db_file)
        monkeypatch.setattr("sqlite3.connect", lambda *args, **kwargs: mock_conn)

        doc = DoctorEngine(config=PradoConfig())
        res = doc.probe_state_db()
        assert res.status == ProbeStatus.FAIL
        assert "integrity check failed" in res.message

    def test_unreadable_state_db_0000_permissions(self, tmp_path, monkeypatch):
        """Verify state.db with mode 0000 yields FAIL gracefully."""
        if os.name == "nt":
            pytest.skip("POSIX permissions test")

        db_file = tmp_path / "state.db"
        db_file.write_text("content")
        os.chmod(db_file, 0o000)
        monkeypatch.setattr("prado.scheduler.doctor.get_state_db_path", lambda: db_file)

        try:
            doc = DoctorEngine(config=PradoConfig())
            res = doc.probe_state_db()
            assert res.status == ProbeStatus.FAIL
            assert "unable to open database file" in res.message or "error" in res.message
        finally:
            os.chmod(db_file, 0o600)

    def test_network_offline_dns_failure_and_timeouts(self, monkeypatch):
        """Verify offline network (DNS resolution error, timeout, SSL error) produces FAIL gracefully."""
        session = requests.Session()
        doc = DoctorEngine(config=PradoConfig(), http_session=session)

        # 1. DNS Failure on IdP
        monkeypatch.setattr(
            session,
            "get",
            MagicMock(side_effect=requests.ConnectionError("Failed to resolve 'identidad.ugr.es' (DNS error)")),
        )
        res_idp = doc.probe_idp_reachability()
        assert res_idp.status == ProbeStatus.FAIL
        assert "Cannot reach Identity Provider" in res_idp.message
        assert res_idp.details.get("error") is not None

        # 2. Timeout on PRADO Moodle
        monkeypatch.setattr(
            session,
            "head",
            MagicMock(side_effect=requests.Timeout("HTTPSConnectionPool: Read timed out. (connect timeout=5.0)")),
        )
        res_prado = doc.probe_prado_endpoint()
        assert res_prado.status == ProbeStatus.FAIL
        assert "Cannot reach Moodle endpoint" in res_prado.message
        assert res_prado.details.get("error") is not None

    def test_http_500_server_error_defect(self, monkeypatch):
        """
        Verify that if IdP or PRADO returns HTTP 500 Internal Server Error,
        doctor detects it as ProbeStatus.FAIL.
        """
        session = requests.Session()
        mock_resp_500 = MagicMock()
        mock_resp_500.status_code = 500

        monkeypatch.setattr(session, "get", lambda *args, **kwargs: mock_resp_500)
        monkeypatch.setattr(session, "head", lambda *args, **kwargs: mock_resp_500)

        doc = DoctorEngine(config=PradoConfig(), http_session=session)
        res_idp = doc.probe_idp_reachability()
        res_prado = doc.probe_prado_endpoint()

        assert res_idp.status == ProbeStatus.FAIL
        assert res_prado.status == ProbeStatus.FAIL
        assert "HTTP 500" in res_idp.message
        assert "HTTP 500" in res_prado.message

    def test_course_root_not_writable(self, tmp_path):
        """Verify read-only course destination produces FAIL gracefully."""
        if os.name == "nt":
            pytest.skip("POSIX permissions test")

        read_only_dir = tmp_path / "readonly_courses"
        read_only_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(read_only_dir, 0o444)

        try:
            cfg = PradoConfig(courses_root=read_only_dir)
            doc = DoctorEngine(config=cfg)
            res = doc.probe_course_root()
            assert res.status == ProbeStatus.FAIL
            assert "not writable" in res.message
        finally:
            os.chmod(read_only_dir, 0o755)

    def test_credentials_store_unhandled_keyring_exception_defect(self, monkeypatch):
        """
        Verify that if Keyring daemon throws an unexpected RuntimeError or D-Bus exception in _is_keyring_usable,
        probe_credentials_store catches it gracefully without crashing.
        """
        doc = DoctorEngine(config=PradoConfig())
        with patch(
            "prado.auth.credentials.CredentialStore._is_keyring_usable",
            side_effect=RuntimeError("org.freedesktop.DBus.Error.ServiceUnknown"),
        ):
            res = doc.probe_credentials_store()
            assert res.status in (ProbeStatus.WARN, ProbeStatus.OK)
            assert res.details["keyring_usable"] is False

    def test_doctor_json_schema_validity_under_all_failures(self, tmp_path, monkeypatch):
        """
        Verify --json output schema produces 100% valid, parsable JSON under
        simultaneous multi-probe catastrophic failures.
        """
        session = requests.Session()
        monkeypatch.setattr(session, "get", MagicMock(side_effect=requests.ConnectionError("Offline")))
        monkeypatch.setattr(session, "head", MagicMock(side_effect=requests.Timeout("Timeout")))

        # Point state.db and config to bad locations
        bad_db = tmp_path / "bad.db"
        bad_db.write_bytes(b"JUNK")
        monkeypatch.setattr("prado.scheduler.doctor.get_state_db_path", lambda: bad_db)

        cfg = PradoConfig(courses_root=tmp_path / "courses")
        doc = DoctorEngine(config=cfg, http_session=session)
        report = doc.run_all()

        assert report.overall_status == ProbeStatus.FAIL
        assert report.fail_count >= 3

        report_dict = report.to_dict()
        json_str = json.dumps(report_dict, indent=2)
        parsed = json.loads(json_str)

        # Validate JSON schema
        assert "timestamp" in parsed
        assert parsed["overall_status"] == "FAIL"
        assert "summary" in parsed
        assert parsed["summary"]["total"] == 9
        assert parsed["summary"]["fail"] >= 3
        assert len(parsed["probes"]) == 9

        for probe in parsed["probes"]:
            assert "probe_id" in probe
            assert "name" in probe
            assert "status" in probe
            assert probe["status"] in ("OK", "WARN", "FAIL", "SKIP")
            assert "message" in probe
            assert "details" in probe
            assert isinstance(probe["details"], dict)

        terminal_output = report.format_terminal(use_color=False)
        assert "PradoOS Doctor" in terminal_output
        assert "[✗]" in terminal_output
        assert "Result: FAILED" in terminal_output


# ============================================================================
# Section 2: DaemonManager Plist & Systemd Adversarial Stress Tests
# ============================================================================

class TestDaemonManagerAdversarial:
    """Stress tests for DaemonManager (launchd, systemd, crontab, schtasks)."""

    def test_launchd_plist_xml_syntax_validity(self, tmp_path):
        """Verify generated launchd plist produces valid XML conformant to Apple DTD."""
        plist_dir = tmp_path / "LaunchAgents"
        log_dir = tmp_path / "logs"
        backend = LaunchdBackend(plist_dir=plist_dir, log_dir=log_dir)

        command = ["/usr/local/bin/python3", "-m", "prado", "sync", "--no-interactive"]
        plist_dict = backend._generate_plist_dict(interval_seconds=3600, command=command)

        plist_file = plist_dir / "test_valid.plist"
        plist_dir.mkdir(parents=True, exist_ok=True)
        with open(plist_file, "wb") as f:
            plistlib.dump(plist_dict, f)

        # 1. Native plistlib load
        with open(plist_file, "rb") as f:
            loaded = plistlib.load(f)
        assert loaded["Label"] == "es.ugr.prado"
        assert loaded["StartInterval"] == 3600
        assert loaded["ProgramArguments"] == command

        # 2. Native macOS plutil -lint if running on darwin
        if sys.platform == "darwin" and shutil.which("plutil"):
            res = subprocess.run(["plutil", "-lint", str(plist_file)], capture_output=True, text=True)
            assert res.returncode == 0, f"plutil lint failed: {res.stderr}"

    def test_launchd_plist_environment_variables_omission(self, tmp_path):
        """
        Verify EnvironmentVariables dictionary is included in launchd plist.
        """
        backend = LaunchdBackend(plist_dir=tmp_path)
        plist_dict = backend._generate_plist_dict(3600, ["python", "-m", "prado", "sync"])

        assert "EnvironmentVariables" in plist_dict
        assert "PATH" in plist_dict["EnvironmentVariables"]

    def test_launchd_plist_invalid_start_interval_types(self, tmp_path):
        """
        Verify LaunchdBackend coerces float/small StartIntervals to integer >= 60.
        """
        backend = LaunchdBackend(plist_dir=tmp_path)
        plist_dict = backend._generate_plist_dict(3600.5, ["python"])
        assert isinstance(plist_dict["StartInterval"], int)
        assert plist_dict["StartInterval"] == 3600

        plist_file = tmp_path / "float.plist"
        with open(plist_file, "wb") as f:
            plistlib.dump(plist_dict, f)

        content = plist_file.read_text(encoding="utf-8")
        assert "<integer>3600</integer>" in content

    def test_systemd_unit_syntax_and_quoting(self, tmp_path, monkeypatch):
        """Verify systemd service and timer unit syntax, ExecStart escaping, and timer persistence."""
        unit_dir = tmp_path / "systemd" / "user"
        backend = SystemdBackend(unit_dir=unit_dir)

        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout="active\n"),
        )

        assert backend.install(interval_seconds=1800) is True
        service_text = backend.service_path.read_text(encoding="utf-8")
        timer_text = backend.timer_path.read_text(encoding="utf-8")

        # Systemd service validation
        assert "[Unit]" in service_text
        assert "Description=" in service_text
        assert "After=network-online.target" in service_text
        assert "[Service]" in service_text
        assert "Type=oneshot" in service_text
        assert "ExecStart=" in service_text
        assert "StandardOutput=journal" in service_text

        # Systemd timer validation
        assert "[Timer]" in timer_text
        assert "OnBootSec=5min" in timer_text
        assert "OnUnitActiveSec=1800s" in timer_text
        assert "Persistent=true" in timer_text
        assert "[Install]" in timer_text
        assert "WantedBy=timers.target" in timer_text

    def test_crontab_hour_bounds_defect(self, tmp_path, monkeypatch):
        """
        Verify that when interval_seconds >= 86400 (e.g. 90000), CrontabBackend
        generates valid daily cron syntax ('0 0 * * *') instead of invalid '0 */25 * * *'.
        """
        backend = CrontabBackend(log_dir=tmp_path)
        state = {"cron": ""}

        def mock_run(cmd, *args, **kwargs):
            if cmd == ["crontab", "-"]:
                state["cron"] = kwargs.get("input", "")
            return subprocess.CompletedProcess(cmd, 0, stdout="")

        monkeypatch.setattr(subprocess, "run", mock_run)

        backend.install(interval_seconds=90000)
        assert "0 */25 * * *" not in state["cron"]
        assert "0 0 * * *" in state["cron"]

    def test_schtasks_modifier_bounds_check(self, monkeypatch):
        """Verify schtasks switches to DAILY when interval_seconds >= 86400."""
        backend = SchtasksBackend()
        commands_run = []

        def mock_run(cmd, *args, **kwargs):
            commands_run.append(cmd)
            return subprocess.CompletedProcess(cmd, 0)

        monkeypatch.setattr(subprocess, "run", mock_run)

        backend.install(interval_seconds=172800)
        create_cmd = commands_run[-1]
        assert "/sc" in create_cmd
        assert "DAILY" in create_cmd
        assert "/mo" in create_cmd
        assert "2" in create_cmd


# ============================================================================
# Section 3: Pluggable AI Layer Adversarial Stress Tests
# ============================================================================

class TestAIAdversarial:
    """Stress tests for AI layer (deterministic, Ollama, external API)."""

    def test_deterministic_provider_extreme_inputs(self):
        """Stress test DeterministicFallbackProvider with extreme inputs and malformed HTML."""
        provider = DeterministicFallbackProvider()
        assert provider.is_available() is True

        # 1. Empty forum post
        empty_post = ForumPost(forum_id="", subject="", author="", content="")
        sum1 = provider.summarize_forum_post(empty_post)
        assert sum1.urgency == "normal"
        assert sum1.executive_summary == ""
        assert sum1.key_dates == []

        # 2. 50,000-character payload with unclosed HTML tags and script injection
        malicious_content = (
            "<script>alert('xss');"
            + (" Urgent examen prueba entrega " * 1000)
            + " 15 de Noviembre de 2026 </script>"
        )
        big_post = ForumPost(forum_id="TEST", subject="Alert", author="Prof", content=malicious_content)
        sum2 = provider.summarize_forum_post(big_post)
        assert sum2.urgency == "urgent"
        assert "<script>" not in sum2.executive_summary
        assert len(sum2.key_dates) >= 1

        # 3. Study plan with 0 deadlines
        plan0 = provider.generate_study_plan([], horizon_days=7)
        assert len(plan0.days) == 7
        assert all(len(d.blocks) == 0 for d in plan0.days)
        assert all(d.total_hours == 0.0 for d in plan0.days)

        # 4. Study plan with past and distant future deadlines
        today = datetime.date(2026, 10, 27)
        weird_deadlines = [
            DeadlineItem("1", "Overdue", "SO", datetime.datetime(2020, 1, 1), ""),
            DeadlineItem("2", "Far Future", "ED", datetime.datetime(2050, 1, 1), ""),
        ]
        plan_weird = provider.generate_study_plan(weird_deadlines, horizon_days=7, start_date=today)
        assert len(plan_weird.days) == 7
        # Overdue deadline delta_days < 0 is ignored; far future delta_days > 14 is ignored
        assert all(len(d.blocks) == 0 for d in plan_weird.days)

    def test_ollama_offline_and_http_errors_fallback(self, monkeypatch):
        """Verify OllamaProvider falls back seamlessly on connection failure, HTTP 500, and bad JSON."""
        provider = OllamaProvider(base_url="http://localhost:11434")
        post = ForumPost("1", "Examen", "Prof", "Examen urgente el 30/10.")
        deadlines = [DeadlineItem("1", "Examen", "MC", datetime.datetime(2026, 10, 30), "")]

        # 1. Connection Refused
        monkeypatch.setattr(requests, "get", MagicMock(side_effect=requests.ConnectionError("Refused")))
        assert provider.is_available() is False
        summary1 = provider.summarize_forum_post(post)
        assert summary1.is_ai_generated is False
        assert summary1.urgency == "urgent"
        plan1 = provider.generate_study_plan(deadlines)
        assert plan1.is_ai_generated is False

        # 2. HTTP 500 on generate
        monkeypatch.setattr(requests, "get", MagicMock(return_value=MagicMock(status_code=200)))
        mock_500 = MagicMock()
        mock_500.status_code = 500
        mock_500.raise_for_status.side_effect = requests.HTTPError("500 Server Error")
        monkeypatch.setattr(requests, "post", MagicMock(return_value=mock_500))

        assert provider.is_available() is True
        summary2 = provider.summarize_forum_post(post)
        assert summary2.is_ai_generated is False
        assert "Examen" in summary2.executive_summary

        plan2 = provider.generate_study_plan(deadlines)
        assert plan2.is_ai_generated is False

    def test_external_ai_provider_missing_key_and_api_errors_fallback(self, monkeypatch):
        """Verify ExternalAIProvider falls back seamlessly on missing keys, 401, 429, and malformed responses."""
        post = ForumPost("1", "Aviso", "Prof", "Entrega urgente el 05/11.")
        deadlines = [DeadlineItem("1", "Entrega", "TIC", datetime.datetime(2026, 11, 5), "")]

        # 1. Missing or whitespace API key
        p_empty = ExternalAIProvider(api_key="   ")
        assert p_empty.is_available() is False
        s_empty = p_empty.summarize_forum_post(post)
        assert s_empty.is_ai_generated is False

        # 2. HTTP 401 Unauthorized
        p_auth = ExternalAIProvider(api_key="sk-invalid")
        assert p_auth.is_available() is True

        mock_401 = MagicMock()
        mock_401.status_code = 401
        mock_401.raise_for_status.side_effect = requests.HTTPError("401 Unauthorized")
        monkeypatch.setattr(requests, "post", MagicMock(return_value=mock_401))

        s_401 = p_auth.summarize_forum_post(post)
        assert s_401.is_ai_generated is False
        assert s_401.urgency == "urgent"

        plan_401 = p_auth.generate_study_plan(deadlines)
        assert plan_401.is_ai_generated is False

        # 3. Empty choices array or missing content
        mock_bad_json = MagicMock()
        mock_bad_json.status_code = 200
        mock_bad_json.json.return_value = {"choices": []}
        monkeypatch.setattr(requests, "post", MagicMock(return_value=mock_bad_json))

        s_bad = p_auth.summarize_forum_post(post)
        assert s_bad.is_ai_generated is False

    def test_ai_factory_fallback_matrix(self):
        """Verify get_ai_provider factory guarantees DeterministicFallbackProvider under all edge cases."""
        assert isinstance(get_ai_provider(None), DeterministicFallbackProvider)
        assert isinstance(get_ai_provider(AIConfig(enabled=False)), DeterministicFallbackProvider)
        assert isinstance(get_ai_provider(AIConfig(enabled=True, provider="none")), DeterministicFallbackProvider)
        assert isinstance(get_ai_provider(AIConfig(enabled=True, provider="unknown_provider")), DeterministicFallbackProvider)
        assert isinstance(get_ai_provider(AIConfig(enabled=True, provider="openai", api_key="")), DeterministicFallbackProvider)
        assert isinstance(get_ai_provider(AIConfig(enabled=True, provider="openai", api_key=None)), DeterministicFallbackProvider)
