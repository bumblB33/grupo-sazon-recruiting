from datetime import UTC, datetime

from screening_agent.domain.enums import DisqualifyReason, ReviewReason, Stage, Status
from screening_agent.domain.profile import CandidateProfile
from screening_agent.flow.tools import ALL_TOOLS
from screening_agent.flow.turn_record import ReplySource, ToolCallRecord, TurnRecord
from screening_agent.llm.guardrail import CandidateTone, GuardrailCategory
from screening_agent.llm.usage import ModelUsage
from screening_agent.recruiter.labels import LABELS, label
from screening_agent.recruiter.views import (
    TurnView,
    event_views,
    profile_rows,
    transcript_views,
)
from screening_agent.storage.models import Event, TranscriptEntry


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
    assert set(LABELS["reply_source"]) == set(ReplySource)


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


def test_every_enum_value_has_a_label():
    assert set(LABELS["status"]) == set(Status)
    assert set(LABELS["stage"]) == set(Stage)
    assert set(LABELS["reason"]) == set(DisqualifyReason) | set(ReviewReason)
    assert set(LABELS["guardrail"]) == set(GuardrailCategory)
    assert set(LABELS["tone"]) == set(CandidateTone)
    assert set(LABELS["tool"]) == set(ALL_TOOLS)
    assert set(LABELS["profile_field"]) == set(CandidateProfile.model_fields)


def test_an_unknown_value_falls_back_to_a_humanised_name():
    assert label("needs_recruiter_review", "status") == "Needs review"
    assert label("retired_stage", "stage") == "Retired stage"


def test_profile_rows_follow_screening_order_and_mark_unanswered_fields():
    rows = profile_rows(
        {"full_name": "Ana García", "has_licence": False, "availability": ["full_time", "weekends"]}
    )
    shown = {row.name: row.value for row in rows}
    assert [row.name for row in rows][:3] == ["Full name", "Driving licence", "Zone"]
    assert shown["Full name"] == "Ana García"
    assert shown["Driving licence"] == "No"
    assert shown["Availability"] == "Full time, Weekends"
    assert shown["Zone"] is None


def test_event_views_label_the_kind_and_known_payload_values():
    now = datetime.now(UTC)
    [view] = event_views(
        [
            Event(
                candidate_id="+34600",
                kind="outcome",
                created_at=now,
                payload={
                    "status": "disqualified",
                    "disqualify_reason": "no_licence",
                    "review_reason": None,
                },
            )
        ]
    )
    assert view.kind == "Outcome reached"
    assert [(f.name, f.value) for f in view.fields] == [
        ("Status", "Disqualified"),
        ("Disqualify reason", "No driving licence"),
    ]


def test_a_closed_experience_answer_with_no_platforms_reads_none():
    rows = {
        row.name: row.value
        for row in profile_rows({"experience_years": 0, "experience_platforms": []})
    }
    assert rows["Delivery platforms"] == "None"
    assert {row.name: row.value for row in profile_rows({})}["Delivery platforms"] is None


def test_profile_rows_do_not_fail_on_a_non_string_list_item():
    rows = {row.name: row.value for row in profile_rows({"availability": [3]})}
    assert rows["Availability"] == "3"


def test_event_payload_values_are_labelled_for_every_producer():
    now = datetime.now(UTC)
    events = [
        Event(
            candidate_id="c",
            kind="guardrail_blocked",
            created_at=now,
            payload={"reason": "off_topic"},
        ),
        Event(
            candidate_id="c", kind="nudge", created_at=now, payload={"count": 1, "stage": "zone"}
        ),
        Event(
            candidate_id="c",
            kind="recruiter_override",
            created_at=now,
            payload={"status": "qualified", "notes": "", "actor": "recruiter:a@b.c"},
        ),
    ]
    blocked, nudge, override = (
        [(f.name, f.value) for f in view.fields] for view in event_views(events)
    )
    assert blocked == [("Reason", "Off topic")]
    assert nudge == [("Count", "1"), ("Stage", "Zone")]
    assert override == [("Status", "Qualified"), ("Actor", "recruiter:a@b.c")]
