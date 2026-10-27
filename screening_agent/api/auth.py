import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

SESSION_ALGORITHM = "HS256"
API_KEY_SEPARATOR = "."
MAX_EMAIL_LENGTH = 254
EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)+")


@dataclass(frozen=True)
class Principal:
    """Who is acting on a recruiter route: a logged-in recruiter, an API client, or dev mode."""

    kind: str
    id: str

    @property
    def label(self) -> str:
        return f"{self.kind}:{self.id}"


def issue_session(email: str, secret: str, hours: float, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    claims = {"sub": email, "iat": now, "exp": now + timedelta(hours=hours)}
    return jwt.encode(claims, secret, algorithm=SESSION_ALGORITHM)


def read_session(token: str | None, secret: str) -> str | None:
    """Returns the email, or None for a missing, tampered or expired cookie."""
    if not token:
        return None
    try:
        claims = jwt.decode(
            token, secret, algorithms=[SESSION_ALGORITHM], options={"require": ["exp", "sub"]}
        )
    except jwt.InvalidTokenError:
        return None
    return str(claims["sub"])


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
