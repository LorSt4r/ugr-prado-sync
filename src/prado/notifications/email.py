"""
SMTP Email Notifications for PradoOS.

Supports:
- Standard STARTTLS (e.g. port 587) and implicit SSL (e.g. port 465)
- Multipart plain text and HTML emails
- Institutional UGR SMTP (smtp.ugr.es) and external mail relays
"""

from __future__ import annotations

from dataclasses import dataclass, field
import email.message
import smtplib
from typing import List, Optional

from prado.notifications.webhooks import NotificationResult


@dataclass
class SmtpConfig:
    """Configuration for SMTP email alerts."""
    host: str = "smtp.ugr.es"
    port: int = 587
    username: Optional[str] = None
    password: Optional[str] = None
    use_tls: bool = True
    use_ssl: bool = False
    from_address: Optional[str] = None
    to_addresses: List[str] = field(default_factory=list)
    timeout_seconds: float = 15.0


class SmtpEmailSender:
    """Dispatches email notifications using standard smtplib."""

    def __init__(self, config: SmtpConfig):
        self.config = config

    def send_email(
        self,
        subject: str,
        text_body: str,
        html_body: Optional[str] = None,
        to_addresses: Optional[List[str]] = None,
    ) -> NotificationResult:
        recipients = to_addresses or self.config.to_addresses
        if not recipients:
            return NotificationResult(
                channel="email",
                success=False,
                message="No recipient addresses configured",
            )

        from_addr = self.config.from_address or self.config.username or "prado@ugr.es"

        try:
            clean_subject = " ".join((subject or "").splitlines()).strip()
            clean_from = " ".join(from_addr.splitlines()).strip()
            clean_recipients = [" ".join(r.splitlines()).strip() for r in recipients if r]
            msg = email.message.EmailMessage()
            msg["Subject"] = clean_subject
            msg["From"] = clean_from
            msg["To"] = ", ".join(clean_recipients)
            msg.set_content(text_body)

            if html_body:
                msg.add_alternative(html_body, subtype="html")

            if self.config.use_ssl:
                server = smtplib.SMTP_SSL(
                    self.config.host,
                    self.config.port,
                    timeout=self.config.timeout_seconds,
                )
            else:
                server = smtplib.SMTP(
                    self.config.host,
                    self.config.port,
                    timeout=self.config.timeout_seconds,
                )
                if self.config.use_tls:
                    server.ehlo()
                    server.starttls()
                    server.ehlo()

            with server:
                if self.config.username and self.config.password:
                    server.login(self.config.username, self.config.password)
                server.send_message(msg)

            return NotificationResult(
                channel="email",
                success=True,
                message=f"Email sent to {len(clean_recipients)} recipient(s)",
            )
        except Exception as e:
            return NotificationResult(
                channel="email",
                success=False,
                message="Failed to send SMTP email",
                error=str(e),
            )
