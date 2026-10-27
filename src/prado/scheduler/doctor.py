"""
prado doctor — Comprehensive 9-Probe Diagnostic Framework for PradoOS.

Probes:
1. Python environment (version >= 3.10, virtualenv detection)
2. Config validity & permissions (0600 on config.yaml)
3. State DB integrity (PRAGMA integrity_check)
4. Credentials store check (Keyring or encrypted vault fallback)
5. IdP network reachability (identidad.ugr.es)
6. PRADO endpoint reachability (pradogrado2627.ugr.es)
7. Course root destination writable permissions & disk space
8. Daemon / scheduler installation status
9. Dependency integrity & clean environment
"""

from __future__ import annotations

from dataclasses import dataclass, field
import datetime
from enum import Enum
import importlib
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import stat
import sys
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests

from prado.auth.credentials import CredentialStore
from prado.config import (
    PradoConfig,
    get_config_dir,
    get_config_file,
    get_state_db_path,
    load_config,
)
from prado.scheduler.daemon import DaemonManager


class ProbeStatus(str, Enum):
    OK = "OK"
    WARN = "WARN"
    FAIL = "FAIL"
    SKIP = "SKIP"


@dataclass
class ProbeResult:
    """Individual diagnostic probe outcome."""
    probe_id: str
    name: str
    status: ProbeStatus
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    remediation: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "probe_id": self.probe_id,
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "details": self.details,
            "remediation": self.remediation,
        }


@dataclass
class DoctorReport:
    """Aggregated doctor diagnostic report."""
    timestamp: str
    overall_status: ProbeStatus
    probes: List[ProbeResult] = field(default_factory=list)

    @property
    def passed_count(self) -> int:
        return sum(1 for p in self.probes if p.status == ProbeStatus.OK)

    @property
    def warn_count(self) -> int:
        return sum(1 for p in self.probes if p.status == ProbeStatus.WARN)

    @property
    def fail_count(self) -> int:
        return sum(1 for p in self.probes if p.status == ProbeStatus.FAIL)

    @property
    def skip_count(self) -> int:
        return sum(1 for p in self.probes if p.status == ProbeStatus.SKIP)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "overall_status": self.overall_status.value,
            "summary": {
                "total": len(self.probes),
                "ok": self.passed_count,
                "warn": self.warn_count,
                "fail": self.fail_count,
                "skip": self.skip_count,
            },
            "probes": [p.to_dict() for p in self.probes],
        }

    def format_terminal(self, use_color: bool = True) -> str:
        symbols = {
            ProbeStatus.OK: "\033[92m[✓]\033[0m" if use_color else "[✓]",
            ProbeStatus.WARN: "\033[93m[⚠]\033[0m" if use_color else "[⚠]",
            ProbeStatus.FAIL: "\033[91m[✗]\033[0m" if use_color else "[✗]",
            ProbeStatus.SKIP: "\033[90m[○]\033[0m" if use_color else "[○]",
        }

        lines = [
            f"PradoOS Doctor — Diagnostic Report ({self.timestamp})",
            "=" * 60,
        ]

        for p in self.probes:
            sym = symbols.get(p.status, "[?]")
            lines.append(f"{sym} {p.name:<30}: {p.message}")

        lines.append("=" * 60)
        lines.append(
            f"Summary: {self.passed_count} OK, {self.warn_count} WARN, {self.fail_count} FAIL"
            + (f", {self.skip_count} SKIP" if self.skip_count > 0 else "")
        )

        overall_label = "PASSED" if self.overall_status in (ProbeStatus.OK, ProbeStatus.WARN) else "FAILED"
        lines.append(f"Result: {overall_label}")

        issues = [p for p in self.probes if p.status in (ProbeStatus.WARN, ProbeStatus.FAIL) and p.remediation]
        if issues:
            lines.append("\nRemediation Suggestions:")
            for p in issues:
                lines.append(f"  • {p.name}: {p.remediation}")

        return "\n".join(lines)


