import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Cookie, Depends, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from screening_agent.api.auth import (
    Principal,
    email_domain_allowed,
    hash_secret,
    is_valid_email,
    issue_session,
    new_login_token,
)
from screening_agent.api.deps import (
    RECRUITER_COOKIE,
    get_email_sender,
    get_engine,
    get_repository,
    login_base_url,
    recruiter_from_cookie,
    secure_cookies,
    session_csrf_token,
    session_secret,
    verify_csrf,
)
from screening_agent.channels.email import EmailSender, EmailSendError
from screening_agent.config import settings
from screening_agent.domain.enums import Stage, Status
from screening_agent.flow.engine import ScreeningEngine
from screening_agent.recruiter.i18n import (
    LOCALE_COOKIE,
    LOCALE_COOKIE_MAX_AGE,
    STRINGS,
    Locale,
    parse_locale,
    resolve_locale,
)
from screening_agent.recruiter.labels import label
from screening_agent.recruiter.views import event_views, profile_rows, transcript_views
from screening_agent.storage.models import CandidateDetail
from screening_agent.storage.repository import Repository

logger = logging.getLogger(__name__)

RECRUITER_PREFIX = "/recruiter"
LOGIN_PATH = f"{RECRUITER_PREFIX}/login"
CSRF_FIELD = "csrf_token"
STATUSES = list(Status)
STAGES = list(Stage)
LOCALES = list(Locale)

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.filters["label"] = label


def require_recruiter_page(
    recruiter_session: str | None = Cookie(default=None, alias=RECRUITER_COOKIE),
    repository: Repository = Depends(get_repository),
) -> Principal:
    """A browser without a valid session is sent to the login form instead of a 401."""
    principal = recruiter_from_cookie(recruiter_session, repository)
    if principal is None:
        raise HTTPException(status_code=303, headers={"Location": LOGIN_PATH})
    return principal


recruiter_router = APIRouter(prefix=RECRUITER_PREFIX, tags=["recruiter"])
authenticated_pages = APIRouter()


def current_locale(request: Request) -> Locale:
    return resolve_locale(
        request.query_params.get("lang"),
        request.cookies.get(LOCALE_COOKIE),
        request.headers.get("accept-language"),
    )


def locale_context(locale: Locale) -> dict[str, object]:
    return {
        "t": STRINGS[locale],
        "strings": STRINGS,
        "locale": locale,
        "locales": LOCALES,
        "lang": locale.value,
    }


LoginErrorKey = Literal["error_link_used", "error_inactive"]


def login_page(
    request: Request,
    locale: Locale,
    error_key: LoginErrorKey | None = None,
    status_code: int = 200,
) -> Response:
    error = STRINGS[locale][error_key] if error_key else None
    return templates.TemplateResponse(
        request, "login.html", {"error": error, **locale_context(locale)}, status_code=status_code
    )


@recruiter_router.get("/login")
def login_form(request: Request) -> Response:
    """A valid ?lang= choice is remembered in a cookie so the whole login flow keeps it."""
    session_secret()
    locale = current_locale(request)
    response = login_page(request, locale)
    if parse_locale(request.query_params.get("lang")) is not None:
        response.set_cookie(
            LOCALE_COOKIE,
            locale.value,
            max_age=LOCALE_COOKIE_MAX_AGE,
            samesite="lax",
            secure=secure_cookies(request),
        )
    return response


@recruiter_router.post("/login")
def request_login_link(
    request: Request,
    email: str = Form(),
    repository: Repository = Depends(get_repository),
    sender: EmailSender = Depends(get_email_sender),
) -> Response:
    """Always answers "check your inbox" so the form cannot be used to list recruiters or probe the
    domain allowlist. Only an invited, active address at an allowed domain gets a link."""
    session_secret()
    base_url = login_base_url(request)
    locale = current_locale(request)
    email = email.strip().lower()
    valid = is_valid_email(email)
    if valid and email_domain_allowed(email, settings.recruiter_email_domains):
        client_ip = request.client.host if request.client else "unknown"
        send_login_link(email, client_ip, base_url, locale, repository, sender)
    return templates.TemplateResponse(
        request,
        "check_inbox.html",
        {"email": email if valid else None, **locale_context(locale)},
    )


