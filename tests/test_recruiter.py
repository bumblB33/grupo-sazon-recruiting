import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from string import Formatter

import pytest
from pydantic import SecretStr

from screening_agent.api import app as api
from screening_agent.api import deps
from screening_agent.api.auth import issue_session
from screening_agent.api.deps import RECRUITER_COOKIE, get_email_sender
from screening_agent.channels.email import (
    EmailSendError,
    LoggingEmailSender,
    RedirectingEmailSender,
)
from screening_agent.config import settings
from screening_agent.recruiter.i18n import DEFAULT_LOCALE, LOCALE_COOKIE, STRINGS
from screening_agent.recruiter.router import CSRF_FIELD, LOGIN_PATH, RECRUITER_PREFIX
from tests.conftest import (
    RECRUITER_EMAIL,
    FakeOutbound,
    invite,
    log_in,
    open_candidate,
    screen_no_licence,
    twilio_form,
)

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


def test_login_link_sets_cookie_and_is_single_use(client, email, signed):
    invite()
    asked = client.post(LOGIN_PATH, data={"email": "Ana@GrupoSazon.com "})
    assert asked.status_code == 200
    assert "Revisa tu correo" in asked.text
    to, _, body = email.sent[-1]
    assert to == RECRUITER_EMAIL
    link = email.last_link()
    assert link.startswith(f"http://testserver{LOGIN_PATH}/")
    followed = client.post(link, follow_redirects=False)
    assert followed.status_code == 303
    assert followed.headers["location"] == LIST
    cookie = followed.headers["set-cookie"]
    assert f"{RECRUITER_COOKIE}=" in cookie and "HttpOnly" in cookie and "Max-Age=43200" in cookie
    assert "Secure" not in cookie
    page = client.get(LIST)
    assert page.status_code == 200
    assert RECRUITER_EMAIL in page.text
    repository = api.app.dependency_overrides[api.get_repository]()
    assert repository.get_recruiter(RECRUITER_EMAIL).last_login_at is not None
    reused = client.post(link, follow_redirects=False)
    assert reused.status_code == 401
    assert "ya se usó" in reused.text
    assert client.get(link, follow_redirects=False).status_code == 401
    client.post(f"{RECRUITER_PREFIX}/logout", follow_redirects=False)
    assert client.get(LIST, follow_redirects=False).status_code == 303


def test_opening_the_link_shows_a_confirm_button_and_does_not_consume_it(client, email, signed):
    """Mail scanners prefetch GET; the token must survive until the recruiter presses the button."""
    invite()
    client.post(LOGIN_PATH, data={"email": RECRUITER_EMAIL})
    link = email.last_link()
    for _ in range(2):
        opened = client.get(link, follow_redirects=False)
        assert opened.status_code == 200
        assert "set-cookie" not in opened.headers
        assert f'action="{link.removeprefix("http://testserver")}"' in opened.text
    assert client.post(link, follow_redirects=False).status_code == 303


def test_uninvited_address_at_an_allowed_domain_gets_no_email_and_no_row(client, email, signed):
    response = client.post(LOGIN_PATH, data={"email": "intern@gruposazon.com"})
    assert response.status_code == 200
    assert "Revisa tu correo" in response.text
    assert email.sent == []
    repository = api.app.dependency_overrides[api.get_repository]()
    assert repository.get_recruiter("intern@gruposazon.com") is None


def test_invite_outside_the_domain_allowlist_cannot_log_in(client, email, signed):
    invite("ana@example.com")
    client.post(LOGIN_PATH, data={"email": "ana@example.com"})
    assert email.sent == []


def test_unknown_domain_gets_the_same_page_but_no_email(client, email, signed):
    response = client.post(LOGIN_PATH, data={"email": "mallory@example.com"})
    assert response.status_code == 200
    assert "Revisa tu correo" in response.text
    assert email.sent == []
    repository = api.app.dependency_overrides[api.get_repository]()
    assert repository.get_recruiter("mallory@example.com") is None


def test_deactivated_recruiter_gets_no_link_and_loses_the_session(client, email, signed):
    log_in(client, email)
    assert client.get(LIST).status_code == 200
    repository = api.app.dependency_overrides[api.get_repository]()
    repository.deactivate_recruiter(RECRUITER_EMAIL)
    assert client.get(LIST, follow_redirects=False).status_code == 303
    sent_before = len(email.sent)
    client.post(LOGIN_PATH, data={"email": RECRUITER_EMAIL})
    assert len(email.sent) == sent_before


