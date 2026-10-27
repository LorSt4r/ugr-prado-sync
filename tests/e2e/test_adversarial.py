"""
Milestone M1 Adversarial Stress Test Suite.

Adversarially tests PradoOS authentication, credentials, session management,
and 3-tier MFA under hostile conditions, resource failures, corrupted inputs,
network dropouts, and simulated IdP errors.

Verifies:
1. CredentialStore:
   - Corrupted vault files (garbage bytes, truncated tokens, non-dict json payloads)
   - Invalid key / tampered machine salt
   - Missing keyring & OS keyring backend failures (RuntimeError, D-Bus failures)
   - Empty and malformed environment variables
2. UgrSamlDriver:
   - Simulated IdP errors: account locked, password expired, invalid credentials
   - HTTP 500, 502, 503 error responses across SP login, IdP POST, ACS POST
   - Network timeouts & connection drops across all HTTP handshakes
3. MfaResolver:
   - Malformed email bodies, corrupt MIME encodings, binary payloads
   - Missing 6-digit codes (5-digit, 7-digit, non-numeric)
   - Expired timestamps (>300 seconds)
   - Non-interactive stdin (non-TTY pipe, EOF, json mode)
4. Typed Exception Taxonomy:
   - All errors must inherit from PradoError
   - Zero credential or secret leakage in exception messages
"""

from __future__ import annotations

import base64
import email
from email.message import EmailMessage
import io
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
import requests
from cryptography.fernet import Fernet

from prado.auth.credentials import CredentialStore
from prado.auth.mfa import MfaResolver, decode_mime_header
from prado.auth.saml import UgrSamlDriver
from prado.auth.session import MoodleSessionManager
from prado.config import MfaConfig, write_secure_file
from prado.exceptions import (
    AccountLockedError,
    AuthError,
    AuthenticationRequiredError,
    ConfigError,
    InvalidCredentialsError,
    KeyringStorageError,
    MfaRequiredError,
    MfaVerificationFailedError,
    NetworkError,
    PasswordExpiredError,
    PradoError,
    SessionExpiredError,
)


class MockResponse:
    def __init__(
        self,
        text: str = "",
        status_code: int = 200,
        url: str = "https://pradogrado2627.ugr.es/my/",
        cookies: dict = None,
    ):
        self.text = text
        self.status_code = status_code
        self.url = url
        self.cookies = requests.cookies.cookiejar_from_dict(cookies or {})


# =============================================================================
# 1. CredentialStore Adversarial Stress Tests
# =============================================================================

