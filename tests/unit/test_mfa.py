"""
Unit tests for PradoOS 3-Tier Multi-Factor Authentication (MFA) resolution.
"""

import email
from email.message import EmailMessage
import io
import os
import sys
import time
from unittest.mock import MagicMock, patch
import pytest
import requests

from prado.auth.mfa import MfaResolver, decode_mime_header
from prado.auth.saml import UgrSamlDriver
from prado.auth.session import MoodleSessionManager
from prado.config import MfaConfig
from prado.exceptions import (
    MfaRequiredError,
    MfaVerificationFailedError,
)


class MockResponse:
    def __init__(self, text: str, status_code: int = 200, url: str = "https://pradogrado2627.ugr.es/my/"):
        self.text = text
        self.status_code = status_code
        self.url = url


# =========================================================================
# 1. MIME Header and Helper Tests
# =========================================================================


def test_decode_mime_header():
    # Plain ascii
    assert decode_mime_header("Simple Subject") == "Simple Subject"
    assert decode_mime_header("") == ""
    assert decode_mime_header(None) == ""

    # RFC 2047 encoded header: "=?UTF-8?B?...?="
    # "código de verificación" base64: Y8OzZGlnbyBkZSB2ZXJpZmljYWNpw7Nu
    encoded = "=?UTF-8?B?Y8OzZGlnbyBkZSB2ZXJpZmljYWNpw7Nu?="
    assert "código de verificación" in decode_mime_header(encoded)


# =========================================================================
# 2. Tier 3: Explicit / Agent / JSON Mode / TTY Tests
# =========================================================================


def test_mfa_explicit_agent_code():
    resolver = MfaResolver(agent_code="842109")
    code = resolver.resolve_code()
    assert code == "842109"


def test_mfa_env_variable_code(monkeypatch):
    monkeypatch.setenv("PRADO_MFA_CODE", "998877")
    resolver = MfaResolver()
    code = resolver.resolve_code()
    assert code == "998877"


def test_mfa_non_interactive_raises_mfa_required_error():
    cfg = MfaConfig(apple_mail_enabled=False)
    resolver = MfaResolver(mfa_config=cfg, interactive=False)
    with pytest.raises(MfaRequiredError) as exc_info:
        resolver.resolve_code()

    err = exc_info.value
    assert err.factor == "email"
    assert err.tier == 3
    assert "Two-factor verification code required" in str(err)


def test_mfa_json_mode_raises_mfa_required_error():
    cfg = MfaConfig(apple_mail_enabled=False)
    resolver = MfaResolver(mfa_config=cfg, interactive=True, json_mode=True)
    with pytest.raises(MfaRequiredError) as exc_info:
        resolver.resolve_code()

    assert exc_info.value.tier == 3


def test_mfa_interactive_tty_prompt():
    cfg = MfaConfig(apple_mail_enabled=False)
    resolver = MfaResolver(mfa_config=cfg, interactive=True, json_mode=False)

    with patch.object(sys.stdin, "isatty", return_value=True), \
         patch.object(sys.stdin, "readline", return_value="123456\n"):
        code = resolver.resolve_code()
        assert code == "123456"


def test_mfa_interactive_tty_invalid_format_raises_error():
    cfg = MfaConfig(apple_mail_enabled=False)
    resolver = MfaResolver(mfa_config=cfg, interactive=True, json_mode=False)

    with patch.object(sys.stdin, "isatty", return_value=True), \
         patch.object(sys.stdin, "readline", return_value="invalid_code\n"):
        with pytest.raises(MfaVerificationFailedError) as exc_info:
            resolver.resolve_code()
        assert "Invalid verification code format" in str(exc_info.value)


# =========================================================================
# 3. Tier 2a: IMAP SSL Auto-Fetch Tests
# =========================================================================