def test_reactivation_does_not_revive_a_session_issued_before_deactivation(
    client, email, signed, monkeypatch
):
    monkeypatch.setattr(settings, "login_email_cooldown_seconds", 0)
    log_in(client, email)
    old_cookie = client.cookies[RECRUITER_COOKIE]
    repository = api.app.dependency_overrides[api.get_repository]()
    repository.deactivate_recruiter(RECRUITER_EMAIL)
    assert repository.reactivate_recruiter(RECRUITER_EMAIL)
    client.cookies.set(RECRUITER_COOKIE, old_cookie)
    assert client.get(LIST, follow_redirects=False).status_code == 303
    client.cookies.clear()
    log_in(client, email)
    assert client.get(LIST).status_code == 200


def test_deactivation_outranks_a_session_issued_inside_the_same_stored_millisecond(client, signed):
    invite()
    repository = api.app.dependency_overrides[api.get_repository]()
    repository.deactivate_recruiter(RECRUITER_EMAIL)
    repository.reactivate_recruiter(RECRUITER_EMAIL)
    stored = repository.get_recruiter(RECRUITER_EMAIL).sessions_valid_after
    inside = issue_session(RECRUITER_EMAIL, "sign", 12, now=stored + timedelta(microseconds=500))
    client.cookies.set(RECRUITER_COOKIE, inside)
    assert client.get(LIST, follow_redirects=False).status_code == 303
    after = issue_session(RECRUITER_EMAIL, "sign", 12, now=stored + timedelta(milliseconds=2))
    client.cookies.set(RECRUITER_COOKIE, after)
    assert client.get(LIST).status_code == 200


def test_deactivation_between_request_and_click_refuses_the_link(client, email, signed):
    invite()
    client.post(LOGIN_PATH, data={"email": RECRUITER_EMAIL})
    repository = api.app.dependency_overrides[api.get_repository]()
    repository.deactivate_recruiter(RECRUITER_EMAIL)
    refused = client.post(email.last_link(), follow_redirects=False)
    assert refused.status_code == 401
    assert "no está activa" in refused.text
    assert "set-cookie" not in refused.headers


def test_removing_the_domain_from_the_allowlist_ends_live_sessions(
    client, email, signed, monkeypatch
):
    log_in(client, email)
    assert client.get(LIST).status_code == 200
    monkeypatch.setattr(settings, "recruiter_email_domains", ["other.example"])
    assert client.get(LIST, follow_redirects=False).status_code == 303


def test_session_cookie_is_secure_when_the_public_url_is_https(client, email, signed, monkeypatch):
    monkeypatch.setattr(settings, "public_url", "https://recruit.gruposazon.com")
    invite()
    client.post(LOGIN_PATH, data={"email": RECRUITER_EMAIL})
    link = email.last_link().replace("https://recruit.gruposazon.com", "http://testserver")
    followed = client.post(link, follow_redirects=False)
    assert followed.status_code == 303
    assert "Secure" in followed.headers["set-cookie"]


def test_override_form_needs_the_csrf_token_from_the_page(client, email, signed):
    log_in(client, email)
    screen_no_licence(client, "+34600")
    override = f"{RECRUITER_PREFIX}/candidates/+34600/override"
    data = {"status": "qualified", "notes": ""}
    assert client.post(override, data=data, follow_redirects=False).status_code == 403
    forged = {**data, CSRF_FIELD: "0" * 64}
    assert client.post(override, data=forged, follow_redirects=False).status_code == 403
    page = client.get(f"{RECRUITER_PREFIX}/candidates/+34600").text
    marker = f'name="{CSRF_FIELD}" value="'
    token = page.split(marker, 1)[1].split('"', 1)[0]
    genuine = {**data, CSRF_FIELD: token}
    assert client.post(override, data=genuine, follow_redirects=False).status_code == 303
    assert client.get("/candidates/+34600").json()["status"] == "qualified"


def test_invalid_address_is_not_echoed_on_the_inbox_page(client, signed):
    response = client.post(LOGIN_PATH, data={"email": "<b>mallory</b>@evil.com@gruposazon.com"})
    assert response.status_code == 200
    assert "mallory" not in response.text
    assert "esa dirección" in response.text


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
    invite()
    monkeypatch.setattr(settings, "public_url", "https://recruit.gruposazon.com/")
    client.post(LOGIN_PATH, data={"email": RECRUITER_EMAIL}, headers={"Host": "evil.example"})
    assert email.last_link().startswith(f"https://recruit.gruposazon.com{LOGIN_PATH}/")
    assert "evil.example" not in email.sent[-1][2]


