"""
Unified multi-tier credential storage for PradoOS.

Storage hierarchy:
1. Environment variables (PRADO_USERNAME, PRADO_PASSWORD, PRADO_IMAP_PASSWORD)
2. Native OS Keyring (macOS Keychain, Windows Credential Manager, Linux SecretService)
3. Encrypted Fallback Vault (Fernet/AES-128-CBC + HMAC-SHA256 with mode 0600 permissions)
"""

from __future__ import annotations

import base64
import json
import os
import platform
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import keyring
from keyring.errors import KeyringError, NoKeyringError
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from prado.config import get_config_dir, get_credentials_vault_file, write_secure_file
from prado.exceptions import InvalidCredentialsError, KeyringStorageError


class CredentialStore:
    """
    Manages credentials across Environment variables, OS native keyring, and encrypted vault file.
    """

    SERVICE_SSO = "prado:sso"
    SERVICE_IMAP = "prado:imap"

    def __init__(
        self,
        use_env: bool = True,
        preferred_backend: str = "auto",  # 'auto', 'keyring', 'vault', 'env'
        vault_path: Optional[Path] = None,
    ) -> None:
        self.use_env = use_env
        self.preferred_backend = preferred_backend
        self.vault_path = vault_path or get_credentials_vault_file()

    def _get_encryption_key(self) -> bytes:
        """
        Derives a reproducible 32-byte Fernet key based on machine identity and a local salt.
        """
        salt_file = self.vault_path.parent / ".machine_salt"
        if salt_file.exists():
            try:
                with open(salt_file, "rb") as f:
                    salt = f.read()
            except OSError:
                salt = b"prado-default-salt"
        else:
            salt = os.urandom(16)
            write_secure_file(salt_file, salt, mode=0o600)

        machine_seed = f"{platform.node()}-{uuid.getnode()}-{os.environ.get('USER', 'default')}"
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        derived = kdf.derive(machine_seed.encode("utf-8"))
        return base64.urlsafe_b64encode(derived)

    def _load_vault(self) -> Dict[str, Dict[str, str]]:
        """Loads and decrypts credentials from the encrypted vault file."""
        if not self.vault_path.exists():
            return {"sso": {}, "imap": {}}

        try:
            with open(self.vault_path, "rb") as f:
                encrypted_data = f.read()
            if not encrypted_data:
                return {"sso": {}, "imap": {}}

            key = self._get_encryption_key()
            fernet = Fernet(key)
            decrypted = fernet.decrypt(encrypted_data)
            data = json.loads(decrypted.decode("utf-8"))
            if not isinstance(data, dict):
                return {"sso": {}, "imap": {}}
            if not isinstance(data.get("sso"), dict):
                data["sso"] = {}
            if not isinstance(data.get("imap"), dict):
                data["imap"] = {}
            return data
        except (InvalidToken, json.JSONDecodeError, OSError):
            return {"sso": {}, "imap": {}}

    def _save_vault(self, data: Dict[str, Dict[str, str]]) -> None:
        """Encrypts and writes credentials to the vault file with mode 0600."""
        key = self._get_encryption_key()
        fernet = Fernet(key)
        payload = json.dumps(data).encode("utf-8")
        encrypted = fernet.encrypt(payload)
        write_secure_file(self.vault_path, encrypted, mode=0o600)

    def _is_keyring_usable(self) -> bool:
        """Checks if a functional OS keyring backend is available."""
        if self.preferred_backend in ("vault", "env"):
            return False
        try:
            current_keyring = keyring.get_keyring()
            # If priority <= 0 (e.g. fail.Keyring or null backend), keyring is not usable
            if getattr(current_keyring, "priority", 1) <= 0:
                return False
            return True
        except Exception:
            return False

    def get_sso_credentials(self, default_username: Optional[str] = None) -> Tuple[str, str]:
        """
        Retrieves SSO credentials (username, password).
        Precedence:
        1. Environment variables (PRADO_USERNAME, PRADO_PASSWORD)
        2. OS Keyring
        3. Encrypted Vault
        """
        # Tier 1: Environment variables
        if self.use_env and self.preferred_backend != "vault":
            env_user = os.environ.get("PRADO_USERNAME") or default_username
            env_pass = os.environ.get("PRADO_PASSWORD")
            if env_user and env_pass:
                return env_user, env_pass

        target_user = os.environ.get("PRADO_USERNAME") or default_username

        # Tier 2: OS Keyring
        if self._is_keyring_usable() and target_user:
            try:
                pwd = keyring.get_password(self.SERVICE_SSO, target_user)
                if pwd:
                    return target_user, pwd
            except (KeyringError, NoKeyringError, Exception):
                pass

        # Tier 3: Encrypted Vault
        vault = self._load_vault()
        sso_vault = vault.get("sso", {})
        if target_user and target_user in sso_vault:
            return target_user, sso_vault[target_user]

        # If username wasn't given, see if vault has exactly one SSO user
        if not target_user and len(sso_vault) == 1:
            u, p = next(iter(sso_vault.items()))
            return u, p

        raise InvalidCredentialsError(
            f"No SSO credentials found for username '{target_user or 'unknown'}'. "
            "Please configure credentials via 'prado auth' or PRADO_USERNAME/PRADO_PASSWORD."
        )

    def set_sso_credentials(self, username: str, password: str) -> bool:
        """
        Persists SSO credentials into OS Keyring or encrypted vault fallback.
        """
        if not username or not password:
            raise ValueError("Username and password must not be empty.")

        saved_in_keyring = False
        if self._is_keyring_usable():
            try:
                keyring.set_password(self.SERVICE_SSO, username, password)
                saved_in_keyring = True
            except (KeyringError, NoKeyringError, Exception):
                saved_in_keyring = False

        if not saved_in_keyring:
            vault = self._load_vault()
            vault["sso"][username] = password
            self._save_vault(vault)

        return True

    def delete_sso_credentials(self, username: str) -> bool:
        """Deletes SSO credentials from Keyring and Vault."""
        deleted = False
        if self._is_keyring_usable():
            try:
                keyring.delete_password(self.SERVICE_SSO, username)
                deleted = True
            except Exception:
                pass

        vault = self._load_vault()
        if username in vault.get("sso", {}):
            del vault["sso"][username]
            self._save_vault(vault)
            deleted = True

        return deleted

    def get_imap_credentials(self, default_username: Optional[str] = None) -> Tuple[str, str]:
        """
        Retrieves IMAP credentials (username, password).
        Falls back to SSO credentials if dedicated IMAP credentials are not set.
        """
        if self.use_env and self.preferred_backend != "vault":
            env_user = os.environ.get("PRADO_IMAP_USERNAME") or os.environ.get("PRADO_USERNAME") or default_username
            env_pass = os.environ.get("PRADO_IMAP_PASSWORD")
            if env_user and env_pass:
                return env_user, env_pass

        target_user = os.environ.get("PRADO_IMAP_USERNAME") or os.environ.get("PRADO_USERNAME") or default_username

        if self._is_keyring_usable() and target_user:
            try:
                pwd = keyring.get_password(self.SERVICE_IMAP, target_user)
                if pwd:
                    return target_user, pwd
            except (KeyringError, NoKeyringError, Exception):
                pass

        vault = self._load_vault()
        imap_vault = vault.get("imap", {})
        if target_user and target_user in imap_vault:
            return target_user, imap_vault[target_user]

        # Fallback to SSO credentials if IMAP-specific credentials are not found
        try:
            return self.get_sso_credentials(default_username=target_user)
        except InvalidCredentialsError:
            raise InvalidCredentialsError(f"No IMAP credentials found for user '{target_user or 'unknown'}'.")

    def set_imap_credentials(self, username: str, password: str) -> bool:
        """Persists IMAP credentials into Keyring or encrypted vault fallback."""
        if not username or not password:
            raise ValueError("Username and password must not be empty.")

        saved_in_keyring = False
        if self._is_keyring_usable():
            try:
                keyring.set_password(self.SERVICE_IMAP, username, password)
                saved_in_keyring = True
            except (KeyringError, NoKeyringError):
                saved_in_keyring = False

        if not saved_in_keyring:
            vault = self._load_vault()
            vault["imap"][username] = password
            self._save_vault(vault)

        return True

    def delete_imap_credentials(self, username: str) -> bool:
        """Deletes IMAP credentials from Keyring and Vault."""
        deleted = False
        if self._is_keyring_usable():
            try:
                keyring.delete_password(self.SERVICE_IMAP, username)
                deleted = True
            except Exception:
                pass

        vault = self._load_vault()
        if username in vault.get("imap", {}):
            del vault["imap"][username]
            self._save_vault(vault)
            deleted = True

        return deleted
