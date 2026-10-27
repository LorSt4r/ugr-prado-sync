"""
Unit tests for prado doctor diagnostics (9 probes) and report generation.
"""

from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import sys
from unittest.mock import MagicMock
import pytest
import requests

from prado.config import PradoConfig, get_config_file, get_state_db_path, save_config
from prado.scheduler.doctor import (
    DoctorEngine,
    DoctorReport,
    PradoDoctor,
    ProbeResult,
    ProbeStatus,
)


def test_doctor_python_env_probe(monkeypatch):
    doc = DoctorEngine()
    res = doc.probe_python_env()
    assert res.probe_id == "python_env"
    assert res.status in (ProbeStatus.OK, ProbeStatus.WARN)
    assert "python_version" in res.details

    # Test outdated version (<3.10)
    monkeypatch.setattr(sys, "version_info", (3, 9, 7, "final", 0))
    res_fail = doc.probe_python_env()
    assert res_fail.status == ProbeStatus.FAIL
    assert "Python >= 3.10 required" in res_fail.message


def test_doctor_config_validity_probe(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.yaml"
    monkeypatch.setattr("prado.scheduler.doctor.get_config_file", lambda: cfg_file)
    monkeypatch.setattr("prado.scheduler.doctor.get_config_dir", lambda: tmp_path)

    doc = DoctorEngine()

    # 1. Missing config -> WARN
    res1 = doc.probe_config_validity()
    assert res1.status == ProbeStatus.WARN
    assert "not yet created" in res1.message

    # 2. Corrupt config -> FAIL
    cfg_file.write_text("invalid: yaml: [unclosed", encoding="utf-8")
    res2 = doc.probe_config_validity()
    assert res2.status == ProbeStatus.FAIL
    assert "corrupt or invalid YAML" in res2.message

    # 3. Valid config -> OK
    save_config(PradoConfig(), cfg_file)
    res3 = doc.probe_config_validity()
    assert res3.status == ProbeStatus.OK
    assert "Valid config" in res3.message


def test_doctor_state_db_probe(tmp_path, monkeypatch):
    db_file = tmp_path / "state.db"
    monkeypatch.setattr("prado.scheduler.doctor.get_state_db_path", lambda: db_file)

    doc = DoctorEngine()

    # 1. Not created yet -> OK
    res1 = doc.probe_state_db()
    assert res1.status == ProbeStatus.OK
    assert "not created yet" in res1.message

    # 2. Created and healthy -> OK
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE meta (k TEXT, v TEXT);")
    conn.execute("CREATE TABLE courses (course_id INT);")
    conn.execute("CREATE TABLE files (path TEXT);")
    conn.commit()
    conn.close()

    res2 = doc.probe_state_db()
    assert res2.status == ProbeStatus.OK
    assert "SQLite OK" in res2.message

    # 3. Corrupted DB -> FAIL
    with open(db_file, "wb") as f:
        f.write(b"NOT A SQLITE DB HEADER JUNK DATA")

    res3 = doc.probe_state_db()
    assert res3.status == ProbeStatus.FAIL


def test_doctor_credentials_store_probe(monkeypatch):
    doc = DoctorEngine()

    # Mock no credentials found
    monkeypatch.setattr(
        "prado.auth.credentials.CredentialStore.get_sso_credentials",
        MagicMock(side_effect=Exception("No credentials")),
    )
    res1 = doc.probe_credentials_store()
    assert res1.status == ProbeStatus.WARN
    assert "No SSO credentials found" in res1.message

    # Mock credentials found
    monkeypatch.setattr(
        "prado.auth.credentials.CredentialStore.get_sso_credentials",
        MagicMock(return_value=("student", "secret_pass")),
    )
    res2 = doc.probe_credentials_store()
    assert res2.status == ProbeStatus.OK
    assert "Credentials active" in res2.message
    # Critical integrity: password must NEVER be in message or details
    assert "secret_pass" not in res2.message
    assert "secret_pass" not in str(res2.details)


def test_doctor_idp_reachability_probe(monkeypatch):
    session = requests.Session()
    doc = DoctorEngine(http_session=session)

    # 1. Successful reachability
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    monkeypatch.setattr(session, "get", lambda *args, **kwargs: mock_resp)

    res1 = doc.probe_idp_reachability()
    assert res1.status == ProbeStatus.OK
    assert "responding" in res1.message

    # 2. Connection failure
    monkeypatch.setattr(
        session,
        "get",
        MagicMock(side_effect=requests.ConnectionError("DNS lookup failed")),
    )
    res2 = doc.probe_idp_reachability()
    assert res2.status == ProbeStatus.FAIL
    assert "Cannot reach Identity Provider" in res2.message


def test_doctor_prado_endpoint_probe(monkeypatch):
    session = requests.Session()
    doc = DoctorEngine(http_session=session)

    # 1. Successful reachability
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    monkeypatch.setattr(session, "head", lambda *args, **kwargs: mock_resp)

    res1 = doc.probe_prado_endpoint()
    assert res1.status == ProbeStatus.OK
    assert "responding" in res1.message

    # 2. Connection failure
    monkeypatch.setattr(
        session,
        "head",
        MagicMock(side_effect=requests.Timeout("Connection timed out")),
    )
    res2 = doc.probe_prado_endpoint()
    assert res2.status == ProbeStatus.FAIL
    assert "Cannot reach Moodle endpoint" in res2.message


def test_doctor_course_root_probe(tmp_path):
    root_dir = tmp_path / "courses"
    cfg = PradoConfig(courses_root=root_dir)
    doc = DoctorEngine(config=cfg)

    res = doc.probe_course_root()
    assert res.status == ProbeStatus.OK
    assert "Writable" in res.message
    assert root_dir.exists()


def test_doctor_daemon_status_probe():
    doc = DoctorEngine()
    res = doc.probe_daemon_status()
    assert res.probe_id == "daemon_status"
    assert res.status in (ProbeStatus.OK, ProbeStatus.WARN)
    assert "Background Sync Daemon" in res.name


def test_doctor_dependencies_probe(monkeypatch):
    doc = DoctorEngine()
    res1 = doc.probe_dependencies_and_artifacts()
    assert res1.status == ProbeStatus.OK
    assert "dependencies verified" in res1.message

    # Mock missing dependency
    import importlib
    orig_import = importlib.import_module

    def mock_import(name, *args, **kwargs):
        if name == "cryptography":
            raise ImportError("No module named cryptography")
        return orig_import(name, *args, **kwargs)

    monkeypatch.setattr("importlib.import_module", mock_import)
    res2 = doc.probe_dependencies_and_artifacts()
    assert res2.status == ProbeStatus.FAIL
    assert "Missing core dependencies: cryptography" in res2.message


def test_doctor_report_aggregation_and_formatting():
    p1 = ProbeResult(probe_id="p1", name="Probe 1", status=ProbeStatus.OK, message="Good")
    p2 = ProbeResult(probe_id="p2", name="Probe 2", status=ProbeStatus.WARN, message="Check this", remediation="Do X")
    report_warn = DoctorReport(timestamp="2026-10-27T20:00:00Z", overall_status=ProbeStatus.WARN, probes=[p1, p2])

    d = report_warn.to_dict()
    assert d["overall_status"] == "WARN"
    assert d["summary"]["ok"] == 1
    assert d["summary"]["warn"] == 1
    assert d["summary"]["fail"] == 0

    term = report_warn.format_terminal(use_color=False)
    assert "PradoOS Doctor" in term
    assert "[✓] Probe 1" in term
    assert "[⚠] Probe 2" in term
    assert "Remediation Suggestions:" in term
    assert "Do X" in term
