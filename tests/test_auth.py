import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from screening_agent.api.auth import (
    email_domain_allowed,
    hash_secret,
    is_valid_email,
    issue_session,
    new_api_key,
    read_session,
    secret_matches,
    split_api_key,
)
from screening_agent.channels.email import EmailSendError, SendGridEmailSender


def test_session_round_trip_and_expiry():
    issued = datetime.now(UTC)
    token = issue_session("ana@gruposazon.com", "s", 12, now=issued)
    session = read_session(token, "s")
    assert session is not None
    assert session.email == "ana@gruposazon.com"
    assert abs((session.issued_at - issued).total_seconds()) < 0.001
    assert read_session(token, "other") is None
    assert read_session(None, "s") is None
    assert read_session("not.a.jwt", "s") is None
    stale = issue_session("ana@gruposazon.com", "s", 1, now=datetime.now(UTC) - timedelta(hours=2))
    assert read_session(stale, "s") is None


def test_api_key_shape_and_hash():
    key_id, secret, presented = new_api_key()
    assert split_api_key(presented) == (key_id, secret)
    assert split_api_key("nodot") is None
    assert split_api_key(".secret") is None
    assert secret_matches(secret, hash_secret(secret))
    assert not secret_matches("x", hash_secret(secret))


def test_email_domain_allowlist():
    assert email_domain_allowed("Ana@GrupoSazon.com", ["gruposazon.com"])
    assert email_domain_allowed("ana@gruposazon.mx", ["gruposazon.com", "@gruposazon.mx"])
    assert not email_domain_allowed("ana@example.com", ["gruposazon.com"])
    assert not email_domain_allowed("gruposazon.com", ["gruposazon.com"])
    assert not email_domain_allowed("ana@gruposazon.com", [])


def test_sendgrid_sender_posts_v3_mail_send():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["json"] = request.read()
        return httpx.Response(202)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    SendGridEmailSender("SG.key", "noreply@gruposazon.com", client).send(
        "ana@gruposazon.com", "Login", "link here"
    )
    assert seen["url"] == SendGridEmailSender.SEND_URL
    assert seen["auth"] == "Bearer SG.key"
    body = json.loads(seen["json"])
    assert body["personalizations"] == [{"to": [{"email": "ana@gruposazon.com"}]}]
    assert body["from"] == {"email": "noreply@gruposazon.com"}
    assert body["content"] == [{"type": "text/plain", "value": "link here"}]


def test_email_shape_rejects_crafted_addresses():
    assert is_valid_email("ana.g+ops@gruposazon.com")
    assert not is_valid_email("x@evil.com@gruposazon.com")
    assert not is_valid_email("a@gruposazon.com, b@evil.com")
    assert not is_valid_email("ana@gruposazon.com\nbcc:b@evil.com")
    assert not is_valid_email("ana@localhost")
    assert not is_valid_email(f"{'a' * 250}@gruposazon.com")


@pytest.mark.parametrize("failure", [httpx.Response(500), httpx.ConnectError("down")])
def test_sendgrid_failure_surfaces_as_email_send_error(failure):
    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(failure, Exception):
            raise failure
        return failure

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sender = SendGridEmailSender("SG.key", "noreply@gruposazon.com", client)
    with pytest.raises(EmailSendError):
        sender.send("ana@gruposazon.com", "Login", "link")
