"""Mailpit-compatible MFA email delivery, intentionally outside DB transactions."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Protocol

from app.core.settings import Settings


class MfaMailer(Protocol):
    def send_email_otp(self, *, recipient: str, code: str) -> None: ...


class SmtpMfaMailer:
    """Deliver the v1 four-digit email OTP without logging its content."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def send_email_otp(self, *, recipient: str, code: str) -> None:
        message = EmailMessage()
        message["From"] = self._settings.smtp_from
        message["To"] = recipient
        message["Subject"] = "Sentinel Auth verification code"
        message.set_content(f"Your Sentinel Auth verification code is: {code}\nIt expires in 60 seconds.")
        with smtplib.SMTP(
            self._settings.smtp_host,
            self._settings.smtp_port,
            timeout=self._settings.smtp_timeout_seconds,
        ) as client:
            client.send_message(message)
