"""
Unit tests for PradoOS configuration management and secure path resolution.
"""

import datetime
import os
import stat
from pathlib import Path
import pytest
import yaml

from prado.config import (
    ConfigError,
    MfaConfig,
    PradoConfig,
    SyncConfig,
    ensure_secure_dir,
    get_config_dir,
    get_config_file,
    get_credentials_vault_file,
    get_default_academic_year_code,
    get_default_moodle_url,
    get_session_file,
    get_state_db_path,
    load_config,
    save_config,
    write_secure_file,
)


def test_academic_year_calculation():
    # Test Fall / Autumn (>= September)
    dt_oct_2026 = datetime.datetime(2026, 10, 27, 12, 0, 0)
    assert get_default_academic_year_code(dt_oct_2026) == "2627"

    dt_sep_2026 = datetime.datetime(2026, 9, 1, 0, 0, 0)
    assert get_default_academic_year_code(dt_sep_2026) == "2627"

    # Test Spring / Summer (< September)
    dt_jan_2027 = datetime.datetime(2027, 1, 15, 10, 0, 0)
    assert get_default_academic_year_code(dt_jan_2027) == "2627"

    dt_may_2026 = datetime.datetime(2026, 5, 20, 15, 0, 0)
    assert get_default_academic_year_code(dt_may_2026) == "2526"


def test_default_moodle_url():
    url = get_default_moodle_url()
    assert url.startswith("https://pradogrado")
    assert url.endswith(".ugr.es")


def test_config_dir_override(tmp_path, monkeypatch):
    test_dir = tmp_path / "custom_prado_config"
    monkeypatch.setenv("PRADO_CONFIG_DIR", str(test_dir))

    cfg_dir = get_config_dir()
    assert cfg_dir == test_dir
    assert cfg_dir.exists()
    assert cfg_dir.is_dir()

    if os.name != "nt":
        mode = stat.S_IMODE(os.stat(cfg_dir).st_mode)
        assert mode == 0o700


def test_derived_config_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("PRADO_CONFIG_DIR", str(tmp_path))

    assert get_config_file() == tmp_path / "config.yaml"
    assert get_session_file() == tmp_path / "session.json"
    assert get_state_db_path() == tmp_path / "state.db"
    assert get_credentials_vault_file() == tmp_path / "credentials.vault"


def test_write_secure_file(tmp_path):
    target = tmp_path / "secure.txt"
    content = "super_secret_payload_123"

    write_secure_file(target, content, mode=0o600)

    assert target.exists()
    assert target.read_text(encoding="utf-8") == content

    if os.name != "nt":
        file_mode = stat.S_IMODE(os.stat(target).st_mode)
        assert file_mode == 0o600


def test_write_secure_file_binary(tmp_path):
    target = tmp_path / "secure.bin"
    payload = b"\x00\x01\x02\x03\xfe\xff"

    write_secure_file(target, payload, mode=0o600)

    assert target.exists()
    assert target.read_bytes() == payload

    if os.name != "nt":
        file_mode = stat.S_IMODE(os.stat(target).st_mode)
        assert file_mode == 0o600


def test_prado_config_defaults():
    cfg = PradoConfig()
    assert cfg.version == "1.0"
    assert cfg.sso_type == "ugr_saml"
    assert cfg.credential_store == "auto"
    assert cfg.mfa.enable_device_trust is True
    assert cfg.mfa.imap_enabled is False
    assert cfg.mfa.imap_host == "imap.ugr.es"
    assert cfg.sync.preset == "smart"
    assert cfg.courses_root == Path.home() / "Documents" / "UGR_Courses"


def test_prado_config_roundtrip_dict(tmp_path):
    custom_root = tmp_path / "MyCourses"
    cfg = PradoConfig(
        version="1.1",
        moodle_url="https://pradoposgrado2627.ugr.es",
        username="student@correo.ugr.es",
        courses_root=custom_root,
        mfa=MfaConfig(imap_enabled=True, imap_username="student@correo.ugr.es"),
        sync=SyncConfig(preset="mirror", semester=1),
    )

    data = cfg.to_dict()
    assert data["version"] == "1.1"
    assert data["moodle_url"] == "https://pradoposgrado2627.ugr.es"
    assert data["username"] == "student@correo.ugr.es"
    assert data["courses_root"] == str(custom_root)
    assert data["mfa"]["imap_enabled"] is True
    assert data["sync"]["preset"] == "mirror"

    restored = PradoConfig.from_dict(data)
    assert restored.version == "1.1"
    assert restored.moodle_url == "https://pradoposgrado2627.ugr.es"
    assert restored.username == "student@correo.ugr.es"
    assert restored.courses_root == custom_root
    assert restored.mfa.imap_enabled is True
    assert restored.sync.preset == "mirror"


def test_save_and_load_config(tmp_path, monkeypatch):
    monkeypatch.setenv("PRADO_CONFIG_DIR", str(tmp_path))
    config_path = tmp_path / "config.yaml"

    cfg = PradoConfig(
        username="test_student",
        moodle_url="https://custom.moodle.edu",
    )
    save_config(cfg, config_path)

    assert config_path.exists()
    if os.name != "nt":
        assert stat.S_IMODE(os.stat(config_path).st_mode) == 0o600

    loaded = load_config(config_path)
    assert loaded.username == "test_student"
    assert loaded.moodle_url == "https://custom.moodle.edu"


def test_load_nonexistent_config_returns_defaults(tmp_path):
    nonexistent = tmp_path / "does_not_exist.yaml"
    cfg = load_config(nonexistent)
    assert isinstance(cfg, PradoConfig)
    assert cfg.version == "1.0"


def test_load_corrupted_yaml_raises_config_error(tmp_path):
    corrupted = tmp_path / "corrupted.yaml"
    corrupted.write_text("invalid: [yaml: unclosed", encoding="utf-8")

    with pytest.raises(ConfigError):
        load_config(corrupted)


def test_strict_isolation_between_config_and_courses_root(tmp_path, monkeypatch):
    """
    Guarantees that credentials, session cookies, and state DB are completely
    isolated from the student's courses download folder.
    """
    config_dir = tmp_path / "prado_config"
    courses_dir = tmp_path / "student_courses"

    monkeypatch.setenv("PRADO_CONFIG_DIR", str(config_dir))

    cfg = PradoConfig(courses_root=courses_dir)

    session_path = get_session_file()
    vault_path = get_credentials_vault_file()
    state_path = get_state_db_path()

    # None of the security paths should be inside courses_root
    assert not str(session_path).startswith(str(courses_dir))
    assert not str(vault_path).startswith(str(courses_dir))
    assert not str(state_path).startswith(str(courses_dir))
    assert not str(get_config_dir()).startswith(str(courses_dir))
