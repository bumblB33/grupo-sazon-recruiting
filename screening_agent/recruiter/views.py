from dataclasses import dataclass
from datetime import datetime
from typing import Any

from screening_agent.domain.profile import CandidateProfile
from screening_agent.flow.turn_record import ReplySource, ToolCallRecord, TurnRecord
from screening_agent.llm.usage import ModelUsage
from screening_agent.recruiter.labels import humanise, label
from screening_agent.storage.models import Event, TranscriptEntry


@dataclass(frozen=True)
class UsageRow:
    call: str
    model: str
    tokens: str
    latency_ms: float

    @classmethod
    def from_usage(cls, usage: ModelUsage) -> "UsageRow":
        tokens = (
            f"{usage.input_tokens} in / {usage.output_tokens} out"
            if usage.input_tokens is not None
            else "not reported"
        )
        return cls(usage.call, usage.model, tokens, usage.latency_ms)


@dataclass(frozen=True)
class TurnView:
    stage_before: str
    stage_after: str
    status_after: str
    guardrail_category: str | None
    tone: str | None
    tools_exposed: list[str]
    tool_calls: list[ToolCallRecord]
    reply_source_label: str
    replaced_model_text: str | None
    violated_rules: list[str]
    usage: list[UsageRow]
    latency_ms: float
    candidate_hash: str | None
    trace_id: str | None

    @classmethod
    def from_record(cls, record: TurnRecord) -> "TurnView":
        replaced = record.reply_source != ReplySource.MODEL_TEXT
        return cls(
            stage_before=record.stage_before,
            stage_after=record.stage_after,
            status_after=record.status_after,
            guardrail_category=record.guardrail_category,
            tone=record.tone,
            tools_exposed=list(record.tools_exposed),
            tool_calls=list(record.tool_calls),
            reply_source_label=label(record.reply_source, "reply_source"),
            replaced_model_text=record.model_text if replaced and record.model_text else None,
            violated_rules=list(record.violated_rules),
            usage=[UsageRow.from_usage(usage) for usage in record.usage],
            latency_ms=record.latency_ms,
            candidate_hash=record.candidate_hash,
            trace_id=record.trace_id,
        )


@dataclass(frozen=True)
class MessageView:
    direction: str
    channel: str
    body: str
    created_at: datetime
    turn: TurnView | None
    expanded: bool


def transcript_views(entries: list[TranscriptEntry]) -> list[MessageView]:
    """The newest answered message opens its inspector; older ones start collapsed."""
    newest = max((i for i, entry in enumerate(entries) if entry.turn is not None), default=None)
    return [
        MessageView(
            direction=entry.direction,
            channel=entry.channel,
            body=entry.body,
            created_at=entry.created_at,
            turn=TurnView.from_record(entry.turn) if entry.turn is not None else None,
            expanded=index == newest,
        )
        for index, entry in enumerate(entries)
    ]


@dataclass(frozen=True)
class FactRow:
    name: str
    value: str | None


@dataclass(frozen=True)
class EventView:
    kind: str
    created_at: datetime
    fields: list[FactRow]


ENUM_PROFILE_FIELDS = frozenset({"availability", "schedule"})
EVENT_VALUE_KINDS = {
    ("outcome", "status"): "status",
    ("outcome", "stage"): "stage",
    ("outcome", "disqualify_reason"): "reason",
    ("outcome", "review_reason"): "reason",
    ("recruiter_override", "status"): "status",
    ("nudge", "stage"): "stage",
    ("guardrail_blocked", "reason"): "guardrail",
}


def profile_rows(profile: dict[str, Any]) -> list[FactRow]:
    """Every profile field in screening order; a field the candidate has not answered has no value."""
    return [
        FactRow(label(key, "profile_field"), _profile_value(key, profile))
        for key in CandidateProfile.model_fields
    ]


def _profile_value(key: str, profile: dict[str, Any]) -> str | None:
    value = profile.get(key)
    if value is None or value == "":
        return None
    if value == [] and profile.get("experience_years") is not None:
        return "None"
    if value == []:
        return None
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, list):
        return ", ".join(
            humanise(str(item)) if key in ENUM_PROFILE_FIELDS else str(item) for item in value
        )
    return humanise(str(value)) if key in ENUM_PROFILE_FIELDS else str(value)


def event_views(events: list[Event]) -> list[EventView]:
    return [
        EventView(
            kind=label(event.kind, "event"),
            created_at=event.created_at,
            fields=[
                FactRow(humanise(key), _event_value(event.kind, key, value))
                for key, value in event.payload.items()
                if value is not None and value != ""
            ],
        )
        for event in events
    ]


def _event_value(kind: str, key: str, value: Any) -> str:
    value_kind = EVENT_VALUE_KINDS.get((kind, key))
    return label(value, value_kind) if value_kind else str(value)
