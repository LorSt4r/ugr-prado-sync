"""
Configuration management and secure OS path resolution for PradoOS.

Strictly enforces isolation between user configuration/credentials/state (mode 0700/0600)
and the synced course directories.
"""

from __future__ import annotations

import datetime
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional
import yaml

from prado.exceptions import ConfigError


def get_default_academic_year_code(dt: Optional[datetime.datetime] = None) -> str:
    """
    Returns the two-digit pair code for the current academic year (e.g. '2627' for 2026/2027).
    Academic years start in September (month 9).
    """
    if dt is None:
        dt = datetime.datetime.now()
    year = dt.year
    if dt.month >= 9:
        start_yy = f"{year % 100:02d}"
        end_yy = f"{(year + 1) % 100:02d}"
    else:
        start_yy = f"{(year - 1) % 100:02d}"
        end_yy = f"{year % 100:02d}"
    return f"{start_yy}{end_yy}"


def get_default_moodle_url() -> str:
    """Returns the default undergraduate Moodle URL for the current academic year."""
    code = get_default_academic_year_code()
    return f"https://pradogrado{code}.ugr.es"


def get_config_dir() -> Path:
    """
    Returns the OS-appropriate configuration directory for PradoOS:
    - POSIX (macOS, Linux): ~/.config/prado (or $XDG_CONFIG_HOME/prado)
    - Windows: %APPDATA%/prado
    Can be overridden via PRADO_CONFIG_DIR environment variable for testing.
    """
    override = os.environ.get("PRADO_CONFIG_DIR")
    if override:
        path = Path(override)
    elif os.name == "nt":
        app_data = os.environ.get("APPDATA")
        if app_data:
            path = Path(app_data) / "prado"
        else:
            path = Path.home() / "AppData" / "Roaming" / "prado"
    else:
        xdg_config = os.environ.get("XDG_CONFIG_HOME")
        if xdg_config:
            path = Path(xdg_config) / "prado"
        else:
            path = Path.home() / ".config" / "prado"

    ensure_secure_dir(path)
    return path


def get_config_file() -> Path:
    """Returns the absolute path to config.yaml."""
    return get_config_dir() / "config.yaml"


def get_session_file() -> Path:
    """Returns the absolute path to session.json."""
    return get_config_dir() / "session.json"


def get_state_db_path() -> Path:
    """Returns the absolute path to state.db (SQLite database)."""
    return get_config_dir() / "state.db"


def get_credentials_vault_file() -> Path:
    """Returns the absolute path to the encrypted credentials vault fallback."""
    return get_config_dir() / "credentials.vault"


def ensure_secure_dir(directory: Path) -> Path:
    """
    Ensures directory exists with restricted permissions:
    mode 0700 (rwx------) on POSIX.
    """
    directory.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        try:
            os.chmod(directory, 0o700)
        except OSError:
            pass
    return directory


def write_secure_file(path: Path, content: str | bytes, mode: int = 0o600) -> None:
    """
    Atomically writes content to path and enforces restricted file permissions (mode 0600 on POSIX).
    Uses a temporary file in the same directory before atomic replacement.
    """
    parent = path.parent
    ensure_secure_dir(parent)

    import uuid
    token = uuid.uuid4().hex[:8]
    tmp_path = parent / f".tmp_{os.getpid()}_{token}_{path.name}"
    try:
        if isinstance(content, str):
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(content)
        else:
            with open(tmp_path, "wb") as f:
                f.write(content)

        if os.name != "nt":
            try:
                os.chmod(tmp_path, mode)
            except OSError:
                pass

        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


@dataclass
class MfaConfig:
    enable_device_trust: bool = True
    imap_enabled: bool = False
    imap_host: str = "imap.ugr.es"
    imap_port: int = 993
    imap_ssl: bool = True
    imap_username: Optional[str] = None
    imap_folder: str = "INBOX"
    imap_timeout: int = 60
    imap_poll_interval: int = 3
    apple_mail_enabled: bool = True
    apple_mail_account: str = "auto"


@dataclass
class SyncConfig:
    preset: str = "smart"  # 'smart' or 'mirror'
    semester: Optional[int] = None
    dry_run: bool = False
    subgroups: Dict[str, str] = field(default_factory=dict)


@dataclass
class PradoConfig:
    version: str = "1.0"
    moodle_url: str = field(default_factory=get_default_moodle_url)
    sso_type: str = "ugr_saml"
    username: Optional[str] = None
    credential_store: str = "auto"  # 'auto', 'keyring', 'vault_file', 'env'
    courses_root: Path = field(default_factory=lambda: Path.home() / "Documents" / "UGR_Courses")
    mfa: MfaConfig = field(default_factory=MfaConfig)
    sync: SyncConfig = field(default_factory=SyncConfig)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["courses_root"] = str(self.courses_root)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PradoConfig:
        if not isinstance(data, dict):
            raise ConfigError("Config data must be a dictionary")

        mfa_data = data.get("mfa", {})
        if isinstance(mfa_data, dict):
            mfa_cfg = MfaConfig(**mfa_data)
        else:
            mfa_cfg = MfaConfig()

        sync_data = data.get("sync", {})
        if isinstance(sync_data, dict):
            sync_cfg = SyncConfig(**sync_data)
        else:
            sync_cfg = SyncConfig()

        courses_root_val = data.get("courses_root")
        if courses_root_val:
            courses_root = Path(courses_root_val).expanduser()
        else:
            courses_root = Path.home() / "Documents" / "UGR_Courses"

        return cls(
            version=str(data.get("version", "1.0")),
            moodle_url=str(data.get("moodle_url") or get_default_moodle_url()),
            sso_type=str(data.get("sso_type", "ugr_saml")),
            username=data.get("username"),
            credential_store=str(data.get("credential_store", "auto")),
            courses_root=courses_root,
            mfa=mfa_cfg,
            sync=sync_cfg,
        )


def load_config(path: Optional[Path] = None) -> PradoConfig:
    """
    Loads PradoConfig from the specified file or the default config path (~/.config/prado/config.yaml).
    If the file does not exist, returns the default configuration.
    """
    config_file = path or get_config_file()
    if not config_file.exists():
        return PradoConfig()

    try:
        with open(config_file, "r", encoding="utf-8") as f:
            content = yaml.safe_load(f)
        if not content:
            return PradoConfig()
        return PradoConfig.from_dict(content)
    except yaml.YAMLError as e:
        raise ConfigError(f"Malformed YAML in {config_file}: {e}") from e
    except Exception as e:
        raise ConfigError(f"Failed to load configuration from {config_file}: {e}") from e


def save_config(config: PradoConfig, path: Optional[Path] = None) -> None:
    """
    Serializes and securely writes PradoConfig to YAML with mode 0600.
    """
    config_file = path or get_config_file()
    content = yaml.dump(config.to_dict(), default_flow_style=False, sort_keys=False)
    write_secure_file(config_file, content, mode=0o600)
