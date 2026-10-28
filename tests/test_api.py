from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from screening_agent.api import app as api
from screening_agent.api.auth import hash_secret, issue_session, new_api_key
from screening_agent.api.deps import CSRF_HEADER, RECRUITER_COOKIE, email_sender, get_email_sender
from screening_agent.channels.whatsapp import _twilio_signature
from screening_agent.config import settings
from tests.conftest import (
    RECRUITER_EMAIL,
    FakeOutbound,
    log_in,
    open_candidate,
    screen_no_licence,
    twilio_form,
)

WEBHOOK = "/webhook/whatsapp"


def signed_headers(client: TestClient, form: dict[str, str], token: str) -> dict[str, str]:
    url = str(client.base_url) + WEBHOOK
    return {"X-Twilio-Signature": _twilio_signature(url, form, token)}


def test_webhook_then_override_and_analytics(client):
    open_candidate("+34600")
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
    open_candidate("+34600")
    client.post(WEBHOOK, data=twilio_form("SM1", "+34600", "sí"))
    client.patch("/candidates/+34600", json={"status": "qualified", "notes": "ok"})
    detail = client.get("/candidates/+34600").json()
    assert [(m["direction"], m["body"][:5]) for m in detail["transcript"]] == [
        ("out", "¡Hola"),
        ("in", "sí"),
        ("out", "Hola"),
    ]
    assert [e["kind"] for e in detail["events"]] == ["recruiter_override"]
    assert detail["events"][0]["payload"] == {
        "status": "qualified",
        "notes": "ok",
        "actor": "dev:dev-mode",
    }


def test_terminal_turn_summarises_in_background(client):
    screen_no_licence(client, "+34601")
    assert client.get("/candidates/+34601").json()["summary"] == "summary"


def test_api_key_header_identifies_the_client_and_revocation_sticks(client, monkeypatch):
    monkeypatch.setattr(settings, "session_secret", SecretStr("sign"))
    repository = api.app.dependency_overrides[api.get_repository]()
    key_id, secret, presented = new_api_key()
    repository.save_api_key(key_id, hash_secret(secret), "ats-sync")
    assert client.get("/candidates").status_code == 401
    assert client.get("/candidates", headers={"x-api-key": "nonsense"}).status_code == 401
    assert client.get("/candidates", headers={"x-api-key": f"{key_id}.wrong"}).status_code == 401
    assert client.get("/candidates", headers={"x-api-key": presented}).status_code == 200
    open_candidate("+34600")
    client.post("/webhook/whatsapp", data=twilio_form("SM1", "+34600", "sí"))
    patched = client.patch(
        "/candidates/+34600", json={"notes": "seen"}, headers={"x-api-key": presented}
    )
    assert patched.status_code == 200
    events = client.get("/candidates/+34600", headers={"x-api-key": presented}).json()["events"]
    assert events[-1]["payload"]["actor"] == "api_key:ats-sync"
    repository.revoke_api_key(key_id)
    assert client.get("/candidates", headers={"x-api-key": presented}).status_code == 401


def test_session_cookie_from_login_link_works_on_json_routes(client, email, monkeypatch):
    monkeypatch.setattr(settings, "session_secret", SecretStr("sign"))
    monkeypatch.setattr(settings, "recruiter_email_domains", ["gruposazon.com"])
    log_in(client, email)
    assert client.get("/candidates").status_code == 200
    open_candidate("+34600")
    client.post("/webhook/whatsapp", data=twilio_form("SM1", "+34600", "sí"))
    token = client.get("/csrf-token").json()["csrf_token"]
    patched = client.patch(
        "/candidates/+34600", json={"status": "qualified"}, headers={CSRF_HEADER: token}
    )
    assert patched.status_code == 200
    events = client.get("/candidates/+34600").json()["events"]
    assert events[-1]["payload"]["actor"] == f"recruiter:{RECRUITER_EMAIL}"


def test_cookie_writes_on_json_routes_need_the_csrf_header(client, email, monkeypatch):
    monkeypatch.setattr(settings, "session_secret", SecretStr("sign"))
    monkeypatch.setattr(settings, "recruiter_email_domains", ["gruposazon.com"])
    log_in(client, email)
    open_candidate("+34600")
    client.post("/webhook/whatsapp", data=twilio_form("SM1", "+34600", "sí"))
    override = {"status": "qualified"}
    assert client.patch("/candidates/+34600", json=override).status_code == 403
    forged = {CSRF_HEADER: "0" * 64}
    assert client.patch("/candidates/+34600", json=override, headers=forged).status_code == 403
    start = {"phone": "+34600111444"}
    assert client.post("/candidates", json=start).status_code == 403
    assert client.get("/candidates/+34600").json()["status"] == "in_progress"


def test_api_key_writes_work_without_a_session_secret(client, monkeypatch):
    monkeypatch.setattr(settings, "dev_mode", False)
    repository = api.app.dependency_overrides[api.get_repository]()
    key_id, secret, presented = new_api_key()
    repository.save_api_key(key_id, hash_secret(secret), "ats-sync")
    monkeypatch.setattr(settings, "dev_mode", True)
    open_candidate("+34600")
    client.post(WEBHOOK, data=twilio_form("SM1", "+34600", "sí"))
    monkeypatch.setattr(settings, "dev_mode", False)
    headers = {"x-api-key": presented}
    assert (
        client.patch("/candidates/+34600", json={"notes": "x"}, headers=headers).status_code == 200
    )
    assert client.get("/csrf-token", headers=headers).json() == {"csrf_token": None}


