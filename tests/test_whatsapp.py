import base64

import httpx
import pytest

from screening_agent.channels.whatsapp import OutboundNotConfiguredError, TwilioWhatsAppSender
from screening_agent.config import settings


def make_sender(content_sid: str | None = None, status: int = 201):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, json={"sid": "SM1"})

    sender = TwilioWhatsAppSender(
        "AC123",
        "SK456",
        "secret",
        "whatsapp:+14155238886",
        content_sid,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    return sender, requests


def form_of(request: httpx.Request) -> dict[str, str]:
    return dict(httpx.QueryParams(request.content.decode()))


def test_send_text_posts_whatsapp_addressed_form_with_api_key_auth():
    sender, requests = make_sender()
    sender.send_text("+34600", "¿Sigues ahí?")
    request = requests[0]
    assert request.url.path == "/2010-04-01/Accounts/AC123/Messages.json"
    assert request.headers["authorization"] == "Basic " + base64.b64encode(b"SK456:secret").decode()
    assert form_of(request) == {
        "From": "whatsapp:+14155238886",
        "To": "whatsapp:+34600",
        "Body": "¿Sigues ahí?",
    }


def test_opener_uses_content_template_when_configured():
    sender, requests = make_sender("HX42")
    sender.send_opener("+34600", "hola")
    form = form_of(requests[0])
    assert form["ContentSid"] == "HX42"
    assert "Body" not in form


def test_opener_sends_text_without_template():
    sender, requests = make_sender()
    sender.send_opener("+34600", "hola")
    assert form_of(requests[0])["Body"] == "hola"


def test_http_error_raises():
    sender, _ = make_sender(status=401)
    with pytest.raises(httpx.HTTPStatusError):
        sender.send_text("+34600", "x")


def test_from_settings_names_every_missing_outbound_setting(monkeypatch):
    monkeypatch.setattr(settings, "twilio_account_sid", "AC123")
    monkeypatch.setattr(settings, "twilio_whatsapp_from", "+14155238886")
    with pytest.raises(OutboundNotConfiguredError) as error:
        TwilioWhatsAppSender.from_settings()
    assert "SCREENING_TWILIO_API_KEY_SID" in str(error.value)
    assert "SCREENING_TWILIO_API_KEY_SECRET" in str(error.value)
    assert "SCREENING_TWILIO_ACCOUNT_SID" not in str(error.value)
