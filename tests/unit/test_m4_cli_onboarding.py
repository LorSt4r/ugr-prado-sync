"""
Unit and Adversarial Tests for Milestone M4 (Onboarding, Star Loop, and Unified CLI).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from prado.cli import main
from prado.config import PradoConfig, load_config, save_config
from prado.onboarding.star import (
    DEFAULT_GITHUB_REPO,
    execute_star,
    has_been_prompted,
    mark_prompted,
    maybe_prompt_star_after_sync,
    star_via_gh_cli,
)
from prado.onboarding.wizard import OnboardingWizard, resolve_platform_url


class TestOnboardingAndStarUnit:
    def test_resolve_platform_url_presets(self):
        assert resolve_platform_url("grado", year_code="2627") == "https://pradogrado2627.ugr.es"
        assert resolve_platform_url("2", year_code="2627") == "https://pradoposgrado2627.ugr.es"
        assert resolve_platform_url("ceprud", year_code="2627") == "https://prado.ugr.es"
        assert resolve_platform_url("https://moodle.example.edu/") == "https://moodle.example.edu"
        assert resolve_platform_url("custom.moodle.org") == "https://custom.moodle.org"

    def test_star_via_gh_cli_success_and_failure(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda cmd: "/usr/local/bin/gh")
        mock_run = MagicMock()
        mock_run.returncode = 0
        monkeypatch.setattr("subprocess.run", lambda *a, **kw: mock_run)
        assert star_via_gh_cli(DEFAULT_GITHUB_REPO) is True

        mock_run.returncode = 1
        assert star_via_gh_cli(DEFAULT_GITHUB_REPO) is False

    def test_execute_star_browser_fallback(self, mock_config_dir, monkeypatch):
        monkeypatch.setattr("prado.onboarding.star.star_via_gh_cli", lambda repo: False)
        monkeypatch.setattr("prado.onboarding.star.open_repo_in_browser", lambda repo: True)

        res = execute_star(use_browser_fallback=True, config_dir=mock_config_dir)
        assert res["status"] == "opened_browser"
        assert res["method"] == "browser"
        assert has_been_prompted(mock_config_dir)

    def test_interactive_wizard_phase1_and_phase2(self, mock_config_dir, mock_courses_dir, in_memory_keyring):
        inputs = iter([
            "1",                          # Platform: Grado
            "erasmus@correo.ugr.es",      # Username
            str(mock_courses_dir),        # Courses root
            "mirror",                     # Preset
            "1",                          # Semester 1
            "y",                          # Configure Phase 2 now?
            "ED_C=C2,SO_E=E3",            # Subgroups
            "y",                          # Enable IMAP?
            "imap.ugr.es",                # IMAP host
            "erasmus@correo.ugr.es",      # IMAP username
            "n",                          # Install daemon?
        ])
        outputs = []
        wizard = OnboardingWizard(
            input_fn=lambda prompt: next(inputs),
            password_fn=lambda prompt: "my_secret_pwd",
            print_fn=lambda msg: outputs.append(msg),
        )
        res = wizard.run_full_onboarding(interactive=True, json_mode=False, prompt_star=False)
        assert res["status"] == "success"
        assert res["username"] == "erasmus@correo.ugr.es"
        assert res["preset"] == "mirror"
        assert res["semester"] == 1
        assert res["subgroups"] == {"ED_C": "C2", "SO_E": "E3"}
        assert res["imap_enabled"] is True

    def test_cli_courses_commands(self, mock_config_dir, mock_courses_dir, capsys):
        save_config(PradoConfig(username="user@ugr.es", courses_root=mock_courses_dir))

        assert main(["courses", "enable", "15819", "--json"]) == 0
        out_en = json.loads(capsys.readouterr().out)
        assert out_en["is_active"] is True

        assert main(["courses", "disable", "15819", "--json"]) == 0
        out_dis = json.loads(capsys.readouterr().out)
        assert out_dis["is_active"] is False

        assert main(["courses", "set-preset", "mirror", "--json"]) == 0
        out_pre = json.loads(capsys.readouterr().out)
        assert out_pre["preset"] == "mirror"
        assert load_config().sync.preset == "mirror"

        assert main(["courses", "list", "--json"]) == 0
        out_list = json.loads(capsys.readouterr().out)
        assert out_list["courses_count"] == 1
        assert out_list["courses"][0]["course_id"] == 15819

    def test_cli_auth_logout_and_doctor_fix(self, mock_config_dir, mock_courses_dir, capsys):
        save_config(PradoConfig(username="user@ugr.es", courses_root=mock_courses_dir))
        sess_file = mock_config_dir / "session.json"
        sess_file.write_text("[]", encoding="utf-8")

        assert main(["auth", "logout", "--json"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["action"] == "logout"
        assert not sess_file.exists()

        code_doc = main(["doctor", "--fix", "--json"])
        out_doc = json.loads(capsys.readouterr().out)
        assert code_doc in (0, 1)
        assert len(out_doc["probes"]) == 9