def test_mfa_imap_fetch_plain_text():
    cfg = MfaConfig(imap_enabled=True, imap_username="student@correo.ugr.es")
    resolver = MfaResolver(mfa_config=cfg)

    # Build RFC 822 email message
    msg = EmailMessage()
    msg["Subject"] = "Código de verificación de PRADO"
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg.set_content("Su código de verificación para acceder a PRADO es: 456789. Es válido durante 5 minutos.")
    raw_email = msg.as_bytes()

    mock_client = MagicMock()
    mock_client.search.return_value = ("OK", [b"1"])
    mock_client.fetch.return_value = ("OK", [(b"1 (RFC822)", raw_email)])

    with patch("imaplib.IMAP4_SSL", return_value=mock_client):
        code = resolver.fetch_from_imap(
            host="imap.ugr.es",
            username="student@correo.ugr.es",
            password="secret_password",
            timeout_seconds=2,
            poll_interval_seconds=0.1,
        )
        assert code == "456789"


def test_mfa_imap_fetch_multipart_html():
    cfg = MfaConfig(imap_enabled=True, imap_username="student@correo.ugr.es")
    resolver = MfaResolver(mfa_config=cfg)

    # Build multipart email message
    msg = EmailMessage()
    msg["Subject"] = "Verification code PRADO UGR"
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg.set_content("Plain text fallback")
    msg.add_alternative(
        "<html><body><p>Your authentication code is <b>789123</b>.</p></body></html>",
        subtype="html",
    )
    raw_email = msg.as_bytes()

    mock_client = MagicMock()
    mock_client.search.return_value = ("OK", [b"10"])
    mock_client.fetch.return_value = ("OK", [(b"10 (RFC822)", raw_email)])

    with patch("imaplib.IMAP4_SSL", return_value=mock_client):
        code = resolver.fetch_from_imap(
            host="imap.ugr.es",
            username="student@correo.ugr.es",
            password="secret_password",
            timeout_seconds=2,
            poll_interval_seconds=0.1,
        )
        assert code == "789123"


def test_mfa_imap_ignores_stale_or_unrelated_emails():
    cfg = MfaConfig(imap_enabled=True)
    resolver = MfaResolver(mfa_config=cfg)

    # 1. Unrelated subject
    msg1 = EmailMessage()
    msg1["Subject"] = "Welcome to Universidad de Granada"
    msg1["Date"] = email.utils.formatdate()
    msg1.set_content("Your student ID is 123456.")

    # 2. Stale message (> 5 minutes ago)
    msg2 = EmailMessage()
    msg2["Subject"] = "Código de verificación PRADO"
    msg2["Date"] = email.utils.formatdate(time.time() - 600)
    msg2.set_content("El código expirado es: 999999.")

    mock_client = MagicMock()
    mock_client.search.return_value = ("OK", [b"1 2"])
    mock_client.fetch.side_effect = [
        ("OK", [(b"1 (RFC822)", msg1.as_bytes())]),
        ("OK", [(b"2 (RFC822)", msg2.as_bytes())]),
    ]

    with patch("imaplib.IMAP4_SSL", return_value=mock_client):
        code = resolver.fetch_from_imap(
            host="imap.ugr.es",
            username="student@correo.ugr.es",
            password="secret_password",
            timeout_seconds=0.3,
            poll_interval_seconds=0.1,
        )
        assert code is None


# =========================================================================
# 4. Tier 2b: Apple Mail Fallback Tests
# =========================================================================


