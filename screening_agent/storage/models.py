from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(UTC)


class Candidate(BaseModel):
    """Recruiter-facing projection of the candidate document; the engine state is not exposed."""

    id: str
    status: str = "in_progress"
    stage: str = "consent"
    disqualify_reason: str | None = None
    review_reason: str | None = None
    profile: dict[str, Any] = Field(default_factory=dict)
    summary: str | None = None
    recruiter_notes: str | None = None
    created_at: datetime
    updated_at: datetime


class TranscriptEntry(BaseModel):
    direction: str
    channel: str
    body: str
    external_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class Event(BaseModel):
    """Append-only audit log; disqualifications and overrides must be reconstructible from here alone."""

    candidate_id: str
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