def test_login_fails_closed_without_public_url_outside_dev_mode(client, email, signed, monkeypatch):
    invite()
    monkeypatch.setattr(settings, "dev_mode", False)
    response = client.post(
        LOGIN_PATH, data={"email": RECRUITER_EMAIL}, headers={"Host": "evil.example"}
    )
    assert response.status_code == 503
    assert email.sent == []


@pytest.fixture
def real_email_sender(monkeypatch) -> Iterator[None]:
    """Routes the login form through the configured sender instead of the FakeEmail override."""
    api.app.dependency_overrides.pop(get_email_sender, None)
    deps.email_sender.cache_clear()
    monkeypatch.setattr(settings, "login_email_redirect_to", "demo-inbox@example.com")
    yield
    deps.email_sender.cache_clear()


def test_redirect_delivers_every_login_email_to_one_address_in_dev_mode(
    client, signed, real_email_sender, capsys
):
    invite()
    sender = deps.email_sender()
    assert isinstance(sender, RedirectingEmailSender)
    assert isinstance(sender.inner, LoggingEmailSender)
    client.post(LOGIN_PATH, data={"email": RECRUITER_EMAIL})
    printed = capsys.readouterr().err
    assert printed.startswith("email to demo-inbox@example.com:")
    assert f"Requested for {RECRUITER_EMAIL}." in printed
    assert f"{LOGIN_PATH}/" in printed


def test_redirect_fails_closed_outside_dev_mode(client, signed, real_email_sender, monkeypatch):
    invite()
    monkeypatch.setattr(settings, "dev_mode", False)
    monkeypatch.setattr(settings, "public_url", "https://recruit.gruposazon.com")
    monkeypatch.setattr(settings, "sendgrid_api_key", SecretStr("SG.x"))
    monkeypatch.setattr(settings, "login_email_from", "login@gruposazon.com")
    response = client.post(LOGIN_PATH, data={"email": RECRUITER_EMAIL})
    assert response.status_code == 503
    assert "REDIRECT" not in response.text


def test_repeat_request_inside_cooldown_sends_nothing_and_looks_identical(client, email, signed):
    invite()
    first = client.post(LOGIN_PATH, data={"email": RECRUITER_EMAIL})
    second = client.post(LOGIN_PATH, data={"email": RECRUITER_EMAIL})
    assert (first.status_code, first.text) == (second.status_code, second.text)
    assert len(email.sent) == 1


def test_one_ip_cannot_request_links_past_the_limit(client, email, signed, monkeypatch):
    monkeypatch.setattr(settings, "login_requests_per_ip", 2)
    for index in range(4):
        invite(f"user{index}@gruposazon.com")
        client.post(LOGIN_PATH, data={"email": f"user{index}@gruposazon.com"})
    assert [to for to, _, _ in email.sent] == ["user0@gruposazon.com", "user1@gruposazon.com"]


def test_malformed_address_at_an_allowed_domain_gets_no_email(client, email, signed):
    response = client.post(LOGIN_PATH, data={"email": "x@evil.com@gruposazon.com"})
    assert response.status_code == 200
    assert email.sent == []


def test_mail_provider_failure_still_answers_check_your_inbox(client, signed):
    invite()

    class DownEmail:
        def send(self, to: str, subject: str, text: str) -> None:
            raise EmailSendError("provider down")

    api.app.dependency_overrides[get_email_sender] = DownEmail
    response = client.post(LOGIN_PATH, data={"email": RECRUITER_EMAIL})
    assert response.status_code == 200
    assert "Revisa tu correo" in response.text


def test_list_filters_and_shows_funnel(client):
    screen_no_licence(client, "+34600")
    open_candidate("+34601")
    client.post("/webhook/whatsapp", data=twilio_form("SM-other", "+34601", "sí"))
    page = client.get(LIST).text
    assert "+34600" in page and "+34601" in page
    assert "Disqualified: 1" in page and "In progress: 1" in page
    filtered = client.get(LIST, params={"status": "disqualified"}).text
    assert "+34600" in filtered and "+34601" not in filtered
    assert "No candidates match" in client.get(LIST, params={"stage": "start_date"}).text