def test_mfa_apple_mail_fallback_darwin(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    resolver = MfaResolver()

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = "Estimado usuario,\nSu código de verificación para PRADO es 314159."

    with patch("subprocess.run", return_value=mock_proc):
        code = resolver.fetch_from_apple_mail(timeout_seconds=1, poll_interval_seconds=0.1)
        assert code == "314159"


def test_mfa_apple_mail_non_darwin(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    resolver = MfaResolver()
    assert resolver.fetch_from_apple_mail() is None


# =========================================================================
# 5. Form Parsing & Submission Tests
# =========================================================================


def test_extract_mfa_form_details():
    html = """
    <html>
      <form action="/admin/tool/mfa/auth.php" method="post">
        <input type="hidden" name="sesskey" value="sess_token_777" />
        <input type="text" name="verificationcode" />
      </form>
    </html>
    """
    url, sesskey = MfaResolver.extract_mfa_form_details(html, "https://pradogrado2627.ugr.es/auth/saml2/login.php")
    assert "admin/tool/mfa/auth.php" in url
    assert sesskey == "sess_token_777"


def test_extract_mfa_form_details_missing_sesskey_raises():
    html = "<html><form action='/admin/tool/mfa/auth.php'></form></html>"
    with pytest.raises(MfaVerificationFailedError):
        MfaResolver.extract_mfa_form_details(html, "https://pradogrado2627.ugr.es/mfa")


def test_submit_mfa_code_success():
    session = requests.Session()
    resolver = MfaResolver()

    resp_my = MockResponse("<html><div class='usermenu'>Área personal</div></html>", 200, "https://pradogrado2627.ugr.es/my/")

    with patch.object(session, "post", return_value=resp_my) as mock_post:
        resp = resolver.submit_mfa_code(
            session=session,
            mfa_url="https://pradogrado2627.ugr.es/admin/tool/mfa/auth.php",
            sesskey="sess123",
            code="654321",
            trust_device=True,
        )
        assert resp.url == "https://pradogrado2627.ugr.es/my/"
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args[1]
        data = call_kwargs["data"]
        assert data["verificationcode"] == "654321"
        assert data["factor_token_trust"] == "1"
        assert data["sesskey"] == "sess123"


def test_submit_mfa_code_rejected_raises():
    session = requests.Session()
    resolver = MfaResolver()

    err_html = "<html><div class='error'>Código de verificación no válido o caducado.</div></html>"
    resp_err = MockResponse(err_html, 200, "https://pradogrado2627.ugr.es/admin/tool/mfa/auth.php")

    with patch.object(session, "post", return_value=resp_err):
        with pytest.raises(MfaVerificationFailedError) as exc_info:
            resolver.submit_mfa_code(
                session=session,
                mfa_url="https://pradogrado2627.ugr.es/admin/tool/mfa/auth.php",
                sesskey="sess123",
                code="000000",
            )
        assert "Código de verificación no válido" in str(exc_info.value)


# =========================================================================
# 6. End-to-End SAML Login with MFA Interception
# =========================================================================


def test_saml_login_with_mfa_flow(tmp_path):
    mgr = MoodleSessionManager(session_path=tmp_path / "session.json")
    mfa_res = MfaResolver(agent_code="112233")
    driver = UgrSamlDriver(session_manager=mgr, mfa_resolver=mfa_res)

    idp_html = """
    <form action="https://idp.ugr.es/loginuserpass" method="post">
      <input type="hidden" name="AuthState" value="_state_1" />
    </form>
    """
    saml_assertion_html = """
    <form action="https://pradogrado2627.ugr.es/saml2-acs.php" method="post">
      <input type="hidden" name="SAMLResponse" value="token" />
    </form>
    """
    mfa_page_html = """
    <html>
      <form action="https://pradogrado2627.ugr.es/admin/tool/mfa/auth.php" method="post">
        <input type="hidden" name="sesskey" value="test_sesskey_999" />
      </form>
    </html>
    """
    moodle_home_html = "<div class='usermenu'>Área personal</div>logout.php?sesskey=x"

    resp1 = MockResponse(idp_html, url="https://idp.ugr.es/loginuserpass")
    resp2 = MockResponse(saml_assertion_html, url="https://idp.ugr.es/loginuserpass")
    resp3_mfa = MockResponse(mfa_page_html, url="https://pradogrado2627.ugr.es/admin/tool/mfa/auth.php")
    resp4_home = MockResponse(moodle_home_html, url="https://pradogrado2627.ugr.es/my/")

    def mock_get(url, *args, **kwargs):
        if "login.php" in url:
            return resp1
        if "/my/" in url:
            return resp4_home
        return MockResponse("404", 404)

    def mock_post(url, *args, **kwargs):
        if "loginuserpass" in url:
            return resp2
        if "saml2-acs.php" in url:
            return resp3_mfa  # Trigger MFA
        if "admin/tool/mfa" in url:
            return resp4_home  # MFA successful
        return MockResponse("404", 404)

    with patch("requests.Session.get", side_effect=mock_get), \
         patch("requests.Session.post", side_effect=mock_post):
        authed = driver.login("student@correo.ugr.es", "password")
        assert authed is not None
        assert (tmp_path / "session.json").exists()
