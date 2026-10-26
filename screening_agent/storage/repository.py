from collections import Counter
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import messages_from_dict, messages_to_dict
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.database import Database
from pymongo.uri_parser import parse_uri

from screening_agent.config import settings
from screening_agent.domain.enums import Language, Status
from screening_agent.flow.silence import SilenceCandidate
from screening_agent.flow.state import ScreeningState, initial_state, stage_of
from screening_agent.storage.models import Candidate, Event, TranscriptEntry, utcnow


class StaleStateError(RuntimeError):
    """Another writer saved this conversation after the caller loaded it."""


class DuplicateMessageError(RuntimeError):
    """The inbound external id is already in the transcript."""


class Repository:
    """One document per candidate: recruiter fields, engine state, silence timing and the transcript.
    A turn is one conditional update on that document, which is the atomicity the flow needs."""

    def __init__(self, database_url: str | None = None) -> None:
        database_url = database_url or settings.database_url
        database_name = parse_uri(database_url)["database"]
        if not database_name:
            raise ValueError("database_url must name a database, e.g. mongodb://host/screening")
        self.client: MongoClient = MongoClient(database_url, tz_aware=True)
        self.db: Database = self.client[database_name]
        self.candidates = self.db["candidates"]
        self.events = self.db["events"]
        self.candidates.create_index([("transcript.external_id", ASCENDING)])
        self.candidates.create_index([("status", ASCENDING), ("updated_at", DESCENDING)])
        self.candidates.create_index([("stage", ASCENDING)])
        self.events.create_index([("candidate_id", ASCENDING), ("created_at", ASCENDING)])

    def load_state(self, candidate_id: str) -> ScreeningState:
        document = self.candidates.find_one({"_id": candidate_id}, {"state": 1, "version": 1})
        if document is None:
            return initial_state(candidate_id)
        state = dict(document["state"])
        state["messages"] = messages_from_dict(state.get("messages", []))
        state["version"] = document["version"]
        return state  # type: ignore[return-value]

    def conversation_exists(self, candidate_id: str) -> bool:
        return self.candidates.count_documents({"_id": candidate_id}, limit=1) == 1

    def has_message(self, external_id: str) -> bool:
        return (
            self.candidates.count_documents({"transcript.external_id": external_id}, limit=1) == 1
        )

    def save_turn(
        self, state: ScreeningState, channel: str, inbound: str, reply: str, external_id: str | None
    ) -> None:
        """One update for inbound, state and reply, so a failed turn leaves no dedupe entry."""
        if external_id and self.has_message(external_id):
            raise DuplicateMessageError(external_id)
        entries = [_entry(channel, "in", inbound, external_id)]
        if reply:
            entries.append(_entry(channel, "out", reply))
        self._commit(state, channel, entries, {"last_inbound_at": utcnow(), "nudge_count": 0})

    def save_opener(self, state: ScreeningState, channel: str, text: str) -> None:
        self._commit(state, channel, [_entry(channel, "out", text)])

    def save_nudge(self, state: ScreeningState, channel: str, text: str, nudge_count: int) -> None:
        self._commit(state, channel, [_entry(channel, "out", text)], {"nudge_count": nudge_count})

    def save_state(self, state: ScreeningState, channel: str) -> None:
        self._commit(state, channel)

    def record_message(
        self,
        candidate_id: str,
        direction: str,
        channel: str,
        body: str,
        external_id: str | None = None,
    ) -> None:
        self.candidates.update_one(
            {"_id": candidate_id},
            {"$push": {"transcript": _entry(channel, direction, body, external_id).model_dump()}},
        )

    def record_event(self, candidate_id: str, kind: str, payload: dict[str, Any]) -> None:
        self.events.insert_one(
            Event(candidate_id=candidate_id, kind=kind, payload=payload).model_dump()
        )

    def set_summary(self, candidate_id: str, summary: str) -> None:
        self.candidates.update_one({"_id": candidate_id}, {"$set": {"summary": summary}})

    def override(
        self, candidate_id: str, status: str | None, notes: str | None
    ) -> Candidate | None:
        """Writes the new status into the live state too, so the engine honours it. Reopening resets
        the silence clock, otherwise the next sweep abandons the candidate again."""
        changes: dict[str, Any] = {"updated_at": utcnow()}
        if status:
            changes.update(
                {
                    "status": status,
                    "disqualify_reason": None,
                    "review_reason": None,
                    "state.status": status,
                    "state.disqualify_reason": None,
                    "state.review_reason": None,
                }
            )
            if status == Status.IN_PROGRESS:
                changes.update({"last_inbound_at": utcnow(), "nudge_count": 0})
        if notes is not None:
            changes["recruiter_notes"] = notes
        document = self.candidates.find_one_and_update(
            {"_id": candidate_id},
            {"$set": changes, "$inc": {"version": 1}},
            return_document=True,
        )
        return None if document is None else _candidate(document)

    def list_candidates(
        self, status: str | None = None, stage: str | None = None
    ) -> list[Candidate]:
        query: dict[str, Any] = {}
        if status:
            query["status"] = status
        if stage:
            query["stage"] = stage
        cursor = self.candidates.find(query, _CANDIDATE_FIELDS).sort("updated_at", DESCENDING)
        return [_candidate(document) for document in cursor]

    def get_candidate(self, candidate_id: str) -> Candidate | None:
        document = self.candidates.find_one({"_id": candidate_id}, _CANDIDATE_FIELDS)
        return None if document is None else _candidate(document)

    def open_conversations(self) -> list[SilenceCandidate]:
        cursor = self.candidates.find({"status": Status.IN_PROGRESS.value}, _SILENCE_FIELDS)
        return [_silence_candidate(document) for document in cursor]

    def silence_candidate(self, candidate_id: str) -> SilenceCandidate | None:
        document = self.candidates.find_one({"_id": candidate_id}, _SILENCE_FIELDS)
        return None if document is None else _silence_candidate(document)

    def funnel(self) -> dict[str, dict[str, int]]:
        rows = list(self.candidates.find({}, {"status": 1, "stage": 1}))
        return {
            "by_status": dict(Counter(row["status"] for row in rows)),
            "by_stage": dict(Counter(row["stage"] for row in rows)),
        }

    def _commit(
        self,
        state: ScreeningState,
        channel: str,
        entries: list[TranscriptEntry] | None = None,
        timing: dict[str, Any] | None = None,
    ) -> None:
        """Conditional on the loaded version: a writer that loaded an older version loses."""
        candidate_id = state["candidate_id"]
        expected = state.get("version", 0)
        now = utcnow()
        fields = {
            "status": str(state.get("status", "in_progress")),
            "stage": stage_of(state).value,
            "disqualify_reason": str_or_none(state.get("disqualify_reason")),
            "review_reason": str_or_none(state.get("review_reason")),
            "profile": state.get("profile", {}),
            "channel": channel,
            "version": expected + 1,
            "state": {
                **state,
                "messages": messages_to_dict(state["messages"]),
                "version": expected + 1,
            },
            "updated_at": now,
            **(timing or {}),
        }
        update: dict[str, Any] = {
            "$set": fields,
            "$setOnInsert": {
                "created_at": now,
                "opened_at": now,
                "summary": None,
                "recruiter_notes": None,
            },
        }
        if entries:
            update["$push"] = {"transcript": {"$each": [e.model_dump() for e in entries]}}
        if not (timing and "last_inbound_at" in timing):
            update["$setOnInsert"]["last_inbound_at"] = None
        if not (timing and "nudge_count" in timing):
            update["$setOnInsert"]["nudge_count"] = 0
        if expected == 0:
            if self.conversation_exists(candidate_id):
                raise StaleStateError(f"{candidate_id}: created by another writer")
            self.candidates.update_one({"_id": candidate_id}, update, upsert=True)
            return
        result = self.candidates.update_one({"_id": candidate_id, "version": expected}, update)
        if result.matched_count == 0:
            raise StaleStateError(f"{candidate_id}: version {expected} no longer current")


_CANDIDATE_FIELDS = {"state": 0, "transcript": 0}
_SILENCE_FIELDS = {
    "channel": 1,
    "state.language": 1,
    "opened_at": 1,
    "last_inbound_at": 1,
    "nudge_count": 1,
}


def str_or_none(value: Any) -> str | None:
    return None if value is None else str(value)


def _entry(
    channel: str, direction: str, body: str, external_id: str | None = None
) -> TranscriptEntry:
    return TranscriptEntry(direction=direction, channel=channel, body=body, external_id=external_id)


def _candidate(document: dict[str, Any]) -> Candidate:
    return Candidate(id=document["_id"], **{k: v for k, v in document.items() if k != "_id"})


def _silence_candidate(document: dict[str, Any]) -> SilenceCandidate:
    return SilenceCandidate(
        candidate_id=document["_id"],
        channel=document["channel"],
        language=Language(document.get("state", {}).get("language", Language.ES)),
        opened_at=_as_utc(document["opened_at"]),  # type: ignore[arg-type]
        last_inbound_at=_as_utc(document.get("last_inbound_at")),
        nudge_count=document.get("nudge_count", 0),
    )


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)
