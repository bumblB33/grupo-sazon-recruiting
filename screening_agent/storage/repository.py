from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from langchain_core.messages import messages_from_dict, messages_to_dict
from pymongo import ASCENDING, DESCENDING, MongoClient, ReturnDocument
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError
from pymongo.uri_parser import parse_uri

from screening_agent.config import settings
from screening_agent.domain.enums import Language, Status
from screening_agent.flow.silence import SilenceCandidate
from screening_agent.flow.state import ScreeningState, initial_state, stage_of
from screening_agent.storage.models import (
    ApiKey,
    Candidate,
    CandidateDetail,
    Event,
    Recruiter,
    TranscriptEntry,
    utcnow,
)


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
        self.recruiters = self.db["recruiters"]
        self.login_tokens = self.db["login_tokens"]
        self.login_throttles = self.db["login_throttles"]
        self.api_keys = self.db["api_keys"]
        self.candidates.create_index([("transcript.external_id", ASCENDING)])
        self.candidates.create_index([("status", ASCENDING), ("updated_at", DESCENDING)])
        self.candidates.create_index([("stage", ASCENDING)])
        self.events.create_index([("candidate_id", ASCENDING), ("created_at", ASCENDING)])
        self.login_tokens.create_index("expires_at", expireAfterSeconds=0)
        self.login_throttles.create_index("expires_at", expireAfterSeconds=0)

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
        entries = [_entry(channel, "in", inbound, external_id)]
        if reply:
            entries.append(_entry(channel, "out", reply))
        self._commit(
            state,
            channel,
            entries,
            {"last_inbound_at": utcnow(), "nudge_count": 0},
            external_id=external_id,
        )

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
        self, candidate_id: str, status: Status | None, notes: str | None, actor: str
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
        if document is None:
            return None
        self.record_event(
            candidate_id,
            "recruiter_override",
            {"status": str_or_none(status), "notes": notes, "actor": actor},
        )
        return Candidate(**_candidate_fields(document))

    def get_recruiter(self, email: str) -> Recruiter | None:
        document = self.recruiters.find_one({"_id": email})
        return None if document is None else _recruiter(document)

    def invite_recruiter(self, email: str) -> Recruiter:
        """Creates the row that login requires. An existing row, including a deactivation, is kept."""
        document = self.recruiters.find_one_and_update(
            {"_id": email},
            {"$setOnInsert": {"active": True, "created_at": utcnow(), "last_login_at": None}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return _recruiter(_upserted(document))

    def mark_recruiter_login(self, email: str) -> None:
        self.recruiters.update_one({"_id": email}, {"$set": {"last_login_at": utcnow()}})

    def deactivate_recruiter(self, email: str) -> None:
        """Upserts, so an address can be blocked before it is ever invited or logs in."""
        now = utcnow()
        self.recruiters.update_one(
            {"_id": email},
            {
                "$set": {"active": False, "sessions_valid_after": now},
                "$setOnInsert": {"created_at": now, "last_login_at": None},
            },
            upsert=True,
        )

    def reactivate_recruiter(self, email: str) -> bool:
        return (
            self.recruiters.update_one({"_id": email}, {"$set": {"active": True}}).matched_count
            == 1
        )

    def list_recruiters(self) -> list[Recruiter]:
        return [_recruiter(document) for document in self.recruiters.find().sort("_id", ASCENDING)]

    def try_acquire_login_slot(
        self,
        email: str,
        client_ip: str,
        now: datetime,
        email_cooldown: timedelta,
        ip_limit: int,
        ip_window: timedelta,
    ) -> bool:
        """Both limits are single atomic writes, so concurrent requests cannot slip past either one."""
        window_seconds = ip_window.total_seconds()
        window_index = int(now.timestamp() // window_seconds)
        window_end = datetime.fromtimestamp((window_index + 1) * window_seconds, UTC)
        ip_counter = self.login_throttles.find_one_and_update(
            {"_id": f"ip:{client_ip}:{window_index}"},
            {"$inc": {"count": 1}, "$setOnInsert": {"expires_at": window_end}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        if _upserted(ip_counter)["count"] > ip_limit:
            return False
        try:
            # An unexpired cooldown row does not match, so the upsert collides on _id.
            self.login_throttles.update_one(
                {"_id": f"email:{email}", "expires_at": {"$lte": now}},
                {"$set": {"expires_at": now + email_cooldown}},
                upsert=True,
            )
        except DuplicateKeyError:
            return False
        return True

    def save_login_token(self, token_hash: str, email: str, expires_at: datetime) -> None:
        self.login_tokens.insert_one(
            {"_id": token_hash, "email": email, "expires_at": expires_at, "used_at": None}
        )

    def login_token_is_live(self, token_hash: str, now: datetime) -> bool:
        query = {"_id": token_hash, "used_at": None, "expires_at": {"$gt": now}}
        return self.login_tokens.count_documents(query, limit=1) == 1

    def consume_login_token(self, token_hash: str, now: datetime) -> str | None:
        """Single use: the conditional update is the lock, so two clicks cannot both log in."""
        document = self.login_tokens.find_one_and_update(
            {"_id": token_hash, "used_at": None, "expires_at": {"$gt": now}},
            {"$set": {"used_at": now}},
        )
        return None if document is None else document["email"]

    def save_api_key(self, key_id: str, secret_hash: str, label: str) -> ApiKey:
        api_key = ApiKey(key_id=key_id, label=label)
        self.api_keys.insert_one(
            {
                "_id": key_id,
                "hash": secret_hash,
                "label": label,
                "active": True,
                "created_at": api_key.created_at,
            }
        )
        return api_key

    def api_key_hash(self, key_id: str) -> tuple[str, str] | None:
        """Returns (label, secret hash) for an active key id."""
        document = self.api_keys.find_one({"_id": key_id, "active": True})
        return None if document is None else (document["label"], document["hash"])

    def revoke_api_key(self, key_id: str) -> bool:
        return (
            self.api_keys.update_one({"_id": key_id}, {"$set": {"active": False}}).matched_count
            == 1
        )

    def list_api_keys(self) -> list[ApiKey]:
        return [
            ApiKey(
                key_id=d["_id"], label=d["label"], active=d["active"], created_at=d["created_at"]
            )
            for d in self.api_keys.find().sort("created_at", ASCENDING)
        ]

    def list_candidates(
        self, status: str | None = None, stage: str | None = None, limit: int = 0, offset: int = 0
    ) -> list[Candidate]:
        """A limit of 0 returns every match, which is MongoDB's own meaning of limit 0."""
        query: dict[str, Any] = {}
        if status:
            query["status"] = status
        if stage:
            query["stage"] = stage
        cursor = (
            self.candidates.find(query, _CANDIDATE_FIELDS)
            # _id breaks updated_at ties, so pages neither repeat nor skip a candidate.
            .sort([("updated_at", DESCENDING), ("_id", ASCENDING)])
            .skip(offset)
            .limit(limit)
        )
        return [_candidate(document) for document in cursor]

    def get_candidate(self, candidate_id: str) -> Candidate | None:
        document = self.candidates.find_one({"_id": candidate_id}, _CANDIDATE_FIELDS)
        return None if document is None else _candidate(document)

    def get_candidate_detail(self, candidate_id: str) -> CandidateDetail | None:
        document = self.candidates.find_one({"_id": candidate_id}, {"state": 0})
        if document is None:
            return None
        return CandidateDetail(events=self.list_events(candidate_id), **_candidate_fields(document))

    def list_events(self, candidate_id: str) -> list[Event]:
        cursor = self.events.find({"candidate_id": candidate_id}).sort(
            [("created_at", ASCENDING), ("_id", ASCENDING)]
        )
        return [Event.model_validate(document) for document in cursor]

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
        external_id: str | None = None,
    ) -> None:
        """Conditional on the loaded version and on the external id not being in the transcript yet,
        so a lost race across processes is refused by the database, not by a prior read."""
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
        query: dict[str, Any] = {"_id": candidate_id, "version": expected}
        if external_id:
            query["transcript.external_id"] = {"$ne": external_id}
        result = self.candidates.update_one(query, update)
        if result.matched_count == 0:
            version_current = self.candidates.count_documents(
                {"_id": candidate_id, "version": expected}, limit=1
            )
            if external_id and version_current:
                raise DuplicateMessageError(external_id)
            raise StaleStateError(f"{candidate_id}: version {expected} no longer current")


_CANDIDATE_FIELDS = {"state": 0, "transcript": 0}
_SILENCE_FIELDS = {
    "channel": 1,
    "state.language": 1,
    "opened_at": 1,
    "last_inbound_at": 1,
    "nudge_count": 1,
}


def _upserted(document: dict[str, Any] | None) -> dict[str, Any]:
    """An upsert with ReturnDocument.AFTER always returns a document; pymongo types it Optional."""
    if document is None:
        raise RuntimeError("upsert returned no document")
    return document


def str_or_none(value: Any) -> str | None:
    return None if value is None else str(value)


def _entry(
    channel: str, direction: str, body: str, external_id: str | None = None
) -> TranscriptEntry:
    return TranscriptEntry(direction=direction, channel=channel, body=body, external_id=external_id)


def _candidate(document: dict[str, Any]) -> Candidate:
    return Candidate(**_candidate_fields(document))


def _candidate_fields(document: dict[str, Any]) -> dict[str, Any]:
    return {"id": document["_id"], **{k: v for k, v in document.items() if k != "_id"}}


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


def _recruiter(document: dict[str, Any]) -> Recruiter:
    return Recruiter(
        email=document["_id"],
        active=document["active"],
        created_at=document["created_at"],
        last_login_at=document.get("last_login_at"),
        sessions_valid_after=document.get("sessions_valid_after"),
    )
