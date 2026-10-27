import logging
from functools import cache

from fastapi import Cookie, Depends, Header, HTTPException, Request

from screening_agent.api.auth import (
    Principal,
    PrincipalKind,
    client_from_api_key,
    csrf_matches,
    csrf_token,
    is_valid_email,
    recruiter_from_session,
)
from screening_agent.channels.email import (
    EmailNotConfiguredError,
    EmailSender,
    LoggingEmailSender,
    RedirectingEmailSender,
    SendGridEmailSender,
)
from screening_agent.channels.whatsapp import OutboundNotConfiguredError, TwilioWhatsAppSender
from screening_agent.config import settings
from screening_agent.flow.engine import OutboundChannel, ScreeningEngine
from screening_agent.storage.repository import Repository

logger = logging.getLogger(__name__)

RECRUITER_COOKIE = "recruiter_session"
CSRF_HEADER = "X-CSRF-Token"
DEV_PRINCIPAL = Principal(PrincipalKind.DEV, "dev-mode")


@cache
def get_repository() -> Repository:
    return Repository()


@cache
def get_engine() -> ScreeningEngine:
    return ScreeningEngine(get_repository())


@cache
def whatsapp_sender() -> TwilioWhatsAppSender:
    return TwilioWhatsAppSender.from_settings()


def get_whatsapp_outbound() -> OutboundChannel:
    try:
        return whatsapp_sender()
    except OutboundNotConfiguredError as exc:
        raise HTTPException(
            status_code=503, detail=f"whatsapp outbound not configured: {exc}"
        ) from exc


@cache
def email_sender() -> EmailSender:
    try:
        sender: EmailSender = SendGridEmailSender.from_settings()
    except EmailNotConfiguredError:
        if not settings.dev_mode:
            raise
        sender = LoggingEmailSender()
    return redirect_login_email(sender)


def redirect_login_email(sender: EmailSender) -> EmailSender:
    """A redirect outside dev mode would send every recruiter's link to one mailbox, so it fails closed."""
    redirect_to = settings.login_email_redirect_to
    if redirect_to is None:
        return sender
    if not settings.dev_mode:
        raise EmailNotConfiguredError(
            "SCREENING_LOGIN_EMAIL_REDIRECT_TO is allowed in dev mode only"
        )
    if not is_valid_email(redirect_to):
        raise EmailNotConfiguredError("SCREENING_LOGIN_EMAIL_REDIRECT_TO is not an email address")
    return RedirectingEmailSender(sender, redirect_to)


def get_email_sender() -> EmailSender:
    try:
        return email_sender()
    except EmailNotConfiguredError as exc:
        # The login form is public, so the missing setting names go to the log, not the response.
        logger.error("login email not configured: %s", exc)
        raise HTTPException(status_code=503, detail="login email not configured") from exc


def session_secret() -> str | None:
    """Fails closed with 503 when no session secret is configured, unless dev mode is on."""
    if settings.session_secret is None:
        if settings.dev_mode:
            return None
        raise HTTPException(status_code=503, detail="session secret not configured")
    return settings.session_secret.get_secret_value()


def login_base_url(request: Request) -> str:
    """The Host header is attacker-controlled, so only dev mode may fall back to it."""
    if settings.public_url:
        return settings.public_url.rstrip("/")
    if settings.dev_mode:
        return str(request.base_url).rstrip("/")
    raise HTTPException(status_code=503, detail="public url not configured")


def secure_cookies(request: Request) -> bool:
    """Follows the public URL scheme, not the request's, which is plain http behind a TLS proxy."""
    return login_base_url(request).startswith("https://")


def recruiter_from_cookie(cookie: str | None, repository: Repository) -> Principal | None:
    """Dev mode without a secret admits everyone; otherwise the cookie must hold a live session."""
    secret = session_secret()
    if secret is None:
        return DEV_PRINCIPAL
    return recruiter_from_session(cookie, secret, settings.recruiter_email_domains, repository)


def session_csrf_token(principal: Principal, cookie: str | None) -> str | None:
    """Only a cookie session has a token; an API key or the dev principal is never sent ambiently."""
    if principal.kind is not PrincipalKind.RECRUITER or not cookie:
        return None
    secret = session_secret()
    return None if secret is None else csrf_token(cookie, secret)


def verify_csrf(principal: Principal, presented: str, cookie: str | None) -> None:
    """Fails closed: a cookie principal whose token cannot be derived is refused."""
    if principal.kind is not PrincipalKind.RECRUITER:
        return
    expected = session_csrf_token(principal, cookie)
    if expected is None or not csrf_matches(presented, expected):
        raise HTTPException(status_code=403, detail="csrf token missing or invalid")


def require_recruiter(
    x_api_key: str | None = Header(default=None),
    recruiter_session: str | None = Cookie(default=None, alias=RECRUITER_COOKIE),
    repository: Repository = Depends(get_repository),
) -> Principal:
    """JSON routes take a per-client API key in the header or the session cookie the login set."""
    principal = client_from_api_key(x_api_key, repository) or recruiter_from_cookie(
        recruiter_session, repository
    )
    if principal is None:
        raise HTTPException(status_code=401, detail="recruiter login or api key required")
    return principal


def require_recruiter_write(
    principal: Principal = Depends(require_recruiter),
    recruiter_session: str | None = Cookie(default=None, alias=RECRUITER_COOKIE),
    presented_csrf: str = Header(default="", alias=CSRF_HEADER),
) -> Principal:
    """SameSite=Lax still sends the cookie from sibling subdomains, so a cookie writer must also
    echo the CSRF token."""
    verify_csrf(principal, presented_csrf, recruiter_session)
    return principal
