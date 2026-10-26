import base64
import hashlib
import hmac
from collections.abc import Mapping
from urllib.parse import urlsplit, urlunsplit
from xml.sax.saxutils import escape

import httpx
from pydantic import BaseModel

from screening_agent.config import settings

WHATSAPP_PREFIX = "whatsapp:"


class InboundWhatsAppMessage(BaseModel):
    """Normalised shape the webhook hands to the engine, built from Twilio's form POST."""

    message_id: str
    from_phone: str
    text: str

    @classmethod
    def from_twilio_form(cls, form: Mapping[str, str]) -> "InboundWhatsAppMessage":
        return cls(
            message_id=form["MessageSid"],
            from_phone=form["From"].removeprefix(WHATSAPP_PREFIX),
            text=form.get("Body", ""),
        )


def verify_twilio_signature(
    url: str, params: Mapping[str, str], header_value: str | None, auth_token: str
) -> bool:
    """HMAC-SHA1 over the URL plus sorted name+value params, base64. Both default-port URL variants
    are accepted because proxies add or strip the port, as Twilio's own validator does."""
    if not header_value:
        return False
    return any(
        hmac.compare_digest(_twilio_signature(variant, params, auth_token), header_value)
        for variant in _port_variants(url)
    )


def twiml_reply(text: str) -> str:
    """Returning TwiML from the webhook is how Twilio sends the reply back to the sender."""
    body = f"<Message>{escape(text)}</Message>" if text else ""
    return f'<?xml version="1.0" encoding="UTF-8"?><Response>{body}</Response>'


def _twilio_signature(url: str, params: Mapping[str, str], auth_token: str) -> str:
    payload = url + "".join(name + params[name] for name in sorted(params))
    digest = hmac.new(auth_token.encode(), payload.encode(), digestmod=hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def _port_variants(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.port is not None:
        without = urlunsplit(parts._replace(netloc=host))
        return url, without
    default_port = 443 if parts.scheme == "https" else 80
    with_port = urlunsplit(parts._replace(netloc=f"{host}:{default_port}"))
    return url, with_port


class OutboundNotConfiguredError(RuntimeError):
    pass


class TwilioWhatsAppSender:
    """Nudges go as plain text inside the 24h window; the opener uses the approved content template
    when one is configured, since only templates are deliverable outside the window."""

    MESSAGES_URL = "https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"

    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        from_phone: str,
        opener_content_sid: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.account_sid = account_sid
        self.from_phone = from_phone.removeprefix(WHATSAPP_PREFIX)
        self.opener_content_sid = opener_content_sid
        self.client = client or httpx.Client(timeout=10.0)
        self._auth = (account_sid, auth_token)

    @classmethod
    def from_settings(cls) -> "TwilioWhatsAppSender":
        missing = [
            name
            for name, value in (
                ("SCREENING_TWILIO_ACCOUNT_SID", settings.twilio_account_sid),
                ("SCREENING_TWILIO_AUTH_TOKEN", settings.twilio_auth_token),
                ("SCREENING_TWILIO_WHATSAPP_FROM", settings.twilio_whatsapp_from),
            )
            if not value
        ]
        if missing:
            raise OutboundNotConfiguredError(f"missing {', '.join(missing)}")
        return cls(
            settings.twilio_account_sid,  # type: ignore[arg-type]
            settings.twilio_auth_token,  # type: ignore[arg-type]
            settings.twilio_whatsapp_from,  # type: ignore[arg-type]
            settings.twilio_opener_content_sid,
        )

    def send_text(self, candidate_id: str, text: str) -> None:
        self._post(candidate_id, {"Body": text})

    def send_opener(self, candidate_id: str, text: str) -> None:
        if self.opener_content_sid:
            self._post(candidate_id, {"ContentSid": self.opener_content_sid})
        else:
            self._post(candidate_id, {"Body": text})

    def _post(self, candidate_id: str, content: Mapping[str, str]) -> None:
        form = {
            "From": f"{WHATSAPP_PREFIX}{self.from_phone}",
            "To": f"{WHATSAPP_PREFIX}{candidate_id}",
            **content,
        }
        response = self.client.post(
            self.MESSAGES_URL.format(account_sid=self.account_sid), data=form, auth=self._auth
        )
        response.raise_for_status()