def test_json_routes_reject_tampered_and_expired_cookies(client, monkeypatch):
    monkeypatch.setattr(settings, "session_secret", SecretStr("sign"))
    monkeypatch.setattr(settings, "recruiter_email_domains", ["gruposazon.com"])
    client.cookies.set(RECRUITER_COOKIE, issue_session(RECRUITER_EMAIL, "other-secret", 12))
    assert client.get("/candidates").status_code == 401
    expired = issue_session(RECRUITER_EMAIL, "sign", 1, now=datetime.now(UTC) - timedelta(hours=2))
    client.cookies.set(RECRUITER_COOKIE, expired)
    assert client.get("/candidates").status_code == 401


def test_candidate_list_pages_and_rejects_unknown_filters(client):
    for index in range(3):
        open_candidate(f"+3460{index}")
        client.post(WEBHOOK, data=twilio_form(f"SM{index}", f"+3460{index}", "sí"))
    first = [c["id"] for c in client.get("/candidates", params={"limit": 2}).json()]
    rest = client.get("/candidates", params={"limit": 2, "offset": 2}).json()
    paged = first + [c["id"] for c in rest]
    every = [c["id"] for c in client.get("/candidates").json()]
    assert len(first) == 2 and paged == every
    assert client.get("/candidates", params={"status": "qualifed"}).status_code == 422
    assert client.get("/candidates", params={"stage": "nope"}).status_code == 422
    assert client.get("/candidates", params={"limit": 0}).status_code == 422
    assert client.get("/candidates", params={"limit": 501}).status_code == 422
    assert len(client.get("/candidates", params={"status": "in_progress"}).json()) == 3


def test_login_without_mail_settings_does_not_name_them(client, monkeypatch):
    monkeypatch.setattr(settings, "dev_mode", False)
    monkeypatch.setattr(settings, "session_secret", SecretStr("sign"))
    monkeypatch.setattr(settings, "public_url", "https://recruit.gruposazon.com")
    del api.app.dependency_overrides[get_email_sender]
    email_sender.cache_clear()
    response = client.post("/recruiter/login", data={"email": RECRUITER_EMAIL})
    assert response.status_code == 503
    assert "SCREENING_" not in response.text


def test_recruiter_routes_fail_closed_without_session_secret_outside_dev_mode(client, monkeypatch):
    monkeypatch.setattr(settings, "dev_mode", False)
    assert client.get("/candidates").status_code == 503


def test_webhook_requires_valid_twilio_signature_when_token_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "twilio_auth_token", SecretStr("auth-token"))
    form = twilio_form("SM1", "+34600", "sí")
    assert client.post(WEBHOOK, data=form).status_code == 401
    bad = signed_headers(client, form, "wrong-token")
    assert client.post(WEBHOOK, data=form, headers=bad).status_code == 401
    good = signed_headers(client, form, "auth-token")
    assert client.post(WEBHOOK, data=form, headers=good).status_code == 200


def test_webhook_signature_uses_configured_public_url(client, monkeypatch):
    monkeypatch.setattr(settings, "twilio_auth_token", SecretStr("auth-token"))
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
    created = client.post(
        "/candidates", json={"phone": "+34600111222", "language": "en", "name": "Ana García"}
    )
    assert created.status_code == 201
    assert created.json() == {"candidate_id": "+34600111222", "status": "in_progress"}
    assert client.post("/candidates", json={"phone": "+34600111222"}).status_code == 409
    assert [phone for phone, _, _ in outbound.openers] == ["+34600111222"]
    assert outbound.openers[0][1].startswith("Hi, Ana! I'm")
    assert "AI assistant" in outbound.openers[0][1]
    detail = client.get("/candidates/+34600111222").json()
    assert detail["stage"] == "consent"
    assert detail["applicant_name"] == "Ana García"
    assert "Ana García" in client.get("/recruiter/candidates/+34600111222").text
    assert "Ana García" in client.get("/recruiter/").text
    assert client.post("/candidates", json={"phone": "whatsapp:+34"}).status_code == 422


def test_start_candidate_without_twilio_config_is_503(client):
    assert client.post("/candidates", json={"phone": "+34600111333"}).status_code == 503


def test_unknown_number_gets_the_fixed_reply_and_nothing_is_stored(client):
    repository = api.app.dependency_overrides[api.get_repository]()
    response = client.post(WEBHOOK, data=twilio_form("SM-stranger", "+34699000000", "hola"))
    assert response.status_code == 200
    assert response.headers["X-Screening-Outcome"] == "unknown"
    assert "No encuentro ninguna solicitud" in response.text
    assert "I can&#x27;t find an application" in response.text or "can't find" in response.text
    assert not repository.conversation_exists("+34699000000")
    assert repository.list_candidates() == []
    assert not repository.has_message("SM-stranger")
    screen_no_licence(client, "+34600")
    assert client.get("/candidates/+34600").json()["status"] == "disqualified"


@pytest.mark.parametrize("name", ["   ", "12345", "Ana; drop", "<b>Ana</b>"])
def test_start_rejects_applicant_names_that_are_not_names(client, name):
    api.app.dependency_overrides[api.get_whatsapp_outbound] = lambda: FakeOutbound()
    body = {"phone": "+34600111222", "language": "es", "name": name}
    assert client.post("/candidates", json=body).status_code == 422


def test_start_trims_and_collapses_the_applicant_name(client):
    outbound = FakeOutbound()
    api.app.dependency_overrides[api.get_whatsapp_outbound] = lambda: outbound
    body = {"phone": "+34600111222", "language": "es", "name": "  Ana   García-López  "}
    assert client.post("/candidates", json=body).status_code == 201
    assert client.get("/candidates/+34600111222").json()["applicant_name"] == "Ana García-López"
