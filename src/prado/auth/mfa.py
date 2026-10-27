"""
3-Tier Multi-Factor Authentication (MFA) resolver for PradoOS.

Tiers:
- Tier 1: 30-day persistent MFA_TOKEN_* cookie reuse (handled via SessionManager).
- Tier 2a: Cross-platform imaplib.IMAP4_SSL auto-fetch for email verification codes.
- Tier 2b: macOS Apple Mail fallback via osascript.
- Tier 3: Interactive terminal TTY 6-digit prompt, or non-interactive --json error protocol (exit code 2).
"""

from __future__ import annotations

import email
from email.header import decode_header
import imaplib
import os
import re
import subprocess
import sys
import time
from typing import Any, Dict, Optional, Tuple

from bs4 import BeautifulSoup
import requests

from prado.config import MfaConfig
from prado.exceptions import MfaRequiredError, MfaVerificationFailedError, NetworkError


def decode_mime_header(header_value: Optional[str]) -> str:
    """Decodes MIME encoded header strings to clean UTF-8 text."""
    if not header_value:
        return ""
    decoded_fragments = decode_header(header_value)
    text_parts = []
    for fragment, charset in decoded_fragments:
        if isinstance(fragment, bytes):
            charset = charset or "utf-8"
            try:
                text_parts.append(fragment.decode(charset, errors="replace"))
            except LookupError:
                text_parts.append(fragment.decode("utf-8", errors="replace"))
        else:
            text_parts.append(str(fragment))
    return "".join(text_parts)