def test_detail_shows_transcript_summary_and_override_form(client):
    screen_no_licence(client, "+34600")
    page = client.get(f"{RECRUITER_PREFIX}/candidates/+34600").text
    assert "Ana García" in page
    assert "No driving licence" in page
    assert "no_licence" not in page
    assert "no tengo carnet" in page
    assert "<pre>summary</pre>" in page
    assert "Outcome reached" in page
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


def test_detail_shows_the_turn_inspector_and_refreshes_only_while_in_progress(client):
    screen_no_licence(client, "+34600")
    closed_page = client.get(f"{RECRUITER_PREFIX}/candidates/+34600").text
    assert 'http-equiv="refresh"' not in closed_page
    assert "<script>" not in closed_page
    assert "Why this reply" in closed_page
    assert "Driving licence &rarr; Zone · Disqualified" in closed_page
    assert "Fixed closing message" in closed_page
    open_candidate("+34601")
    client.post("/webhook/whatsapp", data=twilio_form("SM-open", "+34601", "sí"))
    open_page = client.get(f"{RECRUITER_PREFIX}/candidates/+34601").text
    assert '<noscript><meta http-equiv="refresh" content="5"></noscript>' in open_page
    assert 'data-poll-seconds="5"' in open_page
    assert "Consent &rarr; Full name" in open_page