def send_login_link(
    email: str,
    client_ip: str,
    base_url: str,
    locale: Locale,
    repository: Repository,
    sender: EmailSender,
) -> None:
    recruiter = repository.get_recruiter(email)
    if recruiter is None or not recruiter.active:
        return
    now = datetime.now(UTC)
    if not repository.try_acquire_login_slot(
        email,
        client_ip,
        now,
        timedelta(seconds=settings.login_email_cooldown_seconds),
        settings.login_requests_per_ip,
        timedelta(minutes=settings.login_ip_window_minutes),
    ):
        logger.warning("login link throttled")
        return
    token = new_login_token()
    expires_at = now + timedelta(minutes=settings.login_link_minutes)
    repository.save_login_token(hash_secret(token), email, expires_at)
    strings = STRINGS[locale]
    body = strings["email_body"].format(
        minutes=settings.login_link_minutes, link=f"{base_url}{LOGIN_PATH}/{token}"
    )
    try:
        sender.send(email, strings["email_subject"], body)
    except EmailSendError:
        logger.exception("login email failed")


@recruiter_router.get("/login/{token}")
def confirm_login_page(
    request: Request, token: str, repository: Repository = Depends(get_repository)
) -> Response:
    """Mail scanners prefetch links; the GET only shows a button and the POST consumes the token."""
    session_secret()
    locale = current_locale(request)
    if not repository.login_token_is_live(hash_secret(token), datetime.now(UTC)):
        return login_page(request, locale, "error_link_used", 401)
    return templates.TemplateResponse(
        request,
        "confirm_login.html",
        {"action": f"{LOGIN_PATH}/{token}", **locale_context(locale)},
    )


@recruiter_router.post("/login/{token}")
def login_with_link(
    request: Request, token: str, repository: Repository = Depends(get_repository)
) -> Response:
    secret = session_secret()
    locale = current_locale(request)
    email = repository.consume_login_token(hash_secret(token), datetime.now(UTC))
    if email is None:
        return login_page(request, locale, "error_link_used", 401)
    recruiter = repository.get_recruiter(email)
    if recruiter is None or not recruiter.active:
        return login_page(request, locale, "error_inactive", 401)
    repository.mark_recruiter_login(email)
    response = RedirectResponse(f"{RECRUITER_PREFIX}/", status_code=303)
    # Dev mode without a secret has no sessions to issue; the pages are open anyway.
    if secret is not None:
        response.set_cookie(
            RECRUITER_COOKIE,
            issue_session(email, secret, settings.session_hours),
            max_age=int(settings.session_hours * 3600),
            httponly=True,
            samesite="lax",
            secure=secure_cookies(request),
        )
    return response


@recruiter_router.post("/logout")
def logout() -> Response:
    response = RedirectResponse(LOGIN_PATH, status_code=303)
    response.delete_cookie(RECRUITER_COOKIE)
    return response


@authenticated_pages.get("/")
def candidate_list(
    request: Request,
    status: str | None = None,
    stage: str | None = None,
    repository: Repository = Depends(get_repository),
    principal: Principal = Depends(require_recruiter_page),
) -> Response:
    return templates.TemplateResponse(
        request,
        "candidates.html",
        {
            "candidates": repository.list_candidates(status=status, stage=stage),
            "funnel": repository.funnel(),
            "status": status,
            "stage": stage,
            "statuses": STATUSES,
            "stages": STAGES,
            "principal": principal,
        },
    )


