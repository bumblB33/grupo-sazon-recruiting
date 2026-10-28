import sys
from typing import Protocol

import httpx

from screening_agent.config import settings


class EmailSender(Protocol):
    def send(self, to: str, subject: str, text: str) -> None: ...


class EmailNotConfiguredError(RuntimeError):
    pass


class EmailSendError(RuntimeError):
    pass


class SendGridEmailSender:
    """Twilio SendGrid Mail Send v3: https://www.twilio.com/docs/sendgrid/api-reference/mail-send/mail-send"""

    SEND_URL = "https://api.sendgrid.com/v3/mail/send"

    def __init__(self, api_key: str, from_email: str, client: httpx.Client | None = None) -> None:
        self.from_email = from_email
        self.client = client or httpx.Client(timeout=10.0)
        self._headers = {"Authorization": f"Bearer {api_key}"}

    @classmethod
    def from_settings(cls) -> "SendGridEmailSender":
        missing = [
            name
            for name, value in (
                ("SCREENING_SENDGRID_API_KEY", settings.sendgrid_api_key),
                ("SCREENING_LOGIN_EMAIL_FROM", settings.login_email_from),
            )
            if not value
        ]
        if missing:
            raise EmailNotConfiguredError(f"missing {', '.join(missing)}")
        return cls(
            settings.sendgrid_api_key.get_secret_value(),  # type: ignore[union-attr]
            settings.login_email_from,  # type: ignore[arg-type]
        )

    def send(self, to: str, subject: str, text: str) -> None:
        payload = {
            "personalizations": [{"to": [{"email": to}]}],
            "from": {"email": self.from_email},
            "subject": subject,
            "content": [{"type": "text/plain", "value": text}],
        }
        try:
            response = self.client.post(self.SEND_URL, json=payload, headers=self._headers)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise EmailSendError(f"SendGrid send failed: {exc}") from exc


class RedirectingEmailSender:
    """Delivers every email to one fixed address. The original recipient is named in the body."""

    def __init__(self, inner: EmailSender, redirect_to: str) -> None:
        self.inner = inner
        self.redirect_to = redirect_to

    def send(self, to: str, subject: str, text: str) -> None:
        self.inner.send(self.redirect_to, subject, f"Requested for {to}.\n\n{text}")


class LoggingEmailSender:
    """Dev mode without SendGrid: the login link goes to stderr, never to a log record that tracing exports."""

    def send(self, to: str, subject: str, text: str) -> None:
        print(f"email to {to}: {subject}\n{text}", file=sys.stderr)
