from fastapi.testclient import TestClient

from screening_agent.api import app as api
from screening_agent.api.deps import RECRUITER_COOKIE
from screening_agent.channels.whatsapp import _twilio_signature
from screening_agent.config import settings
from tests.conftest import FakeOutbound, screen_no_licence, twilio_form

WEBHOOK = "/webhook/whatsapp"


def signed_headers(client: TestClient, form: dict[str, str], token: str) -> dict[str, str]:
    url = str(client.base_url) + WEBHOOK
    return {"X-Twilio-Signature": _twilio_signature(url, form, token)}


def test_webhook_then_override_and_analytics(client):
    form = twilio_form("SM1", "+34600", "sí")
    first = client.post(WEBHOOK, data=form)
    assert first.headers["X-Screening-Outcome"] == "replied"
    assert first.headers["content-type"].startswith("application/xml")
    assert "<Message>" in first.text
    second = client.post(WEBHOOK, data=form)
    assert second.headers["X-Screening-Outcome"] == "duplicate"
    assert "<Message>" not in second.text
    assert client.get("/candidates").json()[0]["stage"] == "full_name"
    patched = client.patch("/candidates/+34600", json={"status": "qualified", "notes": "ok"}).json()
    assert patched["status"] == "qualified"
    assert client.get("/analytics").json()["by_status"] == {"qualified": 1}
    assert client.get("/candidates/nope").status_code == 404


def test_candidate_detail_has_transcript_and_events(client):
    client.post(WEBHOOK, data=twilio_form("SM1", "+34600", "sí"))
    client.patch("/candidates/+34600", json={"status": "qualified", "notes": "ok"})
    detail = client.get("/candidates/+34600").json()
    assert [(m["direction"], m["body"]) for m in detail["transcript"]] == [
        ("in", "sí"),
        ("out", "Hola"),
    ]
    assert [e["kind"] for e in detail["events"]] == ["recruiter_override"]
    assert detail["events"][0]["payload"] == {"status": "qualified", "notes": "ok"}


def test_terminal_turn_summarises_in_background(client):
    screen_no_licence(client, "+34601")
    assert client.get("/candidates/+34601").json()["summary"] == "summary"


def test_recruiter_routes_require_key_when_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "recruiter_api_key", "secret")
    assert client.get("/candidates").status_code == 401
    assert client.get("/candidates", headers={"x-api-key": "secret"}).status_code == 200
    client.cookies.set(RECRUITER_COOKIE, "secret")
    assert client.get("/candidates").status_code == 200


def test_recruiter_routes_fail_closed_without_key_outside_dev_mode(client, monkeypatch):
    monkeypatch.setattr(settings, "dev_mode", False)
    assert client.get("/candidates").status_code == 503


def test_webhook_requires_valid_twilio_signature_when_token_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "twilio_auth_token", "auth-token")
    form = twilio_form("SM1", "+34600", "sí")
    assert client.post(WEBHOOK, data=form).status_code == 401
    bad = signed_headers(client, form, "wrong-token")
    assert client.post(WEBHOOK, data=form, headers=bad).status_code == 401
    good = signed_headers(client, form, "auth-token")
    assert client.post(WEBHOOK, data=form, headers=good).status_code == 200


def test_webhook_signature_uses_configured_public_url(client, monkeypatch):
    monkeypatch.setattr(settings, "twilio_auth_token", "auth-token")
    monkeypatch.setattr(settings, "twilio_webhook_url", "https://demo.example.com/webhook/whatsapp")
    form = twilio_form("SM1", "+34600", "sí")
    signature = _twilio_signature("https://demo.example.com/webhook/whatsapp", form, "auth-token")
    response = client.post(WEBHOOK, data=form, headers={"X-Twilio-Signature": signature})
    assert response.status_code == 200


def test_webhook_fails_closed_without_token_outside_dev_mode(client, monkeypatch):
    monkeypatch.setattr(settings, "dev_mode", False)
    assert client.post(WEBHOOK, data=twilio_form("SM1", "+34600", "sí")).status_code == 503


def test_webhook_rejects_form_without_message_sid(client):
    assert client.post(WEBHOOK, data={"Body": "sí"}).status_code == 422


def test_start_candidate_sends_opener_once(client):
    outbound = FakeOutbound()
    api.app.dependency_overrides[api.get_whatsapp_outbound] = lambda: outbound
    created = client.post("/candidates", json={"phone": "+34600111222", "language": "en"})
    assert created.status_code == 201
    assert created.json() == {"candidate_id": "+34600111222", "status": "in_progress"}
    assert client.post("/candidates", json={"phone": "+34600111222"}).status_code == 409
    assert [phone for phone, _ in outbound.openers] == ["+34600111222"]
    assert "AI assistant" in outbound.openers[0][1]
    assert client.get("/candidates/+34600111222").json()["stage"] == "consent"
    assert client.post("/candidates", json={"phone": "whatsapp:+34"}).status_code == 422


def test_start_candidate_without_twilio_config_is_503(client):
    assert client.post("/candidates", json={"phone": "+34600111333"}).status_code == 503