def test_live_fragment_needs_a_session(client, signed):
    route = f"{RECRUITER_PREFIX}/candidates/+34600/live"
    response = client.get(route, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == LOGIN_PATH


def test_live_fragment_carries_only_the_regions_and_the_poll_interval(client):
    screen_no_licence(client, "+34600")
    open_candidate("+34601")
    client.post("/webhook/whatsapp", data=twilio_form("SM-live", "+34601", "sí"))
    closed = client.get(f"{RECRUITER_PREFIX}/candidates/+34600/live")
    assert closed.headers["cache-control"] == "no-store"
    assert 'data-poll-seconds="0"' in closed.text
    open_ = client.get(f"{RECRUITER_PREFIX}/candidates/+34601/live").text
    assert 'data-poll-seconds="5"' in open_
    for region in ("facts", "route", "transcript", "summary", "profile", "events"):
        assert f'data-live="{region}"' in open_
    assert "<form" not in open_ and "<html" not in open_
    assert client.get(f"{RECRUITER_PREFIX}/candidates/nope/live").status_code == 404


def test_archived_copy_does_not_poll(client, monkeypatch):
    open_candidate("+34601")
    monkeypatch.setattr(settings, "demo_phones", ["+34601"])
    location = client.post(reset_path("+34601"), follow_redirects=False).headers["location"]
    assert 'data-poll-seconds="0"' in client.get(location).text


def placeholders(template: str) -> set[str]:
    return {field for _, field, _, _ in Formatter().parse(template) if field}


def test_locale_catalogs_share_one_key_set_and_placeholders():
    reference = STRINGS[DEFAULT_LOCALE]
    for strings in STRINGS.values():
        assert set(strings) == set(reference)
        for key, template in strings.items():
            assert placeholders(template) == placeholders(reference[key]), key
    assert placeholders(reference["email_body"]) == {"link", "minutes"}
    assert placeholders(reference["check_inbox_body_named"]) == {"email"}


def test_lang_query_sets_cookie_and_carries_through_the_login_flow(client, email, signed):
    invite()
    chosen = client.get(LOGIN_PATH, params={"lang": "es-ES"})
    assert chosen.status_code == 200
    assert f"{LOCALE_COOKIE}=es-ES" in chosen.headers["set-cookie"]
    assert '<html lang="es-ES">' in chosen.text
    assert "Correo electrónico de trabajo" in chosen.text
    assert 'aria-current="true">Español (ES)' in chosen.text
    asked = client.post(LOGIN_PATH, data={"email": RECRUITER_EMAIL})
    assert "tu enlace de acceso está en camino" in asked.text
    assert f"<strong>{RECRUITER_EMAIL}</strong>" in asked.text
    _, subject, _ = email.sent[-1]
    assert subject.startswith("Tu enlace de acceso")
    confirm = client.get(email.last_link())
    assert "Haz clic en el botón" in confirm.text
    switched = client.get(LOGIN_PATH, params={"lang": "en-US"})
    assert "Recruiter login" in switched.text and "Work email" in switched.text
    assert "recruiting · delivery drivers" in switched.text


def test_unknown_lang_falls_back_and_sets_no_cookie(client, signed):
    response = client.get(LOGIN_PATH, params={"lang": "fr-FR"})
    assert response.status_code == 200
    assert "set-cookie" not in response.headers
    assert '<html lang="es-MX">' in response.text


def test_accept_language_picks_the_locale_without_a_cookie(client, signed):
    english = client.get(LOGIN_PATH, headers={"Accept-Language": "en-GB,en;q=0.8"})
    assert "Recruiter login" in english.text
    assert "set-cookie" not in english.headers
    spanish = client.get(LOGIN_PATH, headers={"Accept-Language": "fr-FR, es-ES;q=0.5"})
    assert "Correo electrónico de trabajo" in spanish.text


def reset_path(candidate_id: str) -> str:
    return f"{RECRUITER_PREFIX}/candidates/{candidate_id}/reset"


def test_reset_button_and_route_exist_only_for_allowlisted_phones(client, monkeypatch):
    screen_no_licence(client, "+34600")
    open_candidate("+34601")
    client.post("/webhook/whatsapp", data=twilio_form("SM-other", "+34601", "sí"))
    monkeypatch.setattr(settings, "demo_phones", ["+34600"])
    assert reset_path("%2B34600") in client.get(f"{RECRUITER_PREFIX}/candidates/+34600").text
    assert "/reset" not in client.get(f"{RECRUITER_PREFIX}/candidates/+34601").text
    assert client.post(reset_path("+34601"), follow_redirects=False).status_code == 403
    assert client.post(reset_path("nope"), follow_redirects=False).status_code == 403
    monkeypatch.setattr(settings, "demo_phones", ["nope"])
    assert client.post(reset_path("nope"), follow_redirects=False).status_code == 404


def test_reset_archives_the_candidate_and_frees_the_phone(client, monkeypatch):
    screen_no_licence(client, "+34600111222")
    monkeypatch.setattr(settings, "demo_phones", ["+34600111222"])
    response = client.post(reset_path("+34600111222"), follow_redirects=False)
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith(f"{RECRUITER_PREFIX}/candidates/%2B34600111222")
    page = client.get(location).text
    assert "Archived" in page
    assert "/reset" not in page
    assert "no tengo carnet" in page
    assert "Demo reset" in page
    assert client.get("/candidates/+34600111222").status_code == 404
    assert "+34600111222" not in client.get(LIST).text
    api.app.dependency_overrides[api.get_whatsapp_outbound] = lambda: FakeOutbound()
    started = client.post("/candidates", json={"phone": "+34600111222", "language": "es"})
    assert started.status_code == 201, started.text


def test_reset_form_needs_the_csrf_token_from_the_page(client, email, signed, monkeypatch):
    log_in(client, email)
    screen_no_licence(client, "+34600")
    monkeypatch.setattr(settings, "demo_phones", ["+34600"])
    assert client.post(reset_path("+34600"), follow_redirects=False).status_code == 403
    page = client.get(f"{RECRUITER_PREFIX}/candidates/+34600").text
    marker = f'name="{CSRF_FIELD}" value="'
    token = page.split(marker, 1)[1].split('"', 1)[0]
    genuine = {CSRF_FIELD: token}
    assert (
        client.post(reset_path("+34600"), data=genuine, follow_redirects=False).status_code == 303
    )


def test_page_and_fragment_render_the_same_live_regions(client):
    open_candidate("+34601")
    client.post("/webhook/whatsapp", data=twilio_form("SM-regions", "+34601", "sí"))
    route = f"{RECRUITER_PREFIX}/candidates/+34601"
    page = client.get(route).text
    fragment = client.get(f"{route}/live").text
    regions = ("facts", "route", "transcript", "summary", "profile", "events")
    assert all(f'data-live="{region}"' in page for region in regions)
    assert all(f'data-live="{region}"' in fragment for region in regions)
    conversation = re.search(r'data-conversation="([^"]+)"', page)
    assert conversation is not None
    assert conversation.group(0) in fragment


def test_a_closed_conversation_polls_until_its_summary_arrives_or_the_wait_ends(client):
    screen_no_licence(client, "+34600")
    route = f"{RECRUITER_PREFIX}/candidates/+34600/live"
    repository = api.app.dependency_overrides[api.get_repository]()
    repository.candidates.update_one({"_id": "+34600"}, {"$unset": {"summary": ""}})
    assert 'data-poll-seconds="5"' in client.get(route).text
    stale = datetime.now(UTC) - timedelta(seconds=settings.candidate_page_summary_wait_seconds + 60)
    repository.candidates.update_one({"_id": "+34600"}, {"$set": {"updated_at": stale}})
    assert 'data-poll-seconds="0"' in client.get(route).text
