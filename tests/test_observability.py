import json
import logging

from logfire.testing import TestExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import SecretStr

from screening_agent.api import app as api
from screening_agent.channels.email import LoggingEmailSender
from screening_agent.config import settings
from screening_agent.observability import (
    REDACTED,
    CandidatePathProcessor,
    candidate_hash,
    configure_observability,
    redact_contact,
)
from screening_agent.recruiter.router import LOGIN_PATH
from tests.conftest import (
    NO_LICENCE_TURNS,
    RECRUITER_EMAIL,
    FakeOutbound,
    log_in,
    screen_no_licence,
)

PHONE = "+34600111222"
APPLICANT = "Zacarías Quintanilla"


def test_candidate_hash_is_keyed_and_absent_without_secret(monkeypatch):
    assert candidate_hash(PHONE) is None
    monkeypatch.setattr(settings, "candidate_hash_secret", SecretStr("one"))
    first = candidate_hash(PHONE)
    assert first is not None and PHONE not in first
    assert candidate_hash(PHONE) == first
    monkeypatch.setattr(settings, "candidate_hash_secret", SecretStr("two"))
    assert candidate_hash(PHONE) != first


def test_candidate_path_processor_rewrites_url_attributes_at_start():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(CandidatePathProcessor())
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    attributes = {
        "http.target": f"/recruiter/candidates/{PHONE}?tab=events",
        "http.url": f"http://testserver/candidates/{PHONE}",
        "url.path": "/candidates/web-abc123",
        "http.route": "/candidates/{candidate_id}",
    }
    provider.get_tracer("test").start_span("GET", attributes=attributes).end()
    exported = dict(exporter.get_finished_spans()[0].attributes or {})
    assert exported["http.target"] == "/recruiter/candidates/{candidate_id}?tab=events"
    assert exported["http.url"] == "http://testserver/candidates/{candidate_id}"
    assert exported["url.path"] == "/candidates/{candidate_id}"


def test_scrub_callback_redacts_contact_details_without_echoing_them():
    import re

    from logfire import ScrubMatch

    for value in (PHONE, RECRUITER_EMAIL):
        match = re.search(re.escape(value), f"x {value} y")
        assert match is not None
        assert (
            redact_contact(ScrubMatch(path=("attributes", "k"), value=value, pattern_match=match))
            == REDACTED
        )
    password = re.search("password", "password")
    assert password is not None
    assert redact_contact(ScrubMatch(path=("k",), value="v", pattern_match=password)) is None


def test_logging_email_sender_keeps_the_login_link_out_of_log_records(caplog, capsys):
    with caplog.at_level(logging.DEBUG):
        LoggingEmailSender().send(RECRUITER_EMAIL, "subject", "https://x/recruiter/login/secret")
    assert caplog.records == []
    assert "secret" in capsys.readouterr().err


def test_no_contact_details_or_message_text_leave_the_service(client, email, monkeypatch):
    """Configures Logfire globally for the rest of the session; nothing is sent without a token."""
    exporter = TestExporter()
    configure_observability(
        "screening-test", api.app, additional_span_processors=[SimpleSpanProcessor(exporter)]
    )
    monkeypatch.setattr(settings, "session_secret", SecretStr("sign"))
    monkeypatch.setattr(settings, "recruiter_email_domains", ["gruposazon.com"])
    monkeypatch.setattr(settings, "candidate_hash_secret", SecretStr("hash"))
    outbound = FakeOutbound()
    api.app.dependency_overrides[api.get_whatsapp_outbound] = lambda: outbound

    client.post("/candidates", json={"phone": PHONE, "language": "es", "name": APPLICANT})
    screen_no_licence(client, PHONE)
    log_in(client, email)
    login_link = email.last_link()
    client.post(LOGIN_PATH, data={"email": RECRUITER_EMAIL})
    client.get(f"/candidates/{PHONE}")
    client.get(f"/recruiter/candidates/{PHONE}")

    # The raw list includes Logfire's pending spans, which exported_spans_as_dict() drops.
    spans = [
        {
            "name": span.name,
            "attributes": dict(span.attributes or {}),
            "events": [(event.name, dict(event.attributes or {})) for event in span.events],
        }
        for span in exporter.exported_spans
    ]
    exported = json.dumps(spans, ensure_ascii=False, default=str)
    span_types = {span["attributes"].get("logfire.span_type") for span in spans}
    assert {"span", "pending_span", "log"} <= span_types
    span_names = {span["name"] for span in spans}
    assert {"handle", "guardrail", "turn", "summary"} <= span_names
    assert any("GET" in name for name in span_names), "HTTP spans were not captured"
    assert any("candidate.hash" in span["attributes"] for span in spans)
    assert any("throttled" in span["name"] for span in spans)
    leaked = [
        value
        for value in (PHONE, PHONE.removeprefix("+"), RECRUITER_EMAIL, login_link.rsplit("/", 1)[1])
        + tuple(NO_LICENCE_TURNS[1:])
        + (APPLICANT, APPLICANT.split()[0])
        if value in exported
    ]
    assert leaked == []
