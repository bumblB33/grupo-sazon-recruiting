import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

import jwt

from screening_agent.storage.repository import Repository

SESSION_ALGORITHM = "HS256"
API_KEY_SEPARATOR = "."
MAX_EMAIL_LENGTH = 254
EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)+")
BSON_DATETIME_RESOLUTION = timedelta(milliseconds=1)


class PrincipalKind(StrEnum):
    DEV = "dev"
    RECRUITER = "recruiter"
    API_KEY = "api_key"


@dataclass(frozen=True)
class Principal:
    """Who is acting on a recruiter route; `label` is the actor written to audit events."""

    kind: PrincipalKind
    id: str

    @property
    def label(self) -> str:
        return f"{self.kind}:{self.id}"


@dataclass(frozen=True)
class Session:
    email: str
    issued_at: datetime


def issue_session(email: str, secret: str, hours: float, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    # iat keeps sub-second precision so a deactivation in the same second still outranks it.
    claims = {"sub": email, "iat": now.timestamp(), "exp": now + timedelta(hours=hours)}
    return jwt.encode(claims, secret, algorithm=SESSION_ALGORITHM)


def read_session(token: str | None, secret: str) -> Session | None:
    """None for a missing, tampered or expired cookie."""
    if not token:
        return None
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=[SESSION_ALGORITHM],
            options={"require": ["exp", "sub", "iat"]},
        )
    except jwt.InvalidTokenError:
        return None
    return Session(str(claims["sub"]), datetime.fromtimestamp(float(claims["iat"]), UTC))


def csrf_token(session_cookie: str, secret: str) -> str:
    """Bound to the session cookie, so a token only works alongside the cookie it was derived from."""
    return hmac.new(secret.encode(), session_cookie.encode(), hashlib.sha256).hexdigest()


def new_login_token() -> str:
    return secrets.token_urlsafe(32)


def hash_secret(value: str) -> str:
    """Stored form of login tokens and API key secrets; the plaintext never reaches the database."""
    return hashlib.sha256(value.encode()).hexdigest()


def new_api_key() -> tuple[str, str, str]:
    """Returns (key id, plaintext secret, presented value). Only the presented value is shown once."""
    key_id = secrets.token_hex(6)
    secret = secrets.token_urlsafe(32)
    return key_id, secret, f"{key_id}{API_KEY_SEPARATOR}{secret}"


def split_api_key(presented: str) -> tuple[str, str] | None:
    key_id, separator, secret = presented.partition(API_KEY_SEPARATOR)
    if not separator or not key_id or not secret:
        return None
    return key_id, secret


def secret_matches(presented: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_secret(presented), stored_hash)


def is_valid_email(email: str) -> bool:
    """Rejects anything but one plain local@domain, so a crafted address never reaches the mail API."""
    return len(email) <= MAX_EMAIL_LENGTH and EMAIL_PATTERN.fullmatch(email) is not None


def email_domain_allowed(email: str, domains: list[str]) -> bool:
    _, at, domain = email.rpartition("@")
    return bool(at) and domain.lower() in {d.lower().lstrip("@") for d in domains}


def session_revoked(issued_at: datetime, valid_after: datetime | None) -> bool:
    """MongoDB truncates valid_after to the millisecond, so a session issued inside that
    millisecond may predate the deactivation and counts as revoked."""
    return valid_after is not None and issued_at < valid_after + BSON_DATETIME_RESOLUTION


def recruiter_from_session(
    cookie: str | None, secret: str, domains: list[str], repository: Repository
) -> Principal | None:
    """The cookie must verify, the recruiter must be active at an allowed domain, and no
    deactivation may postdate the cookie."""
    session = read_session(cookie, secret)
    if session is None or not email_domain_allowed(session.email, domains):
        return None
    recruiter = repository.get_recruiter(session.email)
    if recruiter is None or not recruiter.active:
        return None
    if session_revoked(session.issued_at, recruiter.sessions_valid_after):
        return None
    return Principal(PrincipalKind.RECRUITER, session.email)


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
    return Principal(PrincipalKind.API_KEY, stored[0])


def csrf_matches(presented: str, expected: str) -> bool:
    """Compares bytes: compare_digest raises TypeError on non-ASCII str, which a client controls."""
    return hmac.compare_digest(presented.encode(), expected.encode())
