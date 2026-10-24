from datetime import UTC, datetime

from sqlmodel import JSON, Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


class Candidate(SQLModel, table=True):
    id: str = Field(primary_key=True)
    status: str = Field(default="in_progress", index=True)
    stage: str = Field(default="consent", index=True)
    disqualify_reason: str | None = None
    review_reason: str | None = None
    profile: dict = Field(default_factory=dict, sa_type=JSON)
    summary: str | None = None
    recruiter_notes: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Conversation(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    candidate_id: str = Field(unique=True, index=True)
    channel: str
    state: dict = Field(default_factory=dict, sa_type=JSON)
    updated_at: datetime = Field(default_factory=utcnow)


class Message(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    candidate_id: str = Field(index=True)
    external_id: str | None = Field(default=None, unique=True)
    direction: str
    channel: str
    body: str
    created_at: datetime = Field(default_factory=utcnow)


class Event(SQLModel, table=True):
    """Append-only audit log; disqualifications and overrides must be reconstructible from here alone."""

    id: int | None = Field(default=None, primary_key=True)
    candidate_id: str = Field(index=True)
    kind: str = Field(index=True)
    payload: dict = Field(default_factory=dict, sa_type=JSON)
    created_at: datetime = Field(default_factory=utcnow)