class TestCredentialStoreAdversarial:
    def test_corrupted_vault_garbage_bytes(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PRADO_USERNAME", raising=False)
        monkeypatch.delenv("PRADO_PASSWORD", raising=False)

        vault = tmp_path / "corrupted_garbage.vault"
        vault.write_bytes(os.urandom(128))

        store = CredentialStore(use_env=False, preferred_backend="vault", vault_path=vault)
        with pytest.raises(PradoError) as exc_info:
            store.get_sso_credentials("student@correo.ugr.es")
        assert isinstance(exc_info.value, InvalidCredentialsError)

    def test_corrupted_vault_truncated_token(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PRADO_USERNAME", raising=False)
        monkeypatch.delenv("PRADO_PASSWORD", raising=False)

        vault = tmp_path / "truncated.vault"
        vault.write_bytes(b"gAAAAAB")

        store = CredentialStore(use_env=False, preferred_backend="vault", vault_path=vault)
        with pytest.raises(PradoError):
            store.get_sso_credentials()

    def test_corrupted_vault_non_dict_payload_integer(self, tmp_path, monkeypatch):
        """Stress-tests vault when decrypted JSON payload is an integer."""
        monkeypatch.delenv("PRADO_USERNAME", raising=False)
        monkeypatch.delenv("PRADO_PASSWORD", raising=False)

        vault = tmp_path / "non_dict.vault"
        store = CredentialStore(use_env=False, preferred_backend="vault", vault_path=vault)
        key = store._get_encryption_key()
        fernet = Fernet(key)
        vault.write_bytes(fernet.encrypt(json.dumps(42).encode()))

        # Loading non-dict should be gracefully handled without crashing
        with pytest.raises(PradoError):
            store.get_sso_credentials("student@correo.ugr.es")

    def test_corrupted_vault_malformed_sso_section(self, tmp_path, monkeypatch):
        """
        Adversarial test: vault contains valid Fernet and valid JSON,
        but the 'sso' field is an integer or string instead of a dictionary.
        Must raise a typed PradoError rather than unhandled TypeError / AttributeError.
        """
        monkeypatch.delenv("PRADO_USERNAME", raising=False)
        monkeypatch.delenv("PRADO_PASSWORD", raising=False)

        vault = tmp_path / "bad_sso_section.vault"
        store = CredentialStore(use_env=False, preferred_backend="vault", vault_path=vault)
        key = store._get_encryption_key()
        fernet = Fernet(key)
        # sso is int instead of dict
        vault.write_bytes(fernet.encrypt(json.dumps({"sso": 12345, "imap": {}}).encode()))

        with pytest.raises(PradoError) as exc_info:
            store.get_sso_credentials("student@correo.ugr.es")
        assert isinstance(exc_info.value, PradoError)

    def test_corrupted_vault_malformed_sso_string_single_char(self, tmp_path, monkeypatch):
        """
        Adversarial test: vault contains {'sso': 'a'}.
        When username is None, len(sso_vault) == 1 triggers .items() on str,
        which must raise typed PradoError rather than raw AttributeError.
        """
        monkeypatch.delenv("PRADO_USERNAME", raising=False)
        monkeypatch.delenv("PRADO_PASSWORD", raising=False)

        vault = tmp_path / "bad_sso_single_char.vault"
        store = CredentialStore(use_env=False, preferred_backend="vault", vault_path=vault)
        key = store._get_encryption_key()
        fernet = Fernet(key)
        vault.write_bytes(fernet.encrypt(json.dumps({"sso": "a", "imap": {}}).encode()))

        with pytest.raises(PradoError) as exc_info:
            store.get_sso_credentials()
        assert isinstance(exc_info.value, PradoError)

    def test_keyring_imap_runtime_error_fallback(self, tmp_path, monkeypatch):
        """
        When keyring.get_password / set_password raises RuntimeError for IMAP,
        it must not leak raw RuntimeError.
        """
        monkeypatch.delenv("PRADO_IMAP_USERNAME", raising=False)
        monkeypatch.delenv("PRADO_IMAP_PASSWORD", raising=False)
        monkeypatch.delenv("PRADO_USERNAME", raising=False)
        monkeypatch.delenv("PRADO_PASSWORD", raising=False)

        vault = tmp_path / "keyring_imap_err.vault"
        store = CredentialStore(use_env=False, preferred_backend="auto", vault_path=vault)

        vault_store = CredentialStore(use_env=False, preferred_backend="vault", vault_path=vault)
        vault_store.set_imap_credentials("student@correo.ugr.es", "vault_imap_pass")

        with patch("keyring.get_password", side_effect=RuntimeError("Keyring crashed")):
            user, pwd = store.get_imap_credentials("student@correo.ugr.es")
            assert user == "student@correo.ugr.es"
            assert pwd == "vault_imap_pass"

    def test_invalid_key_after_machine_salt_tampering(self, tmp_path, monkeypatch):
        """Encrypt with initial salt, then tamper salt file to simulate key invalidation."""
        monkeypatch.delenv("PRADO_USERNAME", raising=False)
        monkeypatch.delenv("PRADO_PASSWORD", raising=False)

        vault = tmp_path / "tampered_salt.vault"
        store = CredentialStore(use_env=False, preferred_backend="vault", vault_path=vault)
        store.set_sso_credentials("student@correo.ugr.es", "secret123")

        # Tamper the machine salt
        salt_file = tmp_path / ".machine_salt"
        salt_file.write_bytes(os.urandom(16))

        # Re-initialize store with new salt
        store2 = CredentialStore(use_env=False, preferred_backend="vault", vault_path=vault)
        with pytest.raises(PradoError) as exc_info:
            store2.get_sso_credentials("student@correo.ugr.es")
        assert isinstance(exc_info.value, InvalidCredentialsError)

    def test_keyring_backend_runtime_error_fallback(self, tmp_path, monkeypatch):
        """
        Adversarial test: OS keyring backend throws RuntimeError (e.g. D-Bus communication failure).
        CredentialStore must handle this gracefully without leaking raw RuntimeError.
        """
        monkeypatch.delenv("PRADO_USERNAME", raising=False)
        monkeypatch.delenv("PRADO_PASSWORD", raising=False)

        vault = tmp_path / "keyring_err.vault"
        store = CredentialStore(use_env=False, preferred_backend="auto", vault_path=vault)

        # Store fallback credential in vault
        vault_store = CredentialStore(use_env=False, preferred_backend="vault", vault_path=vault)
        vault_store.set_sso_credentials("student@correo.ugr.es", "vault_fallback_pass")

        with patch("keyring.get_password", side_effect=RuntimeError("org.freedesktop.DBus.Error.ServiceUnknown")):
            user, pwd = store.get_sso_credentials("student@correo.ugr.es")
            assert user == "student@correo.ugr.es"
            assert pwd == "vault_fallback_pass"

    def test_keyring_set_password_runtime_error_fallback_to_vault(self, tmp_path, monkeypatch):
        """
        When keyring.set_password raises an unexpected backend RuntimeError,
        it must fall back to saving in the encrypted vault.
        """
        vault = tmp_path / "keyring_set_err.vault"
        store = CredentialStore(use_env=False, preferred_backend="auto", vault_path=vault)

        with patch("keyring.set_password", side_effect=RuntimeError("Keyring backend crashed")):
            success = store.set_sso_credentials("user1@correo.ugr.es", "pass1")
            assert success is True

        # Verify it was persisted to vault
        vstore = CredentialStore(use_env=False, preferred_backend="vault", vault_path=vault)
        u, p = vstore.get_sso_credentials("user1@correo.ugr.es")
        assert u == "user1@correo.ugr.es"
        assert p == "pass1"

    def test_empty_env_vars_handling(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PRADO_USERNAME", "")
        monkeypatch.setenv("PRADO_PASSWORD", "")

        vault = tmp_path / "empty_env.vault"
        store = CredentialStore(use_env=True, preferred_backend="vault", vault_path=vault)
        with pytest.raises(PradoError) as exc_info:
            store.get_sso_credentials()
        assert isinstance(exc_info.value, InvalidCredentialsError)

    def test_whitespace_env_vars_handling(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PRADO_USERNAME", "   ")
        monkeypatch.setenv("PRADO_PASSWORD", "")

        vault = tmp_path / "ws_env.vault"
        store = CredentialStore(use_env=True, preferred_backend="vault", vault_path=vault)
        with pytest.raises(PradoError) as exc_info:
            store.get_sso_credentials()
        assert isinstance(exc_info.value, InvalidCredentialsError)

    def test_secret_not_leaked_in_exception(self, tmp_path, monkeypatch):
        """Verify password is never exposed in exception strings."""
        monkeypatch.delenv("PRADO_USERNAME", raising=False)
        monkeypatch.delenv("PRADO_PASSWORD", raising=False)

        vault = tmp_path / "leak_check.vault"
        store = CredentialStore(use_env=False, preferred_backend="vault", vault_path=vault)

        try:
            store.get_sso_credentials("missing_student")
        except Exception as e:
            msg = str(e)
            assert "secret" not in msg.lower()
            assert "password" in msg.lower() or "credentials" in msg.lower()


# =============================================================================
# 2. UgrSamlDriver Adversarial Stress Tests
# =============================================================================

class TestUgrSamlDriverAdversarial:
    def test_idp_account_locked_variations(self, tmp_path):
        """Test variations of Spanish account locked messages."""
        driver = UgrSamlDriver(session_manager=MoodleSessionManager(session_path=tmp_path / "s.json"))

        idp_html = "<form action='https://idp.ugr.es/loginuserpass' method='post'><input type='hidden' name='AuthState' value='1'/></form>"
        resp1 = MockResponse(idp_html, url="https://idp.ugr.es/loginuserpass")

        phrases = [
            "Su cuenta ha sido bloqueada temporalmente.",
            "Número de intentos superados para este usuario.",
            "Contacte con el Administrador para desbloquear.",
        ]

        for phrase in phrases:
            err_html = f"<html><div class='error'>{phrase}</div></html>"
            resp2 = MockResponse(err_html, url="https://idp.ugr.es/loginuserpass")

            with patch("requests.Session.get", return_value=resp1), \
                 patch("requests.Session.post", return_value=resp2):
                with pytest.raises(AccountLockedError) as exc_info:
                    driver.login("student@correo.ugr.es", "locked_pwd")
                assert phrase in str(exc_info.value)

    def test_idp_password_expired_variations(self, tmp_path):
        """Test variations of password expired messages."""
        driver = UgrSamlDriver(session_manager=MoodleSessionManager(session_path=tmp_path / "s.json"))

        idp_html = "<form action='https://idp.ugr.es/loginuserpass' method='post'><input type='hidden' name='AuthState' value='1'/></form>"
        resp1 = MockResponse(idp_html, url="https://idp.ugr.es/loginuserpass")

        phrases = [
            "Contraseña caducada.",
            "Es obligatorio el cambio de contraseña.",
        ]

        for phrase in phrases:
            err_html = f"<html><div class='error'>{phrase}</div></html>"
            resp2 = MockResponse(err_html, url="https://idp.ugr.es/loginuserpass")

            with patch("requests.Session.get", return_value=resp1), \
                 patch("requests.Session.post", return_value=resp2):
                with pytest.raises(PasswordExpiredError) as exc_info:
                    driver.login("student@correo.ugr.es", "expired_pwd")
                assert phrase in str(exc_info.value)

    def test_idp_http_500_on_sp_login_init(self, tmp_path):
        driver = UgrSamlDriver(session_manager=MoodleSessionManager(session_path=tmp_path / "s.json"))
        resp500 = MockResponse("500 Internal Server Error", status_code=500, url="https://pradogrado2627.ugr.es/auth/saml2/login.php")

        with patch("requests.Session.get", return_value=resp500):
            with pytest.raises(PradoError) as exc_info:
                driver.login("student@correo.ugr.es", "pwd")
            assert isinstance(exc_info.value, AuthError)

    def test_idp_http_502_bad_gateway_on_credentials_post(self, tmp_path):
        driver = UgrSamlDriver(session_manager=MoodleSessionManager(session_path=tmp_path / "s.json"))
        idp_html = "<form action='https://idp.ugr.es/loginuserpass' method='post'><input type='hidden' name='AuthState' value='1'/></form>"
        resp1 = MockResponse(idp_html, url="https://idp.ugr.es/loginuserpass")
        resp502 = MockResponse("502 Bad Gateway", status_code=502, url="https://idp.ugr.es/loginuserpass")

        with patch("requests.Session.get", return_value=resp1), \
             patch("requests.Session.post", return_value=resp502):
            with pytest.raises(PradoError) as exc_info:
                driver.login("student@correo.ugr.es", "pwd")
            assert isinstance(exc_info.value, AuthError)

    def test_sp_acs_http_503_service_unavailable(self, tmp_path):
        driver = UgrSamlDriver(session_manager=MoodleSessionManager(session_path=tmp_path / "s.json"))
        idp_html = "<form action='https://idp.ugr.es/loginuserpass' method='post'><input type='hidden' name='AuthState' value='1'/></form>"
        resp1 = MockResponse(idp_html, url="https://idp.ugr.es/loginuserpass")
        saml_html = "<form action='https://pradogrado2627.ugr.es/saml2-acs.php' method='post'><input type='hidden' name='SAMLResponse' value='tok'/></form>"
        resp2 = MockResponse(saml_html, url="https://idp.ugr.es/loginuserpass")
        resp503 = MockResponse("503 Service Unavailable", status_code=503, url="https://pradogrado2627.ugr.es/saml2-acs.php")

        with patch("requests.Session.get", return_value=resp1), \
             patch("requests.Session.post", side_effect=[resp2, resp503]):
            with pytest.raises(PradoError) as exc_info:
                driver.login("student@correo.ugr.es", "pwd")
            assert isinstance(exc_info.value, AuthError)

    def test_network_connect_timeout_raises_typed_error(self, tmp_path):
        driver = UgrSamlDriver(session_manager=MoodleSessionManager(session_path=tmp_path / "s.json"))
        with patch("requests.Session.get", side_effect=requests.exceptions.ConnectTimeout("Connect timeout")):
            with pytest.raises(PradoError) as exc_info:
                driver.login("student@correo.ugr.es", "pwd")
            assert isinstance(exc_info.value, AuthError)

    def test_mfa_submission_network_timeout_must_raise_typed_error(self, tmp_path):
        """
        Adversarial test: network timeout during MFA code POST.
        Must raise a typed PradoError (AuthError/NetworkError) instead of raw requests.exceptions.Timeout.
        """
        mgr = MoodleSessionManager(session_path=tmp_path / "s.json")
        mfa = MfaResolver(agent_code="123456")
        driver = UgrSamlDriver(session_manager=mgr, mfa_resolver=mfa)

        idp_html = "<form action='https://idp.ugr.es/loginuserpass' method='post'><input type='hidden' name='AuthState' value='1'/></form>"
        saml_html = "<form action='https://pradogrado2627.ugr.es/saml2-acs.php' method='post'><input type='hidden' name='SAMLResponse' value='tok'/></form>"
        mfa_html = "<form action='https://pradogrado2627.ugr.es/admin/tool/mfa/auth.php' method='post'><input type='hidden' name='sesskey' value='k'/></form>"

        def mock_get(url, *args, **kwargs):
            return MockResponse(idp_html)

        def mock_post(url, *args, **kwargs):
            if "loginuserpass" in url:
                return MockResponse(saml_html)
            if "saml2-acs.php" in url:
                return MockResponse(mfa_html, url="https://pradogrado2627.ugr.es/admin/tool/mfa/auth.php")
            if "admin/tool/mfa" in url:
                raise requests.exceptions.ReadTimeout("MFA server read timeout")
            return MockResponse("404", 404)

        with patch("requests.Session.get", side_effect=mock_get), \
             patch("requests.Session.post", side_effect=mock_post):
            with pytest.raises(PradoError) as exc_info:
                driver.login("student@correo.ugr.es", "pwd")
            assert isinstance(exc_info.value, PradoError)


# =============================================================================
# 3. MfaResolver Adversarial Stress Tests
# =============================================================================

class TestMfaResolverAdversarial:
    def test_malformed_email_headers_and_body(self):
        cfg = MfaConfig(imap_enabled=True)
        resolver = MfaResolver(mfa_config=cfg)

        raw_corrupt = b"From: =?bad?=\r\nSubject: =?bad?=\r\n\r\n\x00\xff\xfe\xaa"
        mock_client = MagicMock()
        mock_client.search.return_value = ("OK", [b"1"])
        mock_client.fetch.return_value = ("OK", [(b"1 (RFC822)", raw_corrupt)])

        with patch("imaplib.IMAP4_SSL", return_value=mock_client):
            code = resolver.fetch_from_imap(timeout_seconds=0.2, poll_interval_seconds=0.05)
            assert code is None

    def test_email_body_without_6_digit_code(self):
        cfg = MfaConfig(imap_enabled=True)
        resolver = MfaResolver(mfa_config=cfg)

        msg = EmailMessage()
        msg["Subject"] = "Código de verificación PRADO"
        msg["Date"] = email.utils.formatdate()
        msg.set_content("No numbers in this message body at all.")

        mock_client = MagicMock()
        mock_client.search.return_value = ("OK", [b"1"])
        mock_client.fetch.return_value = ("OK", [(b"1 (RFC822)", msg.as_bytes())])

        with patch("imaplib.IMAP4_SSL", return_value=mock_client):
            code = resolver.fetch_from_imap(timeout_seconds=0.2, poll_interval_seconds=0.05)
            assert code is None

    def test_email_body_with_5_or_7_digits_ignored(self):
        cfg = MfaConfig(imap_enabled=True)
        resolver = MfaResolver(mfa_config=cfg)

        msg = EmailMessage()
        msg["Subject"] = "Código de verificación PRADO"
        msg["Date"] = email.utils.formatdate()
        msg.set_content("Códigos: 12345 y 1234567 no son válidos.")

        mock_client = MagicMock()
        mock_client.search.return_value = ("OK", [b"1"])
        mock_client.fetch.return_value = ("OK", [(b"1 (RFC822)", msg.as_bytes())])

        with patch("imaplib.IMAP4_SSL", return_value=mock_client):
            code = resolver.fetch_from_imap(timeout_seconds=0.2, poll_interval_seconds=0.05)
            assert code is None

    def test_expired_email_timestamp_ignored(self):
        cfg = MfaConfig(imap_enabled=True)
        resolver = MfaResolver(mfa_config=cfg)

        msg = EmailMessage()
        msg["Subject"] = "Código de verificación PRADO"
        # 400 seconds ago (cutoff is 300 seconds)
        msg["Date"] = email.utils.formatdate(time.time() - 400)
        msg.set_content("Código: 654321")

        mock_client = MagicMock()
        mock_client.search.return_value = ("OK", [b"1"])
        mock_client.fetch.return_value = ("OK", [(b"1 (RFC822)", msg.as_bytes())])

        with patch("imaplib.IMAP4_SSL", return_value=mock_client):
            code = resolver.fetch_from_imap(timeout_seconds=0.2, poll_interval_seconds=0.05)
            assert code is None

    def test_non_interactive_non_tty_raises_typed_mfa_required(self):
        cfg = MfaConfig(apple_mail_enabled=False, imap_enabled=False)
        resolver = MfaResolver(mfa_config=cfg, interactive=True)

        with patch.object(sys.stdin, "isatty", return_value=False):
            with pytest.raises(MfaRequiredError) as exc_info:
                resolver.resolve_code()
            err = exc_info.value
            assert err.tier == 3
            assert err.factor == "email"

    def test_interactive_tty_eof_raises_verification_error(self):
        cfg = MfaConfig(apple_mail_enabled=False, imap_enabled=False)
        resolver = MfaResolver(mfa_config=cfg, interactive=True)

        with patch.object(sys.stdin, "isatty", return_value=True), \
             patch.object(sys.stdin, "readline", return_value=""):
            with pytest.raises(MfaVerificationFailedError) as exc_info:
                resolver.prompt_user_interactive()
            assert "Invalid verification code format" in str(exc_info.value)

    def test_extract_mfa_details_empty_or_broken_html_raises_typed_error(self):
        with pytest.raises(MfaVerificationFailedError):
            MfaResolver.extract_mfa_form_details("", "https://prado.ugr.es/mfa")

        with pytest.raises(MfaVerificationFailedError):
            MfaResolver.extract_mfa_form_details("<html><div>no sesskey</div></html>", "https://prado.ugr.es/mfa")
