"""
2-Phase Progressive Disclosure Onboarding Wizard (`prado onboard`) for PradoOS.

Phase 1 (<60 seconds):
  1. Platform & Institutional Credentials (stored in OS Keyring / 0600 Vault)
  2. Destination Folder (`courses_root`) & Folder Routing Preset (`smart` vs `mirror`)
  3. Configuration Persistence & First Sync / Dry-Run Preview

Phase 2 (Optional Power-Ups):
  1. Lab / Seminar Subgroup Filtering (`C2`, `E3`, `A1`, etc.)
  2. Zero-Touch 2FA Email Auto-Fetch via IMAP SSL (`imap.ugr.es`)
  3. Background Sync Daemon Installation (`launchd`, `systemd`, `schtasks`)
"""

from __future__ import annotations

import getpass
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable, Dict, List, Optional

from prado.auth.credentials import CredentialStore
from prado.config import (
    MfaConfig,
    PradoConfig,
    SyncConfig,
    get_config_dir,
    get_config_file,
    get_default_academic_year_code,
    get_default_moodle_url,
    load_config,
    save_config,
)
from prado.onboarding.star import maybe_prompt_star_after_sync
from prado.scheduler.daemon import DaemonManager


def resolve_platform_url(platform_choice: str, year_code: Optional[str] = None) -> str:
    """
    Maps a platform preset ('grado', 'posgrado', 'ceprud') or full URL to a Moodle base URL.
    """
    code = year_code or get_default_academic_year_code()
    clean = (platform_choice or "").strip()
    lower = clean.lower()

    if lower in ("", "1", "grado", "pradogrado", "undergraduate"):
        return f"https://pradogrado{code}.ugr.es"
    if lower in ("2", "posgrado", "pradoposgrado", "postgraduate", "master"):
        return f"https://pradoposgrado{code}.ugr.es"
    if lower in ("3", "ceprud", "prado", "general"):
        return "https://prado.ugr.es"
    if clean.startswith("http://") or clean.startswith("https://"):
        return clean.rstrip("/")
    return f"https://{clean.rstrip('/')}"


