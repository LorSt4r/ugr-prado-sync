"""
CLI Onboarding Flow E2E Tests (prado onboard).

Exercises the 2-Phase progressive disclosure onboarding flow via OnboardingWizard and CLI:
- Phase 1: Credentials -> Destination Folder -> Course Selection -> Config Persistence -> Star Prompt
- Phase 2: Power-up configuration (subgroups, IMAP, notifications, daemon)
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from prado.auth.credentials import CredentialStore
from prado.cli import main
from prado.config import load_config
from prado.onboarding.star import has_been_prompted, maybe_prompt_star_after_sync
from prado.onboarding.wizard import OnboardingWizard


class TestCliOnboardFlow:
    """Tests the onboarding wizard flow and CLI command."""

    def test_onboard_phase1_creates_valid_config(
        self, mock_config_dir, mock_courses_dir, in_memory_keyring, capsys
    ):
        code = main([
            "onboard",
            "--username", "student@ugr.es",
            "--password", "secret_pass",
            "--courses-root", str(mock_courses_dir),
            "--preset", "smart",
            "--semester", "1",
            "--no-interactive",
            "--json",
        ])
        out = json.loads(capsys.readouterr().out)
        assert code == 0
        assert out["status"] == "success"

        loaded = load_config()
        assert loaded.username == "student@ugr.es"
        assert loaded.courses_root == mock_courses_dir
        assert loaded.sync.preset == "smart"
        assert loaded.sync.semester == 1

        store = CredentialStore(use_env=False)
        creds = store.get_sso_credentials("student@ugr.es")
        assert creds == ("student@ugr.es", "secret_pass")

    def test_onboard_phase1_destination_folder_creation(
        self, mock_config_dir, mock_courses_dir, in_memory_keyring
    ):
        dest = mock_courses_dir / "My_UGR_Courses"
        wizard = OnboardingWizard()
        wizard.run_phase1(
            username="student@ugr.es",
            password="secret",
            courses_root=dest,
            preset="mirror",
            interactive=False,
        )
        assert dest.exists()
        assert dest.is_dir()
        assert load_config().sync.preset == "mirror"

    def test_onboard_phase2_subgroup_configuration(
        self, mock_config_dir, mock_courses_dir, in_memory_keyring, capsys
    ):
        code = main([
            "onboard",
            "--username", "student@ugr.es",
            "--courses-root", str(mock_courses_dir),
            "--subgroups", "15819=C2,15820=E3",
            "--no-interactive",
            "--json",
        ])
        assert code == 0
        loaded = load_config()
        assert loaded.sync.subgroups["15819"] == "C2"
        assert loaded.sync.subgroups["15820"] == "E3"

    def test_onboard_phase2_imap_configuration(
        self, mock_config_dir, mock_courses_dir, in_memory_keyring
    ):
        wizard = OnboardingWizard()
        wizard.run_phase1(username="student@correo.ugr.es", courses_root=mock_courses_dir, interactive=False)
        wizard.run_phase2(
            imap_enabled=True,
            imap_host="mail.correo.ugr.es",
            imap_username="student@correo.ugr.es",
            imap_password="imap_secret",
            interactive=False,
        )
        loaded = load_config()
        assert loaded.mfa.imap_enabled is True
        assert loaded.mfa.imap_host == "mail.correo.ugr.es"
        assert loaded.mfa.imap_username == "student@correo.ugr.es"

    def test_onboard_star_marker_lifecycle(self, mock_config_dir):
        assert not has_been_prompted(mock_config_dir)
        res1 = maybe_prompt_star_after_sync(interactive=False, json_mode=True, config_dir=mock_config_dir)
        assert res1["prompted"] is True
        assert has_been_prompted(mock_config_dir)

        res2 = maybe_prompt_star_after_sync(interactive=False, json_mode=True, config_dir=mock_config_dir)
        assert res2["prompted"] is False
        assert res2["reason"] == "already_prompted"
