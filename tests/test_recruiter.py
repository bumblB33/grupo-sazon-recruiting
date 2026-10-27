import pytest
from pydantic import SecretStr

from screening_agent.api import app as api
from screening_agent.api.auth import issue_session
from screening_agent.api.deps import RECRUITER_COOKIE, get_email_sender
from screening_agent.channels.email import EmailSendError
from screening_agent.config import settings
from screening_agent.recruiter.router import LOGIN_PATH, RECRUITER_PREFIX
from tests.conftest import RECRUITER_EMAIL, log_in, screen_no_licence, twilio_form

LIST = f"{RECRUITER_PREFIX}/"


@pytest.fixture
def signed(monkeypatch) -> None:
    monkeypatch.setattr(settings, "session_secret", SecretStr("sign"))
    monkeypatch.setattr(settings, "recruiter_email_domains", ["gruposazon.com"])


def test_pages_redirect_to_login_without_cookie(client, signed):
    response = client.get(LIST, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == LOGIN_PATH
    assert client.get(LOGIN_PATH).status_code == 200


def test_login_link_enrolls_sets_cookie_and_is_single_use(client, email, signed):
    asked = client.post(LOGIN_PATH, data={"email": "Ana@GrupoSazon.com "})
    assert asked.status_code == 200
    assert "Check your inbox" in asked.text
    to, _, body = email.sent[-1]
    assert to == RECRUITER_EMAIL
    link = email.last_link()
    assert link.startswith(f"http://testserver{LOGIN_PATH}/")
    followed = client.get(link, follow_redirects=False)
    assert followed.status_code == 303
    assert followed.headers["location"] == LIST
    cookie = followed.headers["set-cookie"]
    assert f"{RECRUITER_COOKIE}=" in cookie and "HttpOnly" in cookie and "Max-Age=43200" in cookie
    page = client.get(LIST)
    assert page.status_code == 200
    assert RECRUITER_EMAIL in page.text
    repository = api.app.dependency_overrides[api.get_repository]()
    assert repository.get_recruiter(RECRUITER_EMAIL).last_login_at is not None
    reused = client.get(link, follow_redirects=False)
    assert reused.status_code == 401
    assert "already used" in reused.text
    client.post(f"{RECRUITER_PREFIX}/logout", follow_redirects=False)
    assert client.get(LIST, follow_redirects=False).status_code == 303


def test_unknown_domain_gets_the_same_page_but_no_email(client, email, signed):
    response = client.post(LOGIN_PATH, data={"email": "mallory@example.com"})
    assert response.status_code == 200
    assert "Check your inbox" in response.text
    assert email.sent == []
    repository = api.app.dependency_overrides[api.get_repository]()
    assert repository.get_recruiter("mallory@example.com") is None


def test_deactivated_recruiter_gets_no_link_and_loses_the_session(client, email, signed):
    log_in(client, email)
    assert client.get(LIST).status_code == 200
    repository = api.app.dependency_overrides[api.get_repository]()
    assert repository.set_recruiter_active(RECRUITER_EMAIL, False)
    assert client.get(LIST, follow_redirects=False).status_code == 303
    sent_before = len(email.sent)
    client.post(LOGIN_PATH, data={"email": RECRUITER_EMAIL})
    assert len(email.sent) == sent_before


def test_bad_login_links_and_cookies_are_rejected(client, signed):
    assert client.get(f"{LOGIN_PATH}/not-a-token", follow_redirects=False).status_code == 401
    client.cookies.set(RECRUITER_COOKIE, "garbage")
    assert client.get(LIST, follow_redirects=False).status_code == 303
    client.cookies.set(RECRUITER_COOKIE, issue_session("ghost@gruposazon.com", "sign", 12))
    assert client.get(LIST, follow_redirects=False).status_code == 303
    client.cookies.set(RECRUITER_COOKIE, issue_session(RECRUITER_EMAIL, "other-secret", 12))
    assert client.get(LIST, follow_redirects=False).status_code == 303


def test_pages_fail_closed_without_session_secret_outside_dev_mode(client, monkeypatch):
    monkeypatch.setattr(settings, "dev_mode", False)
    assert client.get(LIST).status_code == 503
    assert client.get(LOGIN_PATH).status_code == 503
    assert client.post(LOGIN_PATH, data={"email": "x@y.com"}).status_code == 503


def test_login_link_ignores_a_forged_host_header(client, email, signed, monkeypatch):
    monkeypatch.setattr(settings, "public_url", "https://recruit.gruposazon.com/")
    client.post(LOGIN_PATH, data={"email": RECRUITER_EMAIL}, headers={"Host": "evil.example"})
    assert email.last_link().startswith(f"https://recruit.gruposazon.com{LOGIN_PATH}/")
    assert "evil.example" not in email.sent[-1][2]


def test_login_fails_closed_without_public_url_outside_dev_mode(client, email, signed, monkeypatch):
    monkeypatch.setattr(settings, "dev_mode", False)
    response = client.post(
        LOGIN_PATH, data={"email": RECRUITER_EMAIL}, headers={"Host": "evil.example"}
    )
    assert response.status_code == 503
    assert email.sent == []


def test_recruiter_row_is_created_when_the_link_is_used_not_requested(client, email, signed):
    repository = api.app.dependency_overrides[api.get_repository]()
    client.post(LOGIN_PATH, data={"email": RECRUITER_EMAIL})
    assert repository.get_recruiter(RECRUITER_EMAIL) is None
    client.get(email.last_link(), follow_redirects=False)
    assert repository.get_recruiter(RECRUITER_EMAIL) is not None


def test_repeat_request_inside_cooldown_sends_nothing_and_looks_identical(client, email, signed):
    first = client.post(LOGIN_PATH, data={"email": RECRUITER_EMAIL})
    second = client.post(LOGIN_PATH, data={"email": RECRUITER_EMAIL})
    assert (first.status_code, first.text) == (second.status_code, second.text)
    assert len(email.sent) == 1


def test_one_ip_cannot_request_links_past_the_limit(client, email, signed, monkeypatch):
    monkeypatch.setattr(settings, "login_requests_per_ip", 2)
    for index in range(4):
        client.post(LOGIN_PATH, data={"email": f"user{index}@gruposazon.com"})
    assert [to for to, _, _ in email.sent] == ["user0@gruposazon.com", "user1@gruposazon.com"]


def test_malformed_address_at_an_allowed_domain_gets_no_email(client, email, signed):
    response = client.post(LOGIN_PATH, data={"email": "x@evil.com@gruposazon.com"})
    assert response.status_code == 200
    assert email.sent == []


def test_mail_provider_failure_still_answers_check_your_inbox(client, signed):
    class DownEmail:
        def send(self, to: str, subject: str, text: str) -> None:
            raise EmailSendError("provider down")

    api.app.dependency_overrides[get_email_sender] = DownEmail
    response = client.post(LOGIN_PATH, data={"email": RECRUITER_EMAIL})
    assert response.status_code == 200
    assert "Check your inbox" in response.text


def test_list_filters_and_shows_funnel(client):
    screen_no_licence(client, "+34600")
    client.post("/webhook/whatsapp", data=twilio_form("SM-other", "+34601", "sí"))
    page = client.get(LIST).text
    assert "+34600" in page and "+34601" in page
    assert "disqualified: 1" in page and "in_progress: 1" in page
    filtered = client.get(LIST, params={"status": "disqualified"}).text
    assert "+34600" in filtered and "+34601" not in filtered
    assert "No candidates match" in client.get(LIST, params={"stage": "start_date"}).text


def test_detail_shows_transcript_summary_and_override_form(client):
    screen_no_licence(client, "+34600")
    page = client.get(f"{RECRUITER_PREFIX}/candidates/+34600").text
    assert "Ana García" in page
    assert "no_licence" in page
    assert "no tengo carnet" in page
    assert "<pre>summary</pre>" in page
    assert "outcome" in page
    assert client.get(f"{RECRUITER_PREFIX}/candidates/nope").status_code == 404


def test_override_form_changes_status_and_records_event(client):
    screen_no_licence(client, "+34600")
    override = f"{RECRUITER_PREFIX}/candidates/+34600/override"
    response = client.post(
        override,
        data={"status": "qualified", "notes": "licence arrives Monday"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"{RECRUITER_PREFIX}/candidates/+34600"
    detail = client.get("/candidates/+34600").json()
    assert detail["status"] == "qualified"
    assert detail["recruiter_notes"] == "licence arrives Monday"
    assert [e["kind"] for e in detail["events"]] == ["outcome", "recruiter_override"]
    assert (
        client.post(override, data={"status": "", "notes": ""}, follow_redirects=False).status_code
        == 303
    )
    cleared = client.get("/candidates/+34600").json()
    assert cleared["status"] == "qualified"
    assert cleared["recruiter_notes"] == ""
    assert client.post(override, data={"status": "bogus"}).status_code == 422
    assert client.post(f"{RECRUITER_PREFIX}/candidates/nope/override", data={}).status_code == 404


def test_detail_route_marks_nothing_done_for_an_unknown_stage(client):
    from screening_agent.api import app as api

    screen_no_licence(client, "+34600")
    route = f"{RECRUITER_PREFIX}/candidates/+34600"
    assert 'class="done"' in client.get(route).text
    repository = api.app.dependency_overrides[api.get_repository]()
    repository.candidates.update_one({"_id": "+34600"}, {"$set": {"stage": "retired_stage"}})
    page = client.get(route).text
    assert 'class="done"' not in page and 'class="here"' not in page
