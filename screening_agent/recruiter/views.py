from dataclasses import dataclass
from datetime import datetime

from screening_agent.flow.turn_record import ReplySource, ToolCallRecord, TurnRecord
from screening_agent.llm.usage import ModelUsage
from screening_agent.storage.models import TranscriptEntry

REPLY_SOURCE_LABELS: dict[ReplySource, str] = {
    ReplySource.TERMINAL: "fixed closing message",
    ReplySource.REASK: "fixed re-ask, model text unusable",
    ReplySource.ZONE_CONFIRM: "fixed zone confirmation, model text unusable",
    ReplySource.NAME_CONFIRM: "fixed name confirmation, model text unusable",
    ReplySource.CONSENT_DEFERRED: "fixed wait message, model text unusable",
    ReplySource.MODEL_TEXT: "model text, passed the reply rules",
    ReplySource.MODEL_COMPOSED: "model text, written after the tool results",
    ReplySource.POLICY_FALLBACK: "fixed question, model text broke a reply rule",
    ReplySource.NEXT_QUESTION: "fixed next question, model wrote nothing",
    ReplySource.GUARDRAIL_REDIRECT: "fixed guardrail redirect",
}


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
    reply_source: str
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
            reply_source=record.reply_source.value,
            reply_source_label=REPLY_SOURCE_LABELS[record.reply_source],
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
