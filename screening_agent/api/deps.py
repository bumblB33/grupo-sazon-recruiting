from functools import cache

from fastapi import Cookie, Depends, Header, HTTPException, Request

from screening_agent.api.auth import Principal, read_session, secret_matches, split_api_key
from screening_agent.channels.email import (
    EmailNotConfiguredError,
    EmailSender,
    LoggingEmailSender,
    SendGridEmailSender,
)
from screening_agent.channels.whatsapp import OutboundNotConfiguredError, TwilioWhatsAppSender
from screening_agent.config import settings
from screening_agent.flow.engine import OutboundChannel, ScreeningEngine
from screening_agent.storage.repository import Repository

RECRUITER_COOKIE = "recruiter_session"
DEV_PRINCIPAL = Principal("dev", "dev-mode")


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
        return SendGridEmailSender.from_settings()
    except EmailNotConfiguredError:
        if settings.dev_mode:
            return LoggingEmailSender()
        raise


def get_email_sender() -> EmailSender:
    try:
        return email_sender()
    except EmailNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=f"login email not configured: {exc}") from exc


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


def recruiter_from_cookie(cookie: str | None, repository: Repository) -> Principal | None:
    """Dev mode without a secret admits everyone. Otherwise the cookie must verify and the
    recruiter must still be active, so deactivation takes effect on the next request."""
    secret = session_secret()
    if secret is None:
        return DEV_PRINCIPAL
    email = read_session(cookie, secret)
    if email is None:
        return None
    recruiter = repository.get_recruiter(email)
    if recruiter is None or not recruiter.active:
        return None
    return Principal("recruiter", email)


def client_from_api_key(presented: str | None, repository: Repository) -> Principal | None:
    if not presented:
        return None
    parts = split_api_key(presented)
    if parts is None:
        return None
    key_id, secret = parts
    stored = repository.api_key_hash(key_id)
    if stored is None or not secret_matches(secret, stored[1]):
        return None
    return Principal("api_key", stored[0])


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
