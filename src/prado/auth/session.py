"""
Session and cookie manager for PradoOS Moodle integration.

Persists Moodle session cookies and 30-day device trust tokens (MFA_TOKEN_*)
inside the OS-protected configuration directory (~/.config/prado/session.json)
with strict mode 0600 file permissions.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from prado.config import get_config_file, get_default_moodle_url, get_session_file, write_secure_file
from prado.exceptions import AuthenticationRequiredError


class MoodleSessionManager:
    """
    Manages session cookie persistence, health checks, and MFA token injection.
    """

    DEFAULT_USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/129.0.0.0 Safari/537.36"
    )

    def __init__(
        self,
        session_path: Optional[Path] = None,
        base_url: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        self.session_path = session_path or get_session_file()
        self.base_url = (base_url or get_default_moodle_url()).rstrip("/")
        self.user_agent = user_agent or self.DEFAULT_USER_AGENT
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.user_agent})

    def load_session(self) -> bool:
        """
        Loads saved cookies from session.json into self.session.cookies.
        Returns True if at least one cookie was successfully restored, False otherwise.
        """
        if not self.session_path.exists():
            return False

        try:
            with open(self.session_path, "r", encoding="utf-8") as f:
                cookies_data = json.load(f)

            if not isinstance(cookies_data, list) or not cookies_data:
                return False

            now = time.time()
            loaded_count = 0
            for item in cookies_data:
                if not isinstance(item, dict) or "name" not in item or "value" not in item:
                    continue

                # Filter out expired cookies if expires timestamp is present
                expires = item.get("expires")
                if expires is not None and expires < now:
                    continue

                self.session.cookies.set(
                    item["name"],
                    item["value"],
                    domain=item.get("domain", ""),
                    path=item.get("path", "/"),
                    secure=bool(item.get("secure", False)),
                )
                loaded_count += 1

            return loaded_count > 0
        except (json.JSONDecodeError, OSError):
            return False

    def save_session(self, session: Optional[requests.Session] = None) -> None:
        """
        Serializes current cookies to session.json with mode 0600.
        """
        target_session = session or self.session
        cookies_list: List[Dict[str, Any]] = []

        for cookie in target_session.cookies:
            cookies_list.append(
                {
                    "name": cookie.name,
                    "value": cookie.value,
                    "domain": cookie.domain,
                    "path": cookie.path,
                    "secure": bool(cookie.secure),
                    "expires": cookie.expires,
                }
            )

        content = json.dumps(cookies_list, indent=2)
        write_secure_file(self.session_path, content, mode=0o600)

    def clear_session(self) -> None:
        """Removes the session.json file and clears in-memory cookies."""
        if self.session_path.exists():
            try:
                self.session_path.unlink()
            except OSError:
                pass
        self.session.cookies.clear()

    def extract_mfa_tokens(self) -> List[Dict[str, Any]]:
        """
        Extracts active MFA device trust tokens (MFA_TOKEN_*) and user identifiers (MOODLEID*).
        """
        tokens: List[Dict[str, Any]] = []
        now = time.time()

        # Check in-memory session cookies first
        for cookie in self.session.cookies:
            if cookie.name.startswith("MFA_TOKEN") or cookie.name.startswith("MOODLEID"):
                if cookie.expires is None or cookie.expires > now:
                    tokens.append(
                        {
                            "name": cookie.name,
                            "value": cookie.value,
                            "domain": cookie.domain,
                            "path": cookie.path,
                            "secure": bool(cookie.secure),
                            "expires": cookie.expires,
                        }
                    )

        # If none in memory, inspect stored session file
        if not tokens and self.session_path.exists():
            try:
                with open(self.session_path, "r", encoding="utf-8") as f:
                    stored = json.load(f)
                if isinstance(stored, list):
                    for item in stored:
                        name = item.get("name", "")
                        if name.startswith("MFA_TOKEN") or name.startswith("MOODLEID"):
                            expires = item.get("expires")
                            if expires is None or expires > now:
                                tokens.append(item)
            except Exception:
                pass

        return tokens

    def inject_preserved_tokens(self, target_session: requests.Session) -> None:
        """
        Injects preserved MFA_TOKEN_* and MOODLEID* tokens into target_session before authentication.
        """
        tokens = self.extract_mfa_tokens()
        for t in tokens:
            target_session.cookies.set(
                t["name"],
                t["value"],
                domain=t.get("domain", ""),
                path=t.get("path", "/"),
                secure=bool(t.get("secure", False)),
            )

    def is_session_valid(
        self,
        session: Optional[requests.Session] = None,
        base_url: Optional[str] = None,
        timeout: int = 10,
    ) -> bool:
        """
        Performs a lightweight GET request to {base_url}/my/ to verify if the session is authenticated.
        Returns True if authenticated without login or MFA redirects.
        """
        target_session = session or self.session
        url = f"{(base_url or self.base_url).rstrip('/')}/my/"

        try:
            resp = target_session.get(url, timeout=timeout, allow_redirects=True)
            if resp.status_code != 200:
                return False

            final_url = resp.url.lower()
            if "idp.ugr.es" in final_url or "admin/tool/mfa" in final_url:
                return False
            if "/login/" in final_url and "logout.php" not in final_url:
                return False

            html = resp.text
            valid_markers = [
                "logout.php?sesskey=",
                "class=\"usermenu\"",
                "Área personal",
                "Mis cursos",
                "usertext",
                "userbutton",
            ]
            if any(marker in html for marker in valid_markers):
                return True

            return False
        except requests.RequestException:
            return False

    def get_authenticated_session(self, base_url: Optional[str] = None) -> requests.Session:
        """
        Interface Contract for M1 ↔ M2.
        Returns an active requests.Session populated with authenticated cookies.
        Raises AuthenticationRequiredError if no valid session is found.
        """
        target_url = base_url or self.base_url
        if self.load_session() and self.is_session_valid(self.session, target_url):
            return self.session

        raise AuthenticationRequiredError(
            "No active authenticated Moodle session found. "
            "Please run 'prado auth' to establish a session."
        )