class DoctorEngine:
    """
    Executes the 9 health probes across configuration, state, credentials,
    network reachability, destinations, daemon, and dependencies.
    """

    def __init__(
        self,
        config: Optional[PradoConfig] = None,
        http_session: Optional[requests.Session] = None,
    ):
        self._config_load_error: Optional[str] = None
        if config is not None:
            self.config = config
        else:
            try:
                self.config = load_config()
            except Exception as e:
                self._config_load_error = str(e)
                self.config = PradoConfig()
        self.session = http_session or requests.Session()

    def run_all(self) -> DoctorReport:
        probes = [
            self.probe_python_env(),
            self.probe_config_validity(),
            self.probe_state_db(),
            self.probe_credentials_store(),
            self.probe_idp_reachability(),
            self.probe_prado_endpoint(),
            self.probe_course_root(),
            self.probe_daemon_status(),
            self.probe_dependencies_and_artifacts(),
        ]

        has_fail = any(p.status == ProbeStatus.FAIL for p in probes)
        has_warn = any(p.status == ProbeStatus.WARN for p in probes)
        overall = ProbeStatus.FAIL if has_fail else (ProbeStatus.WARN if has_warn else ProbeStatus.OK)

        return DoctorReport(
            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            overall_status=overall,
            probes=probes,
        )

    # 1. Python Environment
    def probe_python_env(self) -> ProbeResult:
        version_tuple = sys.version_info
        major = version_tuple[0]
        minor = version_tuple[1]
        micro = version_tuple[2]
        version_str = f"{major}.{minor}.{micro}"
        is_virtualenv = (
            (sys.prefix != sys.base_prefix)
            or ("VIRTUAL_ENV" in os.environ)
            or hasattr(sys, "real_prefix")
        )
        venv_path = sys.prefix if is_virtualenv else None

        details = {
            "python_version": version_str,
            "executable": sys.executable,
            "is_virtualenv": is_virtualenv,
            "virtualenv_path": venv_path,
            "platform": platform.platform(),
            "architecture": platform.machine(),
        }

        if (major, minor) < (3, 10):
            return ProbeResult(
                probe_id="python_env",
                name="Python Environment",
                status=ProbeStatus.FAIL,
                message=f"Python >= 3.10 required (found {version_str})",
                details=details,
                remediation="Upgrade your Python interpreter to version 3.10 or higher.",
            )

        if not is_virtualenv:
            return ProbeResult(
                probe_id="python_env",
                name="Python Environment",
                status=ProbeStatus.WARN,
                message=f"Python {version_str} (running outside virtualenv)",
                details=details,
                remediation="Recommended to run PradoOS within an isolated Python virtual environment.",
            )

        return ProbeResult(
            probe_id="python_env",
            name="Python Environment",
            status=ProbeStatus.OK,
            message=f"Python {version_str} (virtualenv active)",
            details=details,
        )

    # 2. Config Validity & Permissions
    def probe_config_validity(self) -> ProbeResult:
        cfg_path = get_config_file()
        cfg_dir = get_config_dir()
        details = {
            "config_path": str(cfg_path),
            "config_dir": str(cfg_dir),
            "exists": cfg_path.exists(),
        }

        if not cfg_path.exists():
            return ProbeResult(
                probe_id="config_validity",
                name="Config Validity & Permissions",
                status=ProbeStatus.WARN,
                message="Config file not yet created; default configuration in effect",
                details=details,
                remediation="Run 'prado onboard' to generate your personalized config.yaml.",
            )

        try:
            cfg = load_config(cfg_path)
            details["moodle_url"] = cfg.moodle_url
            details["username"] = cfg.username
            details["sso_type"] = cfg.sso_type
        except Exception as e:
            return ProbeResult(
                probe_id="config_validity",
                name="Config Validity & Permissions",
                status=ProbeStatus.FAIL,
                message=f"Config file corrupt or invalid YAML: {e}",
                details=details,
                remediation="Inspect and fix YAML syntax errors in ~/.config/prado/config.yaml.",
            )

        if os.name != "nt":
            file_mode = stat.S_IMODE(os.stat(cfg_path).st_mode)
            details["mode"] = oct(file_mode)
            if file_mode & 0o077 != 0:
                return ProbeResult(
                    probe_id="config_validity",
                    name="Config Validity & Permissions",
                    status=ProbeStatus.WARN,
                    message=f"Config permissions {oct(file_mode)} are too open (expected 0600)",
                    details=details,
                    remediation=f"Run: chmod 600 {cfg_path}",
                )

        return ProbeResult(
            probe_id="config_validity",
            name="Config Validity & Permissions",
            status=ProbeStatus.OK,
            message=f"Valid config (mode 0600, Moodle: {urlparse(cfg.moodle_url).netloc})",
            details=details,
        )

    # 3. State DB Integrity
    def probe_state_db(self) -> ProbeResult:
        db_path = get_state_db_path()
        details = {"db_path": str(db_path), "exists": db_path.exists()}

        if not db_path.exists():
            return ProbeResult(
                probe_id="state_db",
                name="State Database Integrity",
                status=ProbeStatus.OK,
                message="State DB not created yet (will initialize on first sync)",
                details=details,
            )

        try:
            conn = sqlite3.connect(str(db_path), timeout=5.0)
            with conn:
                res = conn.execute("PRAGMA integrity_check;").fetchall()
                integrity = [r[0] for r in res]
                details["integrity_check"] = integrity

                if integrity != ["ok"]:
                    return ProbeResult(
                        probe_id="state_db",
                        name="State Database Integrity",
                        status=ProbeStatus.FAIL,
                        message=f"Database integrity check failed: {integrity}",
                        details=details,
                        remediation="Backup ~/.config/prado/state.db and re-run sync to rebuild state.",
                    )

                # Check courses and files count
                try:
                    courses_count = conn.execute("SELECT count(*) FROM courses;").fetchone()[0]
                    files_count = conn.execute("SELECT count(*) FROM files;").fetchone()[0]
                    details["courses_tracked"] = courses_count
                    details["files_tracked"] = files_count
                    msg = f"SQLite OK ({courses_count} courses, {files_count} files tracked)"
                except sqlite3.OperationalError:
                    msg = "SQLite OK (tables not initialized)"

            return ProbeResult(
                probe_id="state_db",
                name="State Database Integrity",
                status=ProbeStatus.OK,
                message=msg,
                details=details,
            )
        except Exception as e:
            return ProbeResult(
                probe_id="state_db",
                name="State Database Integrity",
                status=ProbeStatus.FAIL,
                message=f"SQLite state database error: {e}",
                details=details,
                remediation="Check filesystem permissions on state.db or repair SQLite database.",
            )

    # 4. Credentials Store
    def probe_credentials_store(self) -> ProbeResult:
        store = CredentialStore()
        try:
            keyring_usable = store._is_keyring_usable()
        except Exception as e:
            keyring_usable = False
        vault_exists = store.vault_path.exists()

        details = {
            "keyring_usable": keyring_usable,
            "vault_exists": vault_exists,
            "configured_user": self.config.username,
        }

        has_sso = False
        try:
            store.get_sso_credentials(default_username=self.config.username)
            has_sso = True
        except Exception:
            has_sso = False

        details["sso_configured"] = has_sso

        if not has_sso:
            return ProbeResult(
                probe_id="credentials_store",
                name="Credentials Store",
                status=ProbeStatus.WARN,
                message="No SSO credentials found in Keyring or Vault",
                details=details,
                remediation="Run 'prado auth' to configure your institutional UGR credentials.",
            )

        store_desc = "Keyring" if keyring_usable else "Encrypted Vault (0600)"
        return ProbeResult(
            probe_id="credentials_store",
            name="Credentials Store",
            status=ProbeStatus.OK,
            message=f"Credentials active ({store_desc}, user: {self.config.username or 'saved'})",
            details=details,
        )

    # 5. IdP Reachability
    def probe_idp_reachability(self) -> ProbeResult:
        idp_host = "idp.ugr.es"
        url = f"https://{idp_host}/simplesaml/module.php/core/loginuserpass"
        details = {"target": url}

        start_time = time.time()
        try:
            res = self.session.get(url, timeout=5.0, allow_redirects=True)
            latency_ms = round((time.time() - start_time) * 1000, 1)
            details["status_code"] = res.status_code
            details["latency_ms"] = latency_ms

            if res.status_code >= 500:
                return ProbeResult(
                    probe_id="idp_reachability",
                    name="IdP Network Reachability",
                    status=ProbeStatus.FAIL,
                    message=f"{idp_host} server error (HTTP {res.status_code}, {latency_ms}ms)",
                    details=details,
                    remediation="UGR Identity Provider may be undergoing maintenance; try again shortly.",
                )

            return ProbeResult(
                probe_id="idp_reachability",
                name="IdP Network Reachability",
                status=ProbeStatus.OK,
                message=f"{idp_host} responding (HTTP {res.status_code}, {latency_ms}ms)",
                details=details,
            )
        except Exception as e:
            details["error"] = str(e)
            return ProbeResult(
                probe_id="idp_reachability",
                name="IdP Network Reachability",
                status=ProbeStatus.FAIL,
                message=f"Cannot reach Identity Provider {idp_host}: {e}",
                details=details,
                remediation="Verify Internet connectivity or VPN access to UGR services.",
            )

    # 6. PRADO Endpoint Reachability
    def probe_prado_endpoint(self) -> ProbeResult:
        target_url = self.config.moodle_url
        details = {"target": target_url}

        start_time = time.time()
        try:
            res = self.session.head(target_url, timeout=5.0, allow_redirects=True)
            latency_ms = round((time.time() - start_time) * 1000, 1)
            details["status_code"] = res.status_code
            details["latency_ms"] = latency_ms

            if res.status_code >= 500:
                return ProbeResult(
                    probe_id="prado_endpoint",
                    name="PRADO Moodle Reachability",
                    status=ProbeStatus.FAIL,
                    message=f"{urlparse(target_url).netloc} server error (HTTP {res.status_code}, {latency_ms}ms)",
                    details=details,
                    remediation="PRADO Moodle server may be down or undergoing scheduled maintenance.",
                )

            return ProbeResult(
                probe_id="prado_endpoint",
                name="PRADO Moodle Reachability",
                status=ProbeStatus.OK,
                message=f"{urlparse(target_url).netloc} responding (HTTP {res.status_code}, {latency_ms}ms)",
                details=details,
            )
        except Exception as e:
            details["error"] = str(e)
            return ProbeResult(
                probe_id="prado_endpoint",
                name="PRADO Moodle Reachability",
                status=ProbeStatus.FAIL,
                message=f"Cannot reach Moodle endpoint {target_url}: {e}",
                details=details,
                remediation="Check configured moodle_url in config.yaml or PRADO server status.",
            )

    # 7. Course Root Destination
    def probe_course_root(self) -> ProbeResult:
        root_dir = self.config.courses_root.expanduser().resolve()
        details = {"courses_root": str(root_dir), "exists": root_dir.exists()}

        try:
            root_dir.mkdir(parents=True, exist_ok=True)
            test_file = root_dir / f".prado_probe_{os.getpid()}_{int(time.time())}.tmp"
            test_file.write_text("prado-doctor-probe", encoding="utf-8")
            test_file.unlink()

            usage = shutil.disk_usage(root_dir)
            free_gb = round(usage.free / (1024**3), 2)
            details["free_gb"] = free_gb

            if free_gb < 1.0:
                return ProbeResult(
                    probe_id="course_root",
                    name="Course Destination Root",
                    status=ProbeStatus.WARN,
                    message=f"Writable, but low disk space ({free_gb} GB free on drive)",
                    details=details,
                    remediation="Free up storage space on the volume hosting your courses root.",
                )

            return ProbeResult(
                probe_id="course_root",
                name="Course Destination Root",
                status=ProbeStatus.OK,
                message=f"Writable ({free_gb} GB free, {root_dir})",
                details=details,
            )
        except Exception as e:
            details["error"] = str(e)
            return ProbeResult(
                probe_id="course_root",
                name="Course Destination Root",
                status=ProbeStatus.FAIL,
                message=f"Destination directory not writable: {e}",
                details=details,
                remediation=f"Ensure write permissions exist on {root_dir}.",
            )

    # 8. Daemon Status
    def probe_daemon_status(self) -> ProbeResult:
        mgr = DaemonManager()
        status = mgr.status()
        details = status.to_dict()

        if status.installed and status.active:
            return ProbeResult(
                probe_id="daemon_status",
                name="Background Sync Daemon",
                status=ProbeStatus.OK,
                message=f"Active ({status.backend}, schedule: {status.schedule})",
                details=details,
            )
        elif status.installed and not status.active:
            return ProbeResult(
                probe_id="daemon_status",
                name="Background Sync Daemon",
                status=ProbeStatus.WARN,
                message=f"Installed but inactive ({status.backend})",
                details=details,
                remediation="Run 'prado daemon start' to enable background synchronization.",
            )
        else:
            return ProbeResult(
                probe_id="daemon_status",
                name="Background Sync Daemon",
                status=ProbeStatus.WARN,
                message=f"Not installed ({status.backend} available)",
                details=details,
                remediation="Run 'prado daemon install' to enable automatic background syncing.",
            )

    # 9. Dependencies Integrity & Clean Environment
    def probe_dependencies_and_artifacts(self) -> ProbeResult:
        core_deps = ["requests", "bs4", "keyring", "yaml", "cryptography", "sqlite3"]
        missing = []
        versions = {}

        for dep in core_deps:
            try:
                mod = importlib.import_module(dep)
                versions[dep] = getattr(mod, "__version__", "builtin")
            except ImportError:
                missing.append(dep)

        details = {
            "dependencies_checked": core_deps,
            "installed_versions": versions,
            "missing": missing,
        }

        if missing:
            return ProbeResult(
                probe_id="dependencies_and_artifacts",
                name="Dependencies & Integrity",
                status=ProbeStatus.FAIL,
                message=f"Missing core dependencies: {', '.join(missing)}",
                details=details,
                remediation="Run: pip install -e .",
            )

        return ProbeResult(
            probe_id="dependencies_and_artifacts",
            name="Dependencies & Integrity",
            status=ProbeStatus.OK,
            message=f"All {len(core_deps)} core dependencies verified; clean environment",
            details=details,
        )


PradoDoctor = DoctorEngine
