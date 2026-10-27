"""
Unit tests for PradoOS SAML Single Sign-On (SSO) driver and MoodleSessionManager.
"""

import json
import os
import stat
import time
from unittest.mock import MagicMock, patch
import pytest
import requests

from prado.auth.credentials import CredentialStore
from prado.auth.mfa import MfaResolver
from prado.auth.saml import UgrSamlDriver
from prado.auth.session import MoodleSessionManager
from prado.exceptions import (
    AccountLockedError,
    AuthError,
    AuthenticationRequiredError,
    InvalidCredentialsError,
    PasswordExpiredError,
)


class MockResponse:
    """Helper mock response object for requests."""

    def __init__(
        self,
        text: str,
        status_code: int = 200,
        url: str = "https://pradogrado2627.ugr.es/my/",
        cookies: dict = None,
    ):
        self.text = text
        self.status_code = status_code
        self.url = url
        self.cookies = requests.cookies.cookiejar_from_dict(cookies or {})


# =========================================================================
# 1. MoodleSessionManager Tests
# =========================================================================


def test_session_manager_save_and_load(tmp_path):
    session_file = tmp_path / "session.json"
    mgr = MoodleSessionManager(session_path=session_file, base_url="https://pradogrado2627.ugr.es")

    # Set some test cookies
    future_time = time.time() + 3600
    mgr.session.cookies.set("MoodleSession", "sess_token_123", domain="pradogrado2627.ugr.es", path="/")
    mgr.session.cookies.set("MFA_TOKEN_test", "trust_token_abc", domain="pradogrado2627.ugr.es", path="/", expires=future_time)

    mgr.save_session()
    assert session_file.exists()

    if os.name != "nt":
        assert stat.S_IMODE(os.stat(session_file).st_mode) == 0o600

    # Load in new manager
    mgr2 = MoodleSessionManager(session_path=session_file, base_url="https://pradogrado2627.ugr.es")
    loaded = mgr2.load_session()
    assert loaded is True
    assert mgr2.session.cookies.get("MoodleSession") == "sess_token_123"
    assert mgr2.session.cookies.get("MFA_TOKEN_test") == "trust_token_abc"


def test_session_manager_filters_expired_cookies(tmp_path):
    session_file = tmp_path / "session.json"
    past_time = time.time() - 3600
    future_time = time.time() + 3600

    raw_cookies = [
        {"name": "MoodleSession", "value": "active_sess", "expires": future_time},
        {"name": "MFA_TOKEN_old", "value": "expired_token", "expires": past_time},
    ]
    session_file.write_text(json.dumps(raw_cookies), encoding="utf-8")

    mgr = MoodleSessionManager(session_path=session_file)
    mgr.load_session()

    assert mgr.session.cookies.get("MoodleSession") == "active_sess"
    assert mgr.session.cookies.get("MFA_TOKEN_old") is None


def test_session_manager_clear_session(tmp_path):
    session_file = tmp_path / "session.json"
    session_file.write_text("[]", encoding="utf-8")

    mgr = MoodleSessionManager(session_path=session_file)
    mgr.session.cookies.set("TestCookie", "val")
    mgr.clear_session()

    assert not session_file.exists()
    assert len(mgr.session.cookies) == 0


def test_session_manager_extract_and_inject_mfa_tokens(tmp_path):
    session_file = tmp_path / "session.json"
    mgr = MoodleSessionManager(session_path=session_file)

    future_time = time.time() + 86400 * 30
    mgr.session.cookies.set("MFA_TOKEN_01", "tok1", expires=future_time)
    mgr.session.cookies.set("MOODLEID1_", "usr1", expires=future_time)
    mgr.session.cookies.set("OtherCookie", "val2")

    tokens = mgr.extract_mfa_tokens()
    names = [t["name"] for t in tokens]
    assert "MFA_TOKEN_01" in names
    assert "MOODLEID1_" in names
    assert "OtherCookie" not in names

    # Test injection into new session
    fresh_session = requests.Session()
    mgr.inject_preserved_tokens(fresh_session)
    assert fresh_session.cookies.get("MFA_TOKEN_01") == "tok1"
    assert fresh_session.cookies.get("MOODLEID1_") == "usr1"


