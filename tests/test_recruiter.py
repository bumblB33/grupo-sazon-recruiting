from screening_agent.api.deps import RECRUITER_COOKIE
from screening_agent.config import settings
from screening_agent.recruiter.router import LOGIN_PATH, RECRUITER_PREFIX
from tests.conftest import screen_no_licence, twilio_form

LIST = f"{RECRUITER_PREFIX}/"


def test_pages_redirect_to_login_without_cookie(client, monkeypatch):
    monkeypatch.setattr(settings, "recruiter_api_key", "secret")
    response = client.get(LIST, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == LOGIN_PATH
    assert client.get(LOGIN_PATH).status_code == 200


def test_login_sets_cookie_then_pages_render(client, monkeypatch):
    monkeypatch.setattr(settings, "recruiter_api_key", "secret")
    wrong = client.post(LOGIN_PATH, data={"key": "nope"}, follow_redirects=False)
    assert wrong.status_code == 401
    assert "Wrong key" in wrong.text
    assert client.post(LOGIN_PATH, data={"key": "sé"}, follow_redirects=False).status_code == 401
    right = client.post(LOGIN_PATH, data={"key": "secret"}, follow_redirects=False)
    assert right.status_code == 303
    assert right.headers["location"] == LIST
    assert f"{RECRUITER_COOKIE}=secret" in right.headers["set-cookie"]
    assert "HttpOnly" in right.headers["set-cookie"]
    assert client.get(LIST).status_code == 200
    client.post(f"{RECRUITER_PREFIX}/logout", follow_redirects=False)
    assert client.get(LIST, follow_redirects=False).status_code == 303


def test_pages_fail_closed_without_key_outside_dev_mode(client, monkeypatch):
    monkeypatch.setattr(settings, "dev_mode", False)
    assert client.get(LIST).status_code == 503
    assert client.post(LOGIN_PATH, data={"key": "x"}).status_code == 503


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
