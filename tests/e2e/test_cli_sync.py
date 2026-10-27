"""
CLI Sync Command E2E Tests (prado sync).

Tests CLI synchronization behaviors via prado.cli.main:
- prado sync (full sync across all active courses)
- prado sync --course <id> (selective single course sync)
- prado sync --dry-run (simulation preview without disk modifications)
- prado sync --force (re-checks and overwrites unmodified files)
- Core exporters creation (DASHBOARD.md, CHANGELOG.md, deadlines.ics)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest

from prado.cli import main
from prado.config import PradoConfig, SyncConfig, save_config


def _authenticate_mock_session(mock_http_session, mock_prado_transport):
    mock_prado_transport.active_sessions["mock_sess_sync"] = {
        "authenticated": True,
        "user": "testuser@correo.ugr.es",
    }
    mock_http_session.cookies.set("MoodleSession", "mock_sess_sync", domain="pradogrado2627.ugr.es")
    return mock_http_session


class TestCliSyncCommand:
    """Tests the synchronization execution and flags via prado.cli.main."""

    def test_sync_dry_run_leaves_destination_untouched(
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

        initial_files = list(mock_courses_dir.rglob("*"))
        code = main(["sync", "--course", "15819", "--dry-run", "--json"])
        out = json.loads(capsys.readouterr().out)

        final_files = list(mock_courses_dir.rglob("*"))
        assert code == 0
        assert out["dry_run"] is True
        assert len(out["planned_actions"]) >= 4
        assert initial_files == final_files

    def test_sync_selective_course_sync(
        self,
        mock_config_dir,
        mock_courses_dir,
        mock_http_session,
        mock_prado_transport,
        monkeypatch,
        capsys,
    ):
        save_config(
            PradoConfig(
                username="testuser@correo.ugr.es",
                courses_root=mock_courses_dir,
                sync=SyncConfig(preset="smart", subgroups={"15819": "C2"}),
            )
        )
        authed_sess = _authenticate_mock_session(mock_http_session, mock_prado_transport)
        monkeypatch.setattr("prado.cli._obtain_authenticated_session", lambda **kw: authed_sess)

        code = main(["sync", "--course", "ED_C", "--json"])
        out = json.loads(capsys.readouterr().out)
        assert code == 0
        assert out["courses_synced"] == 1

        c_dir = mock_courses_dir / "ED_C"
        other_dir = mock_courses_dir / "SO_E"
        assert c_dir.exists()
        assert not other_dir.exists()

    def test_sync_creates_core_markdown_exporters(
        self,
        mock_config_dir,
        mock_courses_dir,
        mock_http_session,
        mock_prado_transport,
        monkeypatch,
    ):
        save_config(PradoConfig(username="testuser@correo.ugr.es", courses_root=mock_courses_dir))
        authed_sess = _authenticate_mock_session(mock_http_session, mock_prado_transport)
        monkeypatch.setattr("prado.cli._obtain_authenticated_session", lambda **kw: authed_sess)

        code = main(["sync", "--course", "15819", "--no-interactive"])
        assert code == 0

        dash = mock_courses_dir / "DASHBOARD.md"
        cl = mock_courses_dir / "CHANGELOG.md"
        cal = mock_courses_dir / "deadlines.ics"

        assert dash.exists()
        assert cl.exists()
        assert cal.exists()
        assert "BEGIN:VCALENDAR" in cal.read_text(encoding="utf-8")

    def test_sync_sha256_integrity_match(
        self,
        mock_config_dir,
        mock_courses_dir,
        mock_http_session,
        mock_prado_transport,
        sample_html_fixtures,
        monkeypatch,
    ):
        save_config(PradoConfig(username="testuser@correo.ugr.es", courses_root=mock_courses_dir))
        authed_sess = _authenticate_mock_session(mock_http_session, mock_prado_transport)
        monkeypatch.setattr("prado.cli._obtain_authenticated_session", lambda **kw: authed_sess)

        main(["sync", "--course", "15819", "--no-interactive"])
        ipynb_files = list((mock_courses_dir / "ED_C").rglob("*.ipynb"))
        assert len(ipynb_files) == 1
        expected_hash = hashlib.sha256(sample_html_fixtures["sample_ipynb_content"]).hexdigest()
        actual_hash = hashlib.sha256(ipynb_files[0].read_bytes()).hexdigest()
        assert actual_hash == expected_hash

    def test_sync_force_flag_replaces_clean_files(
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

        main(["sync", "--course", "15819", "--json"])
        capsys.readouterr()

        # Second sync without force skips already downloaded files
        main(["sync", "--course", "15819", "--json"])
        out_skip = json.loads(capsys.readouterr().out)
        assert out_skip["downloaded"] == 0

        # Sync with --force re-downloads them
        main(["sync", "--course", "15819", "--force", "--json"])
        out_force = json.loads(capsys.readouterr().out)
        assert out_force["downloaded"] >= 1
