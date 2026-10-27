"""
Headless SimpleSAMLphp Single Sign-On (SSO) driver for PRADO UGR.

Executes the automated SAML 2.0 Web Browser SSO profile:
1. SP Login Initiation: GET /auth/saml2/login.php -> Redirect to IdP
2. IdP Form Handling: Extraction of AuthState and retryURL resolution
3. Credential Submission: POST to idp.ugr.es loginuserpass
4. SAML Assertion Extraction: Parsing of Base64 SAMLResponse & RelayState
5. ACS Consumer Submission: POST to SP saml2-acs.php endpoint
6. 3-Tier MFA Interception: Seamless handling of /admin/tool/mfa/auth.php
7. Session Validation & Persistence: Verification against /my/ and 0600 storage
"""

from __future__ import annotations

import time
from typing import Optional, Tuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import requests

from prado.auth.credentials import CredentialStore
from prado.auth.mfa import MfaResolver
from prado.auth.session import MoodleSessionManager
from prado.config import get_default_moodle_url
from prado.exceptions import (
    AccountLockedError,
    AuthError,
    InvalidCredentialsError,
    PasswordExpiredError,
)


class UgrSamlDriver:
    """
    Automates headless SimpleSAMLphp SSO authentication against UGR IdP and PRADO SP.
    """

    DEFAULT_USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/129.0.0.0 Safari/537.36"
    )

    def __init__(
        self,
        base_url: Optional[str] = None,
        session_manager: Optional[MoodleSessionManager] = None,
        mfa_resolver: Optional[MfaResolver] = None,
        credential_store: Optional[CredentialStore] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        self.base_url = (base_url or get_default_moodle_url()).rstrip("/")
        self.session_manager = session_manager or MoodleSessionManager(base_url=self.base_url)
        self.mfa_resolver = mfa_resolver or MfaResolver()
        self.credential_store = credential_store or CredentialStore()
        self.user_agent = user_agent or self.DEFAULT_USER_AGENT

    def login(
        self,
        username: str,
        password: str,
        preserve_trust_tokens: bool = True,
    ) -> requests.Session:
        """
        Executes full headless SAML SSO handshake and resolves MFA if triggered.
        Returns an authenticated requests.Session.
        """
        if not username or not password:
            raise InvalidCredentialsError("Username and password must not be empty.")

        login_start_time = time.time()
        session = requests.Session()
        session.headers.update({"User-Agent": self.user_agent})

        # Inject preserved 30-day device trust tokens before initiating login
        if preserve_trust_tokens:
            self.session_manager.inject_preserved_tokens(session)

        # Step 1: Initiate SAML login by requesting SP login.php
        init_url = f"{self.base_url}/auth/saml2/login.php"
        try:
            resp1 = session.get(init_url, timeout=15, allow_redirects=True)
        except requests.RequestException as e:
            raise AuthError(f"Failed to connect to SP login endpoint {init_url}: {e}") from e

        # If already logged in (e.g. valid session or device trust was sufficient immediately)
        if "idp.ugr.es" not in resp1.url and ("Área personal" in resp1.text or "Mis cursos" in resp1.text):
            if self.session_manager.is_session_valid(session, self.base_url):
                self.session_manager.save_session(session)
                return session

        # Step 2: Handle IdP Login Form and retryURL
        soup1 = BeautifulSoup(resp1.text, "html.parser")
        form1 = soup1.find("form", action=lambda a: a and "loginuserpass" in a)

        if not form1:
            retry_in = soup1.find("input", {"name": "retryURL"})
            if retry_in and retry_in.get("value"):
                retry_url = retry_in["value"]
                if not retry_url.startswith("http"):
                    retry_url = urljoin(resp1.url, retry_url)
                try:
                    resp1 = session.get(retry_url, timeout=15, allow_redirects=True)
                    soup1 = BeautifulSoup(resp1.text, "html.parser")
                    form1 = soup1.find("form", action=lambda a: a and "loginuserpass" in a)
                except requests.RequestException as e:
                    raise AuthError(f"Failed to follow IdP retryURL: {e}") from e

        if not form1:
            raise AuthError(
                f"Could not locate SimpleSAMLphp login form on IdP page. Current URL: {resp1.url}"
            )

        post_url = form1.get("action", "")
        if not post_url.startswith("http"):
            post_url = urljoin(resp1.url, post_url)

        # Collect hidden inputs (especially AuthState)
        post_data = {
            "username": username,
            "password": password,
        }
        for inp in form1.find_all("input", type="hidden"):
            name = inp.get("name")
            value = inp.get("value")
            if name and value is not None:
                post_data[name] = value

        # Step 3: POST credentials to IdP
        try:
            resp2 = session.post(post_url, data=post_data, timeout=15, allow_redirects=True)
        except requests.RequestException as e:
            raise AuthError(f"Failed to submit credentials to IdP: {e}") from e

        # Step 4: Validate IdP response for errors
        soup2 = BeautifulSoup(resp2.text, "html.parser")
        err_box = soup2.find(
            ["div", "p", "span"],
            class_=lambda c: c and ("error" in c.lower() or "alert-danger" in c.lower()),
        )
        if err_box:
            err_msg = err_box.get_text(" ", strip=True)
            err_lower = err_msg.lower()
            if any(k in err_lower for k in ("bloqueada", "intentos superados", "contacte")):
                raise AccountLockedError(f"UGR account is locked: {err_msg}")
            if any(k in err_lower for k in ("caducada", "cambio de contraseña")):
                raise PasswordExpiredError(f"UGR password has expired: {err_msg}")
            if any(k in err_lower for k in ("incorrect", "usuario", "contraseña", "credenciales")):
                raise InvalidCredentialsError(f"Invalid UGR credentials: {err_msg}")
            raise InvalidCredentialsError(f"IdP authentication rejected: {err_msg}")

        # Step 5: Extract SAMLResponse and RelayState from assertion form
        saml_form = soup2.find(
            "form",
            action=lambda a: a and ("saml2-acs.php" in a or "prado" in a or self.base_url in a),
        )
        saml_resp_in = soup2.find("input", {"name": "SAMLResponse"})

        if not saml_form or not saml_resp_in:
            raise AuthError(
                f"SAML assertion form or SAMLResponse token not found after IdP login. Current URL: {resp2.url}"
            )

        acs_url = saml_form.get("action", "")
        if not acs_url.startswith("http"):
            acs_url = urljoin(resp2.url, acs_url)

        saml_payload = {
            "SAMLResponse": saml_resp_in.get("value", "")
        }
        relay_in = soup2.find("input", {"name": "RelayState"})
        if relay_in and relay_in.get("value"):
            saml_payload["RelayState"] = relay_in["value"]

        # Step 6: POST SAMLResponse to SP Assertion Consumer Service (ACS)
        try:
            resp3 = session.post(acs_url, data=saml_payload, timeout=20, allow_redirects=True)
        except requests.RequestException as e:
            raise AuthError(f"Failed to submit SAML assertion to SP ACS endpoint: {e}") from e

        # Step 7: Check if 2-Step Verification (MFA) was triggered
        resp3_url = resp3.url.lower()
        if "admin/tool/mfa" in resp3_url or "verificación en 2 pasos" in resp3.text.lower():
            mfa_url, sesskey = MfaResolver.extract_mfa_form_details(resp3.text, resp3.url)

            # Retrieve IMAP password if needed for auto-fetch
            imap_pwd = None
            try:
                _, imap_pwd = self.credential_store.get_imap_credentials(default_username=username)
            except Exception:
                imap_pwd = password

            # Resolve 6-digit MFA code
            mfa_code = self.mfa_resolver.resolve_code(
                imap_password=imap_pwd,
                start_time=login_start_time,
            )

            # Submit code with 30-day trust
            self.mfa_resolver.submit_mfa_code(
                session=session,
                mfa_url=mfa_url,
                sesskey=sesskey,
                code=mfa_code,
                trust_device=True,
            )

        # Step 8: Validate session validity on Moodle
        if self.session_manager.is_session_valid(session, self.base_url):
            self.session_manager.save_session(session)
            return session

        raise AuthError("SAML SSO handshake succeeded, but session validation on PRADO failed.")

    def authenticate(self, default_username: Optional[str] = None) -> requests.Session:
        """
        High-level entry point:
        1. Checks if existing session is already valid.
        2. If not, retrieves credentials and executes full login.
        """
        # Try existing session first
        if self.session_manager.load_session():
            if self.session_manager.is_session_valid(self.session_manager.session, self.base_url):
                return self.session_manager.session

        # Re-authenticate using stored credentials
        username, password = self.credential_store.get_sso_credentials(default_username=default_username)
        return self.login(username=username, password=password, preserve_trust_tokens=True)
