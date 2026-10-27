"""
CLI JSON Protocol and Agent Execution E2E Tests.

Tests non-interactive JSON protocol across real CLI commands:
- prado discover --json
- prado sync --json
- prado doctor --json
- prado auth status --json
- prado courses list --json
- prado star --no-browser --json
- Exit code contracts: 0 (success), 1 (error), 2 (mfa_required)
"""

from __future__ import annotations

import json
import pytest

from prado.cli import main
from prado.config import PradoConfig, save_config
from prado.exceptions import MfaRequiredError


def _authenticate_mock_session(mock_http_session, mock_prado_transport):
    mock_prado_transport.active_sessions["mock_sess_1"] = {
        "authenticated": True,
        "user": "testuser@correo.ugr.es",
    }
    mock_http_session.cookies.set("MoodleSession", "mock_sess_1", domain="pradogrado2627.ugr.es")
    return mock_http_session


class TestCliJsonProtocol:
    """Tests structured JSON output and exit code contracts through prado.cli.main."""

    def test_json_protocol_discover_output_schema(
        self,
        mock_config_dir,
        mock_courses_dir,
        mock_http_session,
        mock_prado_transport,
        monkeypatch,
        capsys,
    ):
        save_config(PradoConfig(username="testuser@correo.ugr.es", courses_root=mock_courses_dir))
        authed_sess = _authenticate_mock_session(mock_http_session, mock_prado_transport)
        monkeypatch.setattr("prado.cli._obtain_authenticated_session", lambda **kw: authed_sess)

        code = main(["discover", "--json"])
        out = capsys.readouterr().out
        parsed = json.loads(out)

        assert code == 0
        assert parsed["status"] == "success"
        assert parsed["courses_count"] == 5
        assert len(parsed["courses"]) == 5
        assert parsed["courses"][0]["slug"] == "ED_C"

    def test_json_protocol_sync_summary_schema(
        self,
        mock_config_dir,
        mock_courses_dir,
        mock_http_session,
        mock_prado_transport,
        monkeypatch,
        capsys,
    ):
        save_config(PradoConfig(username="testuser@correo.ugr.es", courses_root=mock_courses_dir))
        authed_sess = _authenticate_mock_session(mock_http_session, mock_prado_transport)
        monkeypatch.setattr("prado.cli._obtain_authenticated_session", lambda **kw: authed_sess)

        code = main(["sync", "--course", "15819", "--json"])
        out = capsys.readouterr().out
        parsed = json.loads(out)

        assert code == 0
        assert parsed["status"] == "success"
        assert parsed["courses_synced"] == 1
        assert parsed["downloaded"] >= 1
        assert parsed["deadlines"] == 1

    def test_json_protocol_doctor_diagnostic_schema(
        self, mock_config_dir, mock_courses_dir, monkeypatch, capsys
    ):
        save_config(PradoConfig(username="testuser@correo.ugr.es", courses_root=mock_courses_dir))
        code = main(["doctor", "--json"])
        out = capsys.readouterr().out
        parsed = json.loads(out)

        assert code in (0, 1)
        assert "verdict" in parsed
        assert "probes" in parsed
        assert len(parsed["probes"]) == 9

    def test_json_protocol_mfa_challenge_exit_code_2(
        self, mock_config_dir, monkeypatch, capsys
    ):
        def raise_mfa(**kwargs):
            raise MfaRequiredError(prompt="Verification code needed", factor="email", tier=3)

        monkeypatch.setattr("prado.cli._obtain_authenticated_session", raise_mfa)
        code = main(["discover", "--json"])
        out = capsys.readouterr().out
        parsed = json.loads(out)

        assert code == 2
        assert parsed["status"] == "mfa_required"
        assert parsed["tier"] == 3
        assert parsed["factor"] == "email"
        assert "retry_command" in parsed

    def test_json_protocol_general_error_exit_code_1(
        self, mock_config_dir, capsys
    ):
        code = main(["courses", "enable", "not_an_integer", "--json"])
        out = capsys.readouterr().out
        parsed = json.loads(out)

        assert code == 1
        assert parsed["status"] == "error"
        assert parsed["code"] == "ConfigError"

    def test_json_protocol_auth_status_and_star(
        self, mock_config_dir, in_memory_keyring, capsys
    ):
        code_auth = main(["auth", "status", "--offline", "--json"])
        out_auth = json.loads(capsys.readouterr().out)
        assert code_auth == 0
        assert out_auth["status"] == "success"

        code_star = main(["star", "--no-browser", "--json"])
        out_star = json.loads(capsys.readouterr().out)
        assert code_star == 0
        assert out_star["repo"] == "LorSt4r/ugr-prado-sync"
