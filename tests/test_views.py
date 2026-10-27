from datetime import UTC, datetime

from screening_agent.flow.turn_record import ReplySource, ToolCallRecord, TurnRecord
from screening_agent.llm.usage import ModelUsage
from screening_agent.recruiter.views import REPLY_SOURCE_LABELS, TurnView, transcript_views
from screening_agent.storage.models import TranscriptEntry


def record(source: ReplySource, model_text: str | None = "hola") -> TurnRecord:
    return TurnRecord(
        stage_before="consent",
        stage_after="full_name",
        status_after="in_progress",
        guardrail_category="on_topic",
        tone="confused",
        tools_exposed=["record_consent"],
        tool_calls=[ToolCallRecord(name="record_consent", accepted=True)],
        reply_source=source,
        model_text=model_text,
        violated_rules=["too_many_questions"] if source == ReplySource.POLICY_FALLBACK else [],
        usage=[
            ModelUsage(call="turn", model="m", input_tokens=10, output_tokens=5, latency_ms=12.0)
        ],
        latency_ms=20.0,
        trace_id="abc",
    )


def test_every_reply_source_has_a_label():
    assert set(REPLY_SOURCE_LABELS) == set(ReplySource)


def test_model_text_is_shown_only_when_a_fixed_reply_replaced_it():
    assert TurnView.from_record(record(ReplySource.MODEL_TEXT)).replaced_model_text is None
    view = TurnView.from_record(record(ReplySource.POLICY_FALLBACK))
    assert view.replaced_model_text == "hola"
    assert view.violated_rules == ["too_many_questions"]
    assert view.usage[0].tokens == "10 in / 5 out"


def test_only_the_newest_answered_message_is_expanded():
    now = datetime.now(UTC)
    entries = [
        TranscriptEntry(direction="out", channel="whatsapp", body="opener", created_at=now),
        TranscriptEntry(
            direction="in",
            channel="whatsapp",
            body="sí",
            created_at=now,
            turn=record(ReplySource.NEXT_QUESTION),
        ),
        TranscriptEntry(direction="out", channel="whatsapp", body="q", created_at=now),
        TranscriptEntry(
            direction="in",
            channel="whatsapp",
            body="Ana",
            created_at=now,
            turn=record(ReplySource.MODEL_TEXT),
        ),
    ]
    views = transcript_views(entries)
    assert [v.turn is not None for v in views] == [False, True, False, True]
    assert [v.expanded for v in views] == [False, False, False, True]
