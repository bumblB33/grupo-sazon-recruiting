import base64
import hashlib
import hmac
from collections.abc import Mapping
from urllib.parse import urlsplit, urlunsplit
from xml.sax.saxutils import escape

from pydantic import BaseModel

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
    """Twilio signs the webhook URL followed by every POST param as name+value in sorted order,
    HMAC-SHA1 with the account auth token, base64. Proxies may add or strip the default port,
    so both URL variants are accepted, as Twilio's own validator does."""
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