def test_session_manager_is_session_valid():
    mgr = MoodleSessionManager(base_url="https://pradogrado2627.ugr.es")

    # Valid response
    valid_resp = MockResponse(
        text="<html><body><div class='usermenu'>Área personal</div><a href='login/logout.php?sesskey=xyz'>Logout</a></body></html>",
        status_code=200,
        url="https://pradogrado2627.ugr.es/my/",
    )
    with patch.object(mgr.session, "get", return_value=valid_resp):
        assert mgr.is_session_valid() is True

    # Redirect to IdP
    idp_resp = MockResponse(
        text="<html><form action='loginuserpass'></form></html>",
        status_code=200,
        url="https://idp.ugr.es/simplesaml/module.php/core/loginuserpass",
    )
    with patch.object(mgr.session, "get", return_value=idp_resp):
        assert mgr.is_session_valid() is False

    # Redirect to MFA
    mfa_resp = MockResponse(
        text="<html>Verificación en 2 pasos</html>",
        status_code=200,
        url="https://pradogrado2627.ugr.es/admin/tool/mfa/auth.php",
    )
    with patch.object(mgr.session, "get", return_value=mfa_resp):
        assert mgr.is_session_valid() is False

    # HTTP 500 Error
    err_resp = MockResponse(text="Server Error", status_code=500)
    with patch.object(mgr.session, "get", return_value=err_resp):
        assert mgr.is_session_valid() is False


def test_session_manager_get_authenticated_session_raises(tmp_path):
    session_file = tmp_path / "nonexistent_session.json"
    mgr = MoodleSessionManager(session_path=session_file)

    with pytest.raises(AuthenticationRequiredError):
        mgr.get_authenticated_session()


# =========================================================================
# 2. UgrSamlDriver Tests
# =========================================================================


def test_saml_successful_login(tmp_path):
    session_file = tmp_path / "session.json"
    mgr = MoodleSessionManager(session_path=session_file, base_url="https://pradogrado2627.ugr.es")
    driver = UgrSamlDriver(base_url="https://pradogrado2627.ugr.es", session_manager=mgr)

    # 1. SP redirect response to IdP
    idp_html = """
    <html>
      <body>
        <form action="https://idp.ugr.es/simplesaml/module.php/core/loginuserpass" method="post">
          <input type="hidden" name="AuthState" value="_state_hash_123" />
          <input type="text" name="username" />
          <input type="password" name="password" />
        </form>
      </body>
    </html>
    """
    resp1 = MockResponse(text=idp_html, url="https://idp.ugr.es/simplesaml/module.php/core/loginuserpass?AuthState=_state_hash_123")

    # 2. IdP POST credentials response: returns SAML assertion form
    saml_assertion_html = """
    <html>
      <body>
        <form action="https://pradogrado2627.ugr.es/auth/saml2/sp/saml2-acs.php/pradogrado2627.ugr.es" method="post">
          <input type="hidden" name="SAMLResponse" value="PHNhbWxwOlJlc3BvbnNlPjwvc2FtbHA6UmVzcG9uc2U+" />
          <input type="hidden" name="RelayState" value="https://pradogrado2627.ugr.es/auth/saml2/login.php" />
        </form>
      </body>
    </html>
    """
    resp2 = MockResponse(text=saml_assertion_html, url="https://idp.ugr.es/simplesaml/module.php/core/loginuserpass")

    # 3. SP ACS response: landing on Moodle /my/
    moodle_my_html = """
    <html>
      <body>
        <div class="usermenu">Área personal</div>
        <a href="https://pradogrado2627.ugr.es/login/logout.php?sesskey=abc1234">Salir</a>
      </body>
    </html>
    """
    resp3 = MockResponse(text=moodle_my_html, url="https://pradogrado2627.ugr.es/my/")

    # Setup mock session
    def mock_get(url, *args, **kwargs):
        if "login.php" in url:
            return resp1
        if "/my/" in url:
            return resp3
        return MockResponse("Not found", 404)

    def mock_post(url, *args, **kwargs):
        if "loginuserpass" in url:
            return resp2
        if "saml2-acs.php" in url:
            return resp3
        return MockResponse("Not found", 404)

    with patch("requests.Session.get", side_effect=mock_get), \
         patch("requests.Session.post", side_effect=mock_post):
        authed_session = driver.login("student@correo.ugr.es", "correct_password")
        assert authed_session is not None
        assert session_file.exists()