def reveal_folder_in_file_manager(folder: Path) -> bool:
    """Opens the synced courses folder in Finder (macOS), Explorer (Windows), or xdg-open (Linux)."""
    try:
        if sys.platform == "darwin":
            subprocess.Popen(
                ["open", str(folder)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        if os.name == "nt":
            subprocess.Popen(
                ["explorer", str(folder)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        subprocess.Popen(
            ["xdg-open", str(folder)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


class OnboardingWizard:
    """
    Orchestrates Phase 1 and Phase 2 onboarding in both interactive TTY mode
    and non-interactive / agent-driven mode.
    """

    def __init__(
        self,
        config_path: Optional[Path] = None,
        credential_store: Optional[CredentialStore] = None,
        input_fn: Callable[[str], str] = input,
        password_fn: Callable[[str], str] = getpass.getpass,
        print_fn: Callable[[str], None] = print,
    ) -> None:
        self.config_path = config_path or get_config_file()
        self.credential_store = credential_store or CredentialStore()
        self.input_fn = input_fn
        self.password_fn = password_fn
        self.print_fn = print_fn

    def run_phase1(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        moodle_url: Optional[str] = None,
        courses_root: Optional[Path | str] = None,
        preset: Optional[str] = None,
        semester: Optional[int] = None,
        interactive: bool = True,
        reveal_folder: bool = False,
    ) -> PradoConfig:
        """
        Executes Phase 1 core onboarding:
        - Collects or applies username, password, Moodle URL, destination directory, and routing preset.
        - Stores SSO credentials in the OS credential store / vault.
        - Creates the destination folder on disk.
        - Saves config.yaml with mode 0600 permissions.
        """
        existing = load_config(self.config_path)

        if interactive and not username:
            self.print_fn("\n🎓 Welcome to PradoOS — Academic Workflow Engine (Phase 1 Setup)")
            self.print_fn("=" * 64)
            default_url = moodle_url or existing.moodle_url or get_default_moodle_url()
            plat_ans = self.input_fn(
                f"1. Platform [1=Grado ({default_url}), 2=Posgrado, 3=CEPRUD, or custom URL] (default 1): "
            ).strip()
            resolved_url = resolve_platform_url(plat_ans) if plat_ans else default_url

            default_user = existing.username or ""
            user_prompt = (
                f"2. Institutional Email / Username [{default_user}]: "
                if default_user
                else "2. Institutional Email / Username (e.g. student@correo.ugr.es): "
            )
            entered_user = self.input_fn(user_prompt).strip() or default_user
            username = entered_user

            if password is None:
                entered_pass = self.password_fn("3. Institutional Password (hidden, stored in OS Keychain): ")
                password = entered_pass

            default_root = str(courses_root or existing.courses_root)
            entered_root = self.input_fn(f"4. Courses Destination Folder [{default_root}]: ").strip()
            resolved_root = Path(entered_root or default_root).expanduser()

            default_preset = preset or existing.sync.preset or "mirror"
            entered_preset = (
                self.input_fn(
                    "5. Folder Organization Preset [mirror = Réplica Exacta de PRADO (Recomendado Terminal), smart = Teoria/Practicas (Modo Agente IA)] "
                    f"[{default_preset}]: "
                )
                .strip()
                .lower()
            )
            resolved_preset = entered_preset if entered_preset in ("smart", "mirror") else default_preset

            if semester is None:
                sem_ans = self.input_fn(
                    "6. Semester Filter [1 = 1st Semester, 2 = 2nd Semester, Enter = All Active]: "
                ).strip()
                if sem_ans in ("1", "2"):
                    semester = int(sem_ans)
                else:
                    semester = existing.sync.semester
        else:
            resolved_url = resolve_platform_url(moodle_url) if moodle_url else (existing.moodle_url or get_default_moodle_url())
            username = username or existing.username
            resolved_root = Path(courses_root).expanduser() if courses_root else existing.courses_root
            resolved_preset = (preset or existing.sync.preset or "smart").lower()
            if resolved_preset not in ("smart", "mirror"):
                resolved_preset = "smart"
            if semester is None:
                semester = existing.sync.semester

        # Persist credentials if both username and password are provided
        if username and password:
            self.credential_store.set_sso_credentials(username, password)

        # Ensure destination directory exists
        resolved_root.mkdir(parents=True, exist_ok=True)

        cfg = PradoConfig(
            version=existing.version,
            moodle_url=resolved_url,
            sso_type=existing.sso_type,
            username=username,
            credential_store=existing.credential_store,
            courses_root=resolved_root,
            mfa=existing.mfa,
            sync=SyncConfig(
                preset=resolved_preset,
                semester=semester,
                dry_run=existing.sync.dry_run,
                subgroups=dict(existing.sync.subgroups),
            ),
        )
        save_config(cfg, self.config_path)

        if reveal_folder:
            reveal_folder_in_file_manager(resolved_root)

        return cfg

    def run_phase2(
        self,
        subgroups: Optional[Dict[str, str]] = None,
        imap_enabled: Optional[bool] = None,
        imap_host: Optional[str] = None,
        imap_username: Optional[str] = None,
        imap_password: Optional[str] = None,
        install_daemon: bool = False,
        daemon_interval: int = 14400,
        interactive: bool = True,
    ) -> PradoConfig:
        """
        Executes Phase 2 Optional Power-Up configuration:
        - Configures lab/seminar subgroup filtering (e.g. ED_C -> C2).
        - Configures automatic 2FA email extraction via IMAP SSL.
        - Optionally installs background sync scheduler daemon.
        """
        cfg = load_config(self.config_path)

        if interactive and subgroups is None and imap_enabled is None:
            self.print_fn("\n⚡ PradoOS Phase 2 — Optional Power-Ups")
            self.print_fn("=" * 64)
            sub_ans = self.input_fn(
                "1. Lab Subgroups (e.g. 'ED_C=C2,SO_E=E3' or Enter to keep all): "
            ).strip()
            if sub_ans:
                parsed_subs: Dict[str, str] = {}
                for pair in sub_ans.split(","):
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        if k.strip() and v.strip():
                            parsed_subs[k.strip()] = v.strip()
                subgroups = parsed_subs

            imap_ans = self.input_fn(
                "2. Enable automatic 2FA email code fetching via IMAP? [y/N]: "
            ).strip().lower()
            if imap_ans in ("y", "yes", "s", "si", "sí"):
                imap_enabled = True
                default_host = cfg.mfa.imap_host or "imap.ugr.es"
                imap_host = self.input_fn(f"   IMAP Host [{default_host}]: ").strip() or default_host
                default_imap_user = cfg.mfa.imap_username or cfg.username or ""
                imap_username = (
                    self.input_fn(f"   IMAP Username [{default_imap_user}]: ").strip()
                    or default_imap_user
                )
                if imap_password is None:
                    imap_password = self.password_fn("   IMAP Password (Enter to reuse SSO password): ")

            daemon_ans = self.input_fn(
                "3. Install automatic background sync every 4 hours? [y/N]: "
            ).strip().lower()
            if daemon_ans in ("y", "yes", "s", "si", "sí"):
                install_daemon = True

        if subgroups is not None:
            cfg.sync.subgroups.update(subgroups)

        if imap_enabled is not None:
            cfg.mfa.imap_enabled = bool(imap_enabled)
        if imap_host:
            cfg.mfa.imap_host = imap_host
        if imap_username:
            cfg.mfa.imap_username = imap_username
        if imap_username and imap_password:
            self.credential_store.set_imap_credentials(imap_username, imap_password)

        save_config(cfg, self.config_path)

        if install_daemon:
            mgr = DaemonManager()
            mgr.install(interval_seconds=daemon_interval)

        return cfg

    def run_full_onboarding(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        moodle_url: Optional[str] = None,
        courses_root: Optional[Path | str] = None,
        preset: Optional[str] = None,
        semester: Optional[int] = None,
        subgroups: Optional[Dict[str, str]] = None,
        imap_enabled: Optional[bool] = None,
        imap_host: Optional[str] = None,
        imap_username: Optional[str] = None,
        imap_password: Optional[str] = None,
        install_daemon: bool = False,
        interactive: bool = True,
        json_mode: bool = False,
        prompt_star: bool = True,
    ) -> Dict[str, Any]:
        """
        Runs Phase 1 and (optionally) Phase 2 onboarding, returning a structured summary dict.
        """
        cfg = self.run_phase1(
            username=username,
            password=password,
            moodle_url=moodle_url,
            courses_root=courses_root,
            preset=preset,
            semester=semester,
            interactive=interactive and not json_mode,
        )

        has_phase2_args = any(
            x is not None for x in (subgroups, imap_enabled, imap_host, imap_username, imap_password)
        ) or install_daemon

        if has_phase2_args:
            cfg = self.run_phase2(
                subgroups=subgroups,
                imap_enabled=imap_enabled,
                imap_host=imap_host,
                imap_username=imap_username,
                imap_password=imap_password,
                install_daemon=install_daemon,
                interactive=False,
            )
        elif interactive and not json_mode:
            want_p2 = (
                self.input_fn("\nWould you like to configure Phase 2 Power-Ups now? [y/N]: ")
                .strip()
                .lower()
            )
            if want_p2 in ("y", "yes", "s", "si", "sí"):
                cfg = self.run_phase2(interactive=True)

        star_info: Optional[Dict[str, Any]] = None
        if prompt_star:
            star_info = maybe_prompt_star_after_sync(
                interactive=interactive,
                json_mode=json_mode,
                config_dir=self.config_path.parent,
                input_fn=self.input_fn,
                print_fn=self.print_fn,
            )

        return {
            "status": "success",
            "config_file": str(self.config_path),
            "username": cfg.username,
            "moodle_url": cfg.moodle_url,
            "courses_root": str(cfg.courses_root),
            "preset": cfg.sync.preset,
            "semester": cfg.sync.semester,
            "subgroups": cfg.sync.subgroups,
            "imap_enabled": cfg.mfa.imap_enabled,
            "star": star_info,
        }
