import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

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
from screening_agent.recruiter.views import transcript_views
from screening_agent.storage.repository import Repository

logger = logging.getLogger(__name__)

RECRUITER_PREFIX = "/recruiter"
LOGIN_PATH = f"{RECRUITER_PREFIX}/login"
CSRF_FIELD = "csrf_token"
STATUSES = list(Status)
STAGES = list(Stage)
LOGIN_SUBJECT = "Your Grupo Sazón recruiter login link"
LOGIN_BODY = (
    "Open this link to sign in to the recruiter console. It works once and expires in "
    "{minutes:g} minutes.\n\n{link}\n\nIf you did not ask for it, ignore this email."
)

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


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


def login_page(request: Request, error: str | None = None, status_code: int = 200) -> Response:
    return templates.TemplateResponse(
        request, "login.html", {"error": error}, status_code=status_code
    )


@recruiter_router.get("/login")
def login_form(request: Request) -> Response:
    session_secret()
    return login_page(request)


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
    email = email.strip().lower()
    valid = is_valid_email(email)
    if valid and email_domain_allowed(email, settings.recruiter_email_domains):
        client_ip = request.client.host if request.client else "unknown"
        send_login_link(email, client_ip, base_url, repository, sender)
    return templates.TemplateResponse(
        request, "check_inbox.html", {"email": email if valid else None}
    )


def send_login_link(
    email: str, client_ip: str, base_url: str, repository: Repository, sender: EmailSender
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
    body = LOGIN_BODY.format(
        minutes=settings.login_link_minutes, link=f"{base_url}{LOGIN_PATH}/{token}"
    )
    try:
        sender.send(email, LOGIN_SUBJECT, body)
    except EmailSendError:
        logger.exception("login email failed")


LINK_USED = "That link has expired or was already used"


@recruiter_router.get("/login/{token}")
def confirm_login_page(
    request: Request, token: str, repository: Repository = Depends(get_repository)
) -> Response:
    """Mail scanners prefetch links; the GET only shows a button and the POST consumes the token."""
    session_secret()
    if not repository.login_token_is_live(hash_secret(token), datetime.now(UTC)):
        return login_page(request, LINK_USED, 401)
    return templates.TemplateResponse(
        request, "confirm_login.html", {"action": f"{LOGIN_PATH}/{token}"}
    )


@recruiter_router.post("/login/{token}")
def login_with_link(
    request: Request, token: str, repository: Repository = Depends(get_repository)
) -> Response:
    secret = session_secret()
    email = repository.consume_login_token(hash_secret(token), datetime.now(UTC))
    if email is None:
        return login_page(request, LINK_USED, 401)
    recruiter = repository.get_recruiter(email)
    if recruiter is None or not recruiter.active:
        return login_page(request, "This account is not active", 401)
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
            "candidate": candidate,
            "transcript": transcript_views(candidate.transcript),
            "refresh_seconds": (
                settings.candidate_page_refresh_seconds
                if candidate.status == Status.IN_PROGRESS
                else 0
            ),
            "profile_json": json.dumps(candidate.profile, indent=2, ensure_ascii=False),
            "statuses": STATUSES,
            "stages": STAGES,
            "principal": principal,
            "csrf_field": CSRF_FIELD,
            "csrf_token": session_csrf_token(principal, recruiter_session),
        },
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


recruiter_router.include_router(authenticated_pages)
