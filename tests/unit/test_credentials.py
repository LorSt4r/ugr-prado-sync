"""
Unit tests for PradoOS multi-tier CredentialStore (Environment, Keyring, and Encrypted Vault).
"""

import os
import stat
from pathlib import Path
import pytest

from prado.auth.credentials import CredentialStore
from prado.exceptions import InvalidCredentialsError


def test_env_credentials_highest_priority(tmp_path, monkeypatch):
    monkeypatch.setenv("PRADO_USERNAME", "env_user@correo.ugr.es")
    monkeypatch.setenv("PRADO_PASSWORD", "env_secret_123")

    vault_file = tmp_path / "credentials.vault"
    store = CredentialStore(use_env=True, preferred_backend="auto", vault_path=vault_file)

    user, pwd = store.get_sso_credentials()
    assert user == "env_user@correo.ugr.es"
    assert pwd == "env_secret_123"


def test_env_imap_credentials_priority(tmp_path, monkeypatch):
    monkeypatch.setenv("PRADO_IMAP_USERNAME", "imap_user@correo.ugr.es")
    monkeypatch.setenv("PRADO_IMAP_PASSWORD", "imap_secret_456")

    vault_file = tmp_path / "credentials.vault"
    store = CredentialStore(use_env=True, preferred_backend="auto", vault_path=vault_file)

    user, pwd = store.get_imap_credentials()
    assert user == "imap_user@correo.ugr.es"
    assert pwd == "imap_secret_456"


def test_encrypted_vault_fallback(tmp_path, monkeypatch):
    # Ensure env is clear
    monkeypatch.delenv("PRADO_USERNAME", raising=False)
    monkeypatch.delenv("PRADO_PASSWORD", raising=False)

    vault_file = tmp_path / "credentials.vault"
    # Force vault mode
    store = CredentialStore(use_env=False, preferred_backend="vault", vault_path=vault_file)

    # Store credentials
    store.set_sso_credentials("vault_student", "super_secret_vault_pass")

    assert vault_file.exists()
    # Check permissions on POSIX
    if os.name != "nt":
        assert stat.S_IMODE(os.stat(vault_file).st_mode) == 0o600

    # Verify content is encrypted (does NOT contain plaintext password)
    raw_content = vault_file.read_bytes()
    assert b"super_secret_vault_pass" not in raw_content
    assert b"vault_student" not in raw_content

    # Retrieve credentials
    user, pwd = store.get_sso_credentials("vault_student")
    assert user == "vault_student"
    assert pwd == "super_secret_vault_pass"

    # Also test single user lookup without specifying username
    user2, pwd2 = store.get_sso_credentials()
    assert user2 == "vault_student"
    assert pwd2 == "super_secret_vault_pass"


def test_encrypted_vault_delete(tmp_path, monkeypatch):
    monkeypatch.delenv("PRADO_USERNAME", raising=False)
    monkeypatch.delenv("PRADO_PASSWORD", raising=False)

    vault_file = tmp_path / "credentials.vault"
    store = CredentialStore(use_env=False, preferred_backend="vault", vault_path=vault_file)

    store.set_sso_credentials("user_to_delete", "pass_to_delete")
    assert store.get_sso_credentials("user_to_delete") == ("user_to_delete", "pass_to_delete")

    deleted = store.delete_sso_credentials("user_to_delete")
    assert deleted is True

    with pytest.raises(InvalidCredentialsError):
        store.get_sso_credentials("user_to_delete")


def test_imap_credentials_fallback_to_sso(tmp_path, monkeypatch):
    monkeypatch.delenv("PRADO_USERNAME", raising=False)
    monkeypatch.delenv("PRADO_PASSWORD", raising=False)
    monkeypatch.delenv("PRADO_IMAP_USERNAME", raising=False)
    monkeypatch.delenv("PRADO_IMAP_PASSWORD", raising=False)

    vault_file = tmp_path / "credentials.vault"
    store = CredentialStore(use_env=False, preferred_backend="vault", vault_path=vault_file)

    # Store only SSO
    store.set_sso_credentials("student@correo.ugr.es", "shared_password")

    # IMAP should fallback to SSO
    user, pwd = store.get_imap_credentials("student@correo.ugr.es")
    assert user == "student@correo.ugr.es"
    assert pwd == "shared_password"

    # Now set dedicated IMAP
    store.set_imap_credentials("student@correo.ugr.es", "dedicated_imap_pass")
    user2, pwd2 = store.get_imap_credentials("student@correo.ugr.es")
    assert user2 == "student@correo.ugr.es"
    assert pwd2 == "dedicated_imap_pass"

    # Delete IMAP
    store.delete_imap_credentials("student@correo.ugr.es")
    # Should fallback back to SSO
    user3, pwd3 = store.get_imap_credentials("student@correo.ugr.es")
    assert pwd3 == "shared_password"


def test_missing_credentials_raises_error(tmp_path, monkeypatch):
    monkeypatch.delenv("PRADO_USERNAME", raising=False)
    monkeypatch.delenv("PRADO_PASSWORD", raising=False)

    vault_file = tmp_path / "empty.vault"
    store = CredentialStore(use_env=False, preferred_backend="vault", vault_path=vault_file)

    with pytest.raises(InvalidCredentialsError):
        store.get_sso_credentials("nonexistent_user")


def test_empty_credentials_validation(tmp_path):
    store = CredentialStore(use_env=False, preferred_backend="vault", vault_path=tmp_path / "v.vault")

    with pytest.raises(ValueError):
        store.set_sso_credentials("", "pass")

    with pytest.raises(ValueError):
        store.set_sso_credentials("user", "")


def test_corrupted_vault_file_handling(tmp_path, monkeypatch):
    monkeypatch.delenv("PRADO_USERNAME", raising=False)
    monkeypatch.delenv("PRADO_PASSWORD", raising=False)

    vault_file = tmp_path / "corrupted.vault"
    vault_file.write_bytes(b"garbage-non-fernet-token-data-1234567890")

    store = CredentialStore(use_env=False, preferred_backend="vault", vault_path=vault_file)
    with pytest.raises(InvalidCredentialsError):
        store.get_sso_credentials("some_user")
