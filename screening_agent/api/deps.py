import hmac
from functools import cache

from fastapi import Cookie, Header, HTTPException

from screening_agent.channels.whatsapp import OutboundNotConfiguredError, TwilioWhatsAppSender
from screening_agent.config import settings
from screening_agent.flow.engine import OutboundChannel, ScreeningEngine
from screening_agent.storage.repository import Repository

RECRUITER_COOKIE = "recruiter_key"


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


def recruiter_key_is_valid(presented: str | None) -> bool:
    """Fails closed with 503 when no key is configured, unless dev mode is on."""
    if settings.recruiter_api_key is None:
        if settings.dev_mode:
            return True
        raise HTTPException(status_code=503, detail="recruiter api key not configured")
    if presented is None:
        return False
    return hmac.compare_digest(presented.encode(), settings.recruiter_api_key.encode())


def require_recruiter(
    x_api_key: str | None = Header(default=None),
    recruiter_key: str | None = Cookie(default=None, alias=RECRUITER_COOKIE),
) -> None:
    """JSON routes take the header from API clients or the cookie the recruiter UI login set."""
    if not recruiter_key_is_valid(x_api_key or recruiter_key):
        raise HTTPException(status_code=401, detail="recruiter api key required")