class MfaResolver:
    """
    Orchestrates the 3-tier resolution of Moodle email verification codes.
    """

    def __init__(
        self,
        mfa_config: Optional[MfaConfig] = None,
        interactive: bool = True,
        json_mode: bool = False,
        agent_code: Optional[str] = None,
        gui_mode: bool = False,
    ) -> None:
        self.config = mfa_config or MfaConfig()
        self.interactive = interactive
        self.json_mode = json_mode
        self.agent_code = agent_code
        self.gui_mode = gui_mode

    def resolve_code(
        self,
        imap_password: Optional[str] = None,
        start_time: Optional[float] = None,
    ) -> str:
        """
        Resolves the 6-digit MFA code through the tiered cascade:
        1. Explicit agent code / PRADO_MFA_CODE environment variable
        2. Tier 2a: IMAP SSL auto-fetch (if enabled)
        3. Tier 2b: Apple Mail on macOS (if enabled and on Darwin)
        4. Tier 3: Interactive terminal prompt (if TTY) or MfaRequiredError (agent/json)
        """
        # Explicit code provided via CLI argument or environment variable
        explicit_code = self.agent_code or os.environ.get("PRADO_MFA_CODE")
        if explicit_code:
            clean = explicit_code.strip()
            if re.match(r"^[0-9]{6}$", clean):
                return clean

        # Tier 2a: IMAP auto-fetch
        if self.config.imap_enabled:
            username = self.config.imap_username or os.environ.get("PRADO_IMAP_USERNAME") or os.environ.get("PRADO_USERNAME")
            password = imap_password or os.environ.get("PRADO_IMAP_PASSWORD") or os.environ.get("PRADO_PASSWORD")
            if username and password:
                code = self.fetch_from_imap(
                    host=self.config.imap_host,
                    port=self.config.imap_port,
                    ssl=self.config.imap_ssl,
                    username=username,
                    password=password,
                    folder=self.config.imap_folder,
                    timeout_seconds=self.config.imap_timeout,
                    poll_interval_seconds=self.config.imap_poll_interval,
                    start_time=start_time,
                )
                if code:
                    return code

        # Tier 2b: macOS Apple Mail fallback
        if self.config.apple_mail_enabled and sys.platform == "darwin":
            code = self.fetch_from_apple_mail(
                timeout_seconds=min(self.config.imap_timeout, 45),
                poll_interval_seconds=self.config.imap_poll_interval,
                account_name=self.config.apple_mail_account,
                start_time=start_time,
            )
            if code:
                return code

        # Tier 3: GUI Dialog, Interactive TTY Prompt, or Non-interactive Agent Protocol
        if self.gui_mode:
            from prado.auth.credentials import prompt_gui_input

            gui_code = prompt_gui_input(
                prompt="Enter the 6-digit verification code sent to your institutional email (@correo.ugr.es):",
                title="PradoOS — Two-Factor Verification (MFA)",
                hidden=False,
            )
            if gui_code:
                m_gui = re.search(r"\b([0-9]{6})\b", gui_code.strip())
                if m_gui:
                    return m_gui.group(1)

        is_tty = hasattr(sys.stdin, "isatty") and sys.stdin.isatty()
        if not self.interactive or self.json_mode or not is_tty:
            raise MfaRequiredError(
                prompt="Two-factor verification code required to authenticate with PRADO.",
                factor="email",
                tier=3,
            )

        return self.prompt_user_interactive()

    def fetch_from_imap(
        self,
        host: str = "imap.ugr.es",
        port: int = 993,
        ssl: bool = True,
        username: str = "",
        password: str = "",
        folder: str = "INBOX",
        timeout_seconds: int = 60,
        poll_interval_seconds: int = 3,
        start_time: Optional[float] = None,
    ) -> Optional[str]:
        """
        Polls IMAP4_SSL server for recent verification email (last 300 seconds).
        Extracts 6-digit verification code from plain text or HTML body.
        """
        deadline = time.time() + timeout_seconds
        min_timestamp = (start_time or time.time()) - 300

        while time.time() < deadline:
            try:
                if ssl:
                    client = imaplib.IMAP4_SSL(host, port)
                else:
                    client = imaplib.IMAP4(host, port)

                client.login(username, password)
                client.select(folder, readonly=True)

                status, data = client.search(None, "ALL")
                if status == "OK" and data and data[0]:
                    msg_ids = data[0].split()
                    # Inspect the latest 10 messages in reverse order
                    for msg_id in reversed(msg_ids[-10:]):
                        fetch_status, msg_data = client.fetch(msg_id, "(RFC822)")
                        if fetch_status != "OK" or not msg_data or not msg_data[0]:
                            continue

                        raw_email = msg_data[0][1]
                        if not isinstance(raw_email, bytes):
                            continue

                        msg = email.message_from_bytes(raw_email)
                        subject = decode_mime_header(msg.get("Subject", "")).lower()

                        # Check subject relevance
                        if not any(k in subject for k in ("código", "codigo", "verificación", "verificacion", "verification", "prado")):
                            continue

                        # Check date header
                        date_str = msg.get("Date")
                        if date_str:
                            try:
                                msg_dt = email.utils.parsedate_to_datetime(date_str)
                                if msg_dt.timestamp() < min_timestamp:
                                    continue
                            except Exception:
                                pass

                        # Extract message body
                        body_text = ""
                        if msg.is_multipart():
                            for part in msg.walk():
                                content_type = part.get_content_type()
                                if content_type in ("text/plain", "text/html"):
                                    payload = part.get_payload(decode=True)
                                    if payload:
                                        body_text += payload.decode("utf-8", errors="replace") + "\n"
                        else:
                            payload = msg.get_payload(decode=True)
                            if payload:
                                body_text = payload.decode("utf-8", errors="replace")

                        # Search for 6-digit code
                        match = re.search(r"\b([0-9]{6})\b", body_text)
                        if match:
                            code = match.group(1)
                            client.logout()
                            return code

                client.logout()
            except Exception:
                pass

            time.sleep(poll_interval_seconds)

        return None

    def fetch_from_apple_mail(
        self,
        timeout_seconds: int = 45,
        poll_interval_seconds: int = 3,
        account_name: Optional[str] = None,
        start_time: Optional[float] = None,
    ) -> Optional[str]:
        """
        Extracts 6-digit verification code from macOS Apple Mail using AppleScript osascript.
        """
        if sys.platform != "darwin":
            return None

        deadline = time.time() + timeout_seconds
        acc_clause = ""
        if account_name and account_name != "auto":
            acc_clause = f'set acc to account "{account_name}"\nset inb to mailbox "INBOX" of acc'
        else:
            acc_clause = 'set inb to inbox'

        script = f"""
        tell application "Mail"
            try
                check for new mail
            end try
            delay 0.5
            {acc_clause}
            set cutoff to (current date) - 300
            repeat with m in (messages 1 thru 15 of inb)
                set subj to (subject of m)
                if subj contains "código de verificación" or subj contains "codigo de verificacion" or subj contains "verification code" then
                    if (date received of m) > cutoff then
                        return (content of m)
                    end if
                end if
            end repeat
            return ""
        end tell
        """

        while time.time() < deadline:
            try:
                proc = subprocess.run(
                    ["osascript", "-e", script],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if proc.returncode == 0 and proc.stdout:
                    match = re.search(r"\b([0-9]{6})\b", proc.stdout)
                    if match:
                        return match.group(1)
            except Exception:
                pass

            time.sleep(poll_interval_seconds)

        return None

    def prompt_user_interactive(self) -> str:
        """
        Prompts user on the interactive terminal TTY for the 6-digit code.
        """
        sys.stderr.write("\n[PradoOS MFA] Enter the 6-digit verification code sent to your email: ")
        sys.stderr.flush()
        code = sys.stdin.readline().strip()
        if not re.match(r"^[0-9]{6}$", code):
            raise MfaVerificationFailedError(
                f"Invalid verification code format: '{code}'. Expected 6 numeric digits."
            )
        return code

    @classmethod
    def extract_mfa_form_details(cls, html: str, current_url: str) -> Tuple[str, str]:
        """
        Extracts the MFA action URL and sesskey token from Moodle's /admin/tool/mfa/auth.php page.
        """
        soup = BeautifulSoup(html, "html.parser")
        sesskey_input = soup.find("input", {"name": "sesskey"})
        if not sesskey_input or not sesskey_input.get("value"):
            raise MfaVerificationFailedError("Could not find required 'sesskey' in Moodle MFA form.")

        sesskey = sesskey_input["value"]

        form = soup.find("form", action=lambda a: a and "admin/tool/mfa" in a)
        if form and form.get("action"):
            action = form["action"]
            if not action.startswith("http"):
                mfa_url = requests.compat.urljoin(current_url, action)
            else:
                mfa_url = action
        else:
            mfa_url = current_url

        return mfa_url, sesskey

    def submit_mfa_code(
        self,
        session: requests.Session,
        mfa_url: str,
        sesskey: str,
        code: str,
        trust_device: bool = True,
    ) -> requests.Response:
        """
        Submits the 6-digit verification code to Moodle MFA auth.php with 30-day device trust.
        """
        payload = {
            "factor": "email",
            "sesskey": sesskey,
            "_qf__tool_mfa_local_form_login_form": "1",
            "verificationcode": code.strip(),
            "factor_token_trust": "1" if trust_device else "0",
            "submitbutton": "Continuar",
        }

        try:
            resp = session.post(mfa_url, data=payload, timeout=15, allow_redirects=True)
        except requests.RequestException as e:
            raise NetworkError(f"Network error during MFA code submission: {e}") from e
        resp_url = resp.url.lower()

        if "admin/tool/mfa" in resp_url:
            soup = BeautifulSoup(resp.text, "html.parser")
            err_box = soup.find(["div", "p", "span"], class_=lambda c: c and ("error" in c.lower() or "alert-danger" in c.lower()))
            err_msg = err_box.get_text(" ", strip=True) if err_box else "Verification code rejected or expired."
            raise MfaVerificationFailedError(f"MFA verification failed: {err_msg}")

        return resp