def test_saml_retry_url_handling(tmp_path):
    mgr = MoodleSessionManager(session_path=tmp_path / "session.json")
    driver = UgrSamlDriver(session_manager=mgr)

    # Initial page contains retryURL due to stale state
    retry_page_html = """
    <html>
      <body>
        <input type="hidden" name="retryURL" value="https://idp.ugr.es/retry_flow" />
      </body>
    </html>
    """
    resp1_stale = MockResponse(text=retry_page_html, url="https://idp.ugr.es/stale")

    fresh_login_html = """
    <html>
      <form action="https://idp.ugr.es/loginuserpass" method="post">
        <input type="hidden" name="AuthState" value="_fresh_state" />
      </form>
    </html>
    """
    resp_fresh = MockResponse(text=fresh_login_html, url="https://idp.ugr.es/retry_flow")

    saml_assertion_html = """
    <form action="https://pradogrado2627.ugr.es/saml2-acs.php" method="post">
      <input type="hidden" name="SAMLResponse" value="valid_saml_token" />
    </form>
    """
    resp2 = MockResponse(text=saml_assertion_html, url="https://idp.ugr.es/loginuserpass")
    resp3 = MockResponse(text="<div class='usermenu'>Área personal</div>logout.php?sesskey=x", url="https://pradogrado2627.ugr.es/my/")

    def mock_get(url, *args, **kwargs):
        if "login.php" in url:
            return resp1_stale
        if "retry_flow" in url:
            return resp_fresh
        if "/my/" in url:
            return resp3
        return MockResponse("Not found", 404)

    def mock_post(url, *args, **kwargs):
        if "loginuserpass" in url:
            return resp2
        if "saml2-acs.php" in url:
            return resp3
        return MockResponse("Not found", 404)

    with patch("requests.Session.get", side_effect=mock_get), \
         patch("requests.Session.post", side_effect=mock_post):
        authed = driver.login("student@correo.ugr.es", "correct_pass")
        assert authed is not None


def test_saml_invalid_credentials_error(tmp_path):
    mgr = MoodleSessionManager(session_path=tmp_path / "session.json")
    driver = UgrSamlDriver(session_manager=mgr)

    idp_html = """
    <form action="https://idp.ugr.es/loginuserpass" method="post">
      <input type="hidden" name="AuthState" value="_state" />
    </form>
    """
    resp1 = MockResponse(text=idp_html, url="https://idp.ugr.es/loginuserpass")

    error_html = """
    <html>
      <div class="error">Usuario o contraseña incorrectos. Por favor inténtelo de nuevo.</div>
    </html>
    """
    resp2_err = MockResponse(text=error_html, url="https://idp.ugr.es/loginuserpass")

    with patch("requests.Session.get", return_value=resp1), \
         patch("requests.Session.post", return_value=resp2_err):
        with pytest.raises(InvalidCredentialsError) as exc_info:
            driver.login("student@correo.ugr.es", "wrong_pass")
        assert "Usuario o contraseña incorrectos" in str(exc_info.value)


def test_saml_account_locked_error(tmp_path):
    mgr = MoodleSessionManager(session_path=tmp_path / "session.json")
    driver = UgrSamlDriver(session_manager=mgr)

    idp_html = "<form action='https://idp.ugr.es/loginuserpass' method='post'><input type='hidden' name='AuthState' value='1'/></form>"
    resp1 = MockResponse(text=idp_html, url="https://idp.ugr.es/loginuserpass")

    locked_html = "<div class='error'>Cuenta bloqueada. Intentos superados. Contacte con el soporte técnico.</div>"
    resp2_locked = MockResponse(text=locked_html, url="https://idp.ugr.es/loginuserpass")

    with patch("requests.Session.get", return_value=resp1), \
         patch("requests.Session.post", return_value=resp2_locked):
        with pytest.raises(AccountLockedError):
            driver.login("student@correo.ugr.es", "locked_account_pass")


def test_saml_password_expired_error(tmp_path):
    mgr = MoodleSessionManager(session_path=tmp_path / "session.json")
    driver = UgrSamlDriver(session_manager=mgr)

    idp_html = "<form action='https://idp.ugr.es/loginuserpass' method='post'><input type='hidden' name='AuthState' value='1'/></form>"
    resp1 = MockResponse(text=idp_html, url="https://idp.ugr.es/loginuserpass")

    expired_html = "<div class='error'>Su contraseña está caducada. Debe realizar un cambio de contraseña.</div>"
    resp2_expired = MockResponse(text=expired_html, url="https://idp.ugr.es/loginuserpass")

    with patch("requests.Session.get", return_value=resp1), \
         patch("requests.Session.post", return_value=resp2_expired):
        with pytest.raises(PasswordExpiredError):
            driver.login("student@correo.ugr.es", "expired_pass")


def test_saml_empty_credentials_rejected():
    driver = UgrSamlDriver()
    with pytest.raises(InvalidCredentialsError):
        driver.login("", "password")
    with pytest.raises(InvalidCredentialsError):
        driver.login("user", "")
