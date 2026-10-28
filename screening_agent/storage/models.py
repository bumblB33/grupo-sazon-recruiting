from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from screening_agent.domain.enums import MessageKind
from screening_agent.flow.turn_record import TurnRecord


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
    # The name on the application, from the client that opened the conversation; not what the candidate said.
    applicant_name: str | None = None
    # What the agent flagged for a recruiter to check, and what the candidate asked to pass on.
    concerns: list[str] = Field(default_factory=list)
    candidate_questions: list[str] = Field(default_factory=list)
    summary: str | None = None
    recruiter_notes: str | None = None
    created_at: datetime
    updated_at: datetime
    # Set on the copy a demo reset leaves behind; the live id is free again.
    archived_at: datetime | None = None
    archived_by: str | None = None


class TranscriptEntry(BaseModel):
    direction: str
    channel: str
    body: str
    external_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    # Set on inbound entries the engine answered; closed-conversation and opener entries have none.
    turn: TurnRecord | None = None
    # Outbound entries only. Entries stored before this field existed have none and count as unanswered.
    kind: MessageKind | None = None


def unanswered_agent_messages(entries: list[TranscriptEntry]) -> int:
    """Agent messages since the last inbound one. Silence nudges are excluded from the count."""
    count = 0
    for entry in reversed(entries):
        if entry.direction == "in":
            break
        if entry.kind != MessageKind.NUDGE:
            count += 1
    return count


class Event(BaseModel):
    """Append-only audit log; disqualifications and overrides must be reconstructible from here alone."""

    candidate_id: str
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)


class Recruiter(BaseModel):
    """One row per invited person. Deactivating ends sessions issued before it and blocks new links."""

    email: str
    active: bool = True
    created_at: datetime = Field(default_factory=utcnow)
    last_login_at: datetime | None = None
    sessions_valid_after: datetime | None = None


class ApiKey(BaseModel):
    """One row per machine client; the hash of the secret is stored, the secret is shown once."""

    key_id: str
    label: str
    active: bool = True
    created_at: datetime = Field(default_factory=utcnow)


class CandidateDetail(Candidate):
    transcript: list[TranscriptEntry] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
