from collections import Counter
from pathlib import Path
from typing import Any

from langchain_core.messages import messages_from_dict, messages_to_dict
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from screening_agent.config import settings
from screening_agent.flow.state import ScreeningState, initial_state, stage_of
from screening_agent.storage.models import Candidate, Conversation, Event, Message, utcnow


class Repository:
    def __init__(self, database_url: str | None = None) -> None:
        database_url = database_url or settings.database_url
        _ensure_sqlite_directory(database_url)
        self.engine = create_engine(database_url, **_sqlite_engine_options(database_url))
        SQLModel.metadata.create_all(self.engine)

    def load_state(self, candidate_id: str) -> ScreeningState:
        with Session(self.engine) as session:
            conversation = self._conversation(session, candidate_id)
            if conversation is None:
                return initial_state(candidate_id)
            state = dict(conversation.state)
            state["messages"] = messages_from_dict(state.get("messages", []))
            return state  # type: ignore[return-value]

    def has_message(self, external_id: str) -> bool:
        with Session(self.engine) as session:
            return (
                session.exec(select(Message.id).where(Message.external_id == external_id)).first()
                is not None
            )

    def save_turn(
        self, state: ScreeningState, channel: str, inbound: str, reply: str, external_id: str | None
    ) -> None:
        """One transaction for inbound message, state and reply, so a failed turn leaves no dedupe row."""
        candidate_id = state["candidate_id"]
        with Session(self.engine) as session:
            session.add(
                Message(
                    candidate_id=candidate_id,
                    direction="in",
                    channel=channel,
                    body=inbound,
                    external_id=external_id,
                )
            )
            self._write_state(session, state, channel)
            if reply:
                session.add(
                    Message(candidate_id=candidate_id, direction="out", channel=channel, body=reply)
                )
            session.commit()

    def record_message(
        self,
        candidate_id: str,
        direction: str,
        channel: str,
        body: str,
        external_id: str | None = None,
    ) -> None:
        with Session(self.engine) as session:
            session.add(
                Message(
                    candidate_id=candidate_id,
                    direction=direction,
                    channel=channel,
                    body=body,
                    external_id=external_id,
                )
            )
            session.commit()

    def record_event(self, candidate_id: str, kind: str, payload: dict[str, Any]) -> None:
        with Session(self.engine) as session:
            session.add(Event(candidate_id=candidate_id, kind=kind, payload=payload))
            session.commit()

    def set_summary(self, candidate_id: str, summary: str) -> None:
        with Session(self.engine) as session:
            candidate = session.get(Candidate, candidate_id)
            if candidate:
                candidate.summary = summary
                session.add(candidate)
                session.commit()

    def override(
        self, candidate_id: str, status: str | None, notes: str | None
    ) -> Candidate | None:
        """Writes the new status into the live conversation state too, so the flow engine honours it."""
        with Session(self.engine) as session:
            candidate = session.get(Candidate, candidate_id)
            if candidate is None:
                return None
            if status:
                candidate.status = status
                candidate.disqualify_reason = None
                candidate.review_reason = None
                conversation = self._conversation(session, candidate_id)
                if conversation is not None:
                    conversation.state = {
                        **conversation.state,
                        "status": status,
                        "disqualify_reason": None,
                        "review_reason": None,
                    }
                    conversation.updated_at = utcnow()
                    session.add(conversation)
            if notes is not None:
                candidate.recruiter_notes = notes
            candidate.updated_at = utcnow()
            session.add(candidate)
            session.commit()
            session.refresh(candidate)
            return candidate

    def list_candidates(
        self, status: str | None = None, stage: str | None = None
    ) -> list[Candidate]:
        query = select(Candidate)
        if status:
            query = query.where(Candidate.status == status)
        if stage:
            query = query.where(Candidate.stage == stage)
        with Session(self.engine) as session:
            return list(session.exec(query.order_by(Candidate.updated_at.desc())))

    def get_candidate(self, candidate_id: str) -> Candidate | None:
        with Session(self.engine) as session:
            return session.get(Candidate, candidate_id)

    def funnel(self) -> dict[str, dict[str, int]]:
        with Session(self.engine) as session:
            rows = session.exec(select(Candidate.status, Candidate.stage)).all()
        return {
            "by_status": dict(Counter(status for status, _ in rows)),
            "by_stage": dict(Counter(stage for _, stage in rows)),
        }

    @staticmethod
    def _conversation(session: Session, candidate_id: str) -> Conversation | None:
        return session.exec(
            select(Conversation).where(Conversation.candidate_id == candidate_id)
        ).first()

    def _write_state(self, session: Session, state: ScreeningState, channel: str) -> None:
        candidate_id = state["candidate_id"]
        serialisable: dict[str, Any] = {**state, "messages": messages_to_dict(state["messages"])}
        candidate = session.get(Candidate, candidate_id) or Candidate(id=candidate_id)
        candidate.status = str(state.get("status", "in_progress"))
        candidate.stage = stage_of(state).value
        candidate.disqualify_reason = str_or_none(state.get("disqualify_reason"))
        candidate.review_reason = str_or_none(state.get("review_reason"))
        candidate.profile = state.get("profile", {})
        candidate.updated_at = utcnow()
        session.add(candidate)
        conversation = self._conversation(session, candidate_id) or Conversation(
            candidate_id=candidate_id, channel=channel
        )
        conversation.state = serialisable
        conversation.channel = channel
        conversation.updated_at = utcnow()
        session.add(conversation)


def str_or_none(value: Any) -> str | None:
    return None if value is None else str(value)


def _ensure_sqlite_directory(database_url: str) -> None:
    prefix = "sqlite:///"
    if database_url.startswith(prefix) and ":memory:" not in database_url:
        Path(database_url[len(prefix) :]).parent.mkdir(parents=True, exist_ok=True)


def _sqlite_engine_options(database_url: str) -> dict[str, Any]:
    if not database_url.startswith("sqlite"):
        return {}
    # FastAPI serves requests from worker threads; an in-memory database needs one shared connection.
    options: dict[str, Any] = {"connect_args": {"check_same_thread": False}}
    if ":memory:" in database_url or database_url.endswith("sqlite://"):
        options["poolclass"] = StaticPool
    return options