def keeps_polling(candidate: CandidateDetail) -> bool:
    """A closed conversation keeps polling briefly: the summary is written after the outcome."""
    if candidate.archived_at is not None:
        return False
    if candidate.status == Status.IN_PROGRESS:
        return True
    summary_settled = candidate.summary is not None or any(
        event.kind == "summary_failed" for event in candidate.events
    )
    waited = datetime.now(UTC) - candidate.updated_at
    return not summary_settled and waited < timedelta(
        seconds=settings.candidate_page_summary_wait_seconds
    )


def live_context(candidate: CandidateDetail) -> dict[str, object]:
    """What the live regions render; the page and the polled fragment must agree on it."""
    return {
        "candidate": candidate,
        "transcript": transcript_views(candidate.transcript),
        "profile": profile_rows(candidate.profile),
        "events": event_views(candidate.events),
        "stages": STAGES,
        "poll_seconds": settings.candidate_page_refresh_seconds if keeps_polling(candidate) else 0,
        "conversation": candidate.created_at.isoformat(),
    }


@authenticated_pages.get("/candidates/{candidate_id}")
def candidate_page(
    request: Request,
    candidate_id: str,
    repository: Repository = Depends(get_repository),
    principal: Principal = Depends(require_recruiter_page),
    recruiter_session: str | None = Cookie(default=None, alias=RECRUITER_COOKIE),
) -> Response:
    candidate = repository.get_candidate_detail(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    return templates.TemplateResponse(
        request,
        "candidate.html",
        {
            **live_context(candidate),
            "statuses": STATUSES,
            "principal": principal,
            "csrf_field": CSRF_FIELD,
            "csrf_token": session_csrf_token(principal, recruiter_session),
            "resettable": candidate.id in settings.demo_phones,
        },
    )


@authenticated_pages.get("/candidates/{candidate_id}/live")
def candidate_live_regions(
    request: Request,
    candidate_id: str,
    repository: Repository = Depends(get_repository),
    _: Principal = Depends(require_recruiter_page),
) -> Response:
    """The regions of the candidate page that change while a conversation is open, without the forms."""
    candidate = repository.get_candidate_detail(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    return templates.TemplateResponse(
        request,
        "candidate_live.html",
        live_context(candidate),
        headers={"Cache-Control": "no-store"},
    )


@authenticated_pages.post("/candidates/{candidate_id}/override")
def override_form(
    candidate_id: str,
    status: str = Form(default=""),
    notes: str = Form(default=""),
    csrf_token: str = Form(default="", alias=CSRF_FIELD),
    repository: Repository = Depends(get_repository),
    principal: Principal = Depends(require_recruiter_page),
    recruiter_session: str | None = Cookie(default=None, alias=RECRUITER_COOKIE),
) -> Response:
    """An empty status keeps the current one; an empty textarea clears the notes."""
    verify_csrf(principal, csrf_token, recruiter_session)
    try:
        new_status = Status(status) if status else None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"unknown status {status!r}") from exc
    if repository.override(candidate_id, new_status, notes, principal.label) is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    return RedirectResponse(f"{RECRUITER_PREFIX}/candidates/{candidate_id}", status_code=303)


@authenticated_pages.post("/candidates/{candidate_id}/reset")
def reset_form(
    candidate_id: str,
    csrf_token: str = Form(default="", alias=CSRF_FIELD),
    engine: ScreeningEngine = Depends(get_engine),
    principal: Principal = Depends(require_recruiter_page),
    recruiter_session: str | None = Cookie(default=None, alias=RECRUITER_COOKIE),
) -> Response:
    """Demo only: archives the conversation under a new id so the same phone can start again."""
    verify_csrf(principal, csrf_token, recruiter_session)
    if candidate_id not in settings.demo_phones:
        raise HTTPException(status_code=403, detail="candidate is not a demo phone")
    archive_id = engine.archive_candidate(candidate_id, principal.label)
    if archive_id is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    return RedirectResponse(
        f"{RECRUITER_PREFIX}/candidates/{quote(archive_id, safe='')}", status_code=303
    )


recruiter_router.include_router(authenticated_pages)
