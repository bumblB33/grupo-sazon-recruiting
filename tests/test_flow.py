from datetime import date, timedelta

from screening_agent.domain.enums import DisqualifyReason, ReviewReason, Status
from screening_agent.flow.engine import Outcome
from tests.conftest import ai, ai_multi

CONSENT = ai("Hola", "record_consent", {"accepted": True})
NAME = ai("¿Nombre?", "record_full_name", {"full_name": "Ana García"})
LICENCE = ai("¿Carnet?", "record_licence", {"has_licence": True})
START = (date.today() + timedelta(days=7)).isoformat()


def drive(engine, texts):
    """Mimics a channel: send each text, run the summary once the turn reaches a terminal status."""
    replies = []
    for index, text in enumerate(texts):
        result = engine.handle("cand", text, channel="cli", external_id=f"m{index}")
        replies.append(result.reply)
        if result.terminal:
            engine.summarize_outcome("cand")
    return replies


def test_no_licence_is_hard_stop(make_engine):
    engine, repository, _ = make_engine(
        [CONSENT, NAME, ai("¿Carnet?", "record_licence", {"has_licence": False})]
    )
    replies = drive(engine, ["sí", "Ana García", "no tengo carnet"])
    candidate = repository.get_candidate("cand")
    assert candidate.status == Status.DISQUALIFIED
    assert candidate.disqualify_reason == DisqualifyReason.NO_LICENCE
    assert "carnet" in replies[-1]
    assert candidate.summary == "summary"
    assert engine.handle("cand", "espera", "cli", external_id="late").outcome == Outcome.CLOSED


def test_model_sees_full_history(make_engine):
    engine, _, model = make_engine([CONSENT, NAME, LICENCE])
    drive(engine, ["sí", "Ana García", "sí"])
    third_turn = model.seen_inputs[2]
    assert [m.type for m in third_turn] == [
        "system",
        "human",
        "ai",
        "tool",
        "human",
        "ai",
        "tool",
        "human",
    ]


def test_tools_bound_match_stage(make_engine):
    engine, _, model = make_engine([CONSENT, NAME])
    drive(engine, ["sí", "Ana García"])
    assert model.bound_tool_names[0] == ["record_consent"]
    assert model.bound_tool_names[1][0] == "record_full_name"
    assert "record_consent" not in model.bound_tool_names[1]


def test_unexposed_tool_is_rejected(make_engine):
    engine, repository, _ = make_engine([ai("Hola", "record_licence", {"has_licence": False})])
    drive(engine, ["hola"])
    candidate = repository.get_candidate("cand")
    assert candidate.status == Status.IN_PROGRESS
    assert candidate.stage == "consent"


def test_invalid_tool_arguments_become_reask(make_engine):
    engine, repository, _ = make_engine(
        [
            CONSENT,
            NAME,
            LICENCE,
            ai("¿Ciudad?", "record_zone", {"city": "Madrid"}),
            ai("¿Disponibilidad?", "record_availability", {"availability": ["full-time"]}),
        ]
    )
    replies = drive(engine, ["sí", "Ana García", "sí", "Madrid", "jornada completa"])
    assert "disponibilidad" in replies[-1]
    assert repository.get_candidate("cand").status == Status.IN_PROGRESS


def test_two_invalid_answers_escalate_to_recruiter(make_engine):
    engine, repository, _ = make_engine(
        [
            CONSENT,
            ai("¿Nombre?", "record_full_name", {"full_name": "Ana"}),
            ai("¿Nombre?", "record_full_name", {"full_name": "A"}),
        ]
    )
    drive(engine, ["sí", "Ana", "A"])
    candidate = repository.get_candidate("cand")
    assert candidate.status == Status.NEEDS_RECRUITER_REVIEW
    assert candidate.review_reason == ReviewReason.REPEATED_INVALID_ANSWER


def test_consent_declined_goes_to_recruiter(make_engine):
    engine, repository, _ = make_engine([ai("Hola", "record_consent", {"accepted": False})])
    drive(engine, ["no quiero"])
    assert repository.get_candidate("cand").review_reason == ReviewReason.CONSENT_DECLINED


def test_fuzzy_zone_asks_confirmation_then_accepts(make_engine):
    engine, repository, model = make_engine(
        [
            CONSENT,
            NAME,
            LICENCE,
            ai("¿Ciudad?", "record_zone", {"city": "madird"}),
            ai("ok", "confirm_zone", {"confirmed": True}),
        ]
    )
    replies = drive(engine, ["sí", "Ana García", "sí", "madird", "sí"])
    assert "Madrid" in replies[-2]
    assert model.bound_tool_names[-1][0] == "confirm_zone"
    assert repository.get_candidate("cand").profile["zone"] == "Madrid"


def test_out_of_area_is_hard_stop(make_engine):
    engine, repository, _ = make_engine(
        [CONSENT, NAME, LICENCE, ai("¿Ciudad?", "record_zone", {"city": "Toledo"})]
    )
    drive(engine, ["sí", "Ana García", "sí", "Toledo"])
    assert (
        repository.get_candidate("cand").disqualify_reason == DisqualifyReason.OUTSIDE_SERVICE_AREA
    )


def test_terminal_reply_wins_over_reask(make_engine):
    engine, repository, _ = make_engine(
        [
            CONSENT,
            ai_multi(
                "ok",
                ("record_full_name", {"full_name": "Ana"}),
                ("record_licence", {"has_licence": False}),
            ),
        ]
    )
    replies = drive(engine, ["sí", "Ana, no tengo carnet"])
    assert repository.get_candidate("cand").status == Status.DISQUALIFIED
    assert "carnet" in replies[-1]


def test_multi_tool_turn_qualifies_regardless_of_order(make_engine):
    engine, repository, _ = make_engine(
        [
            CONSENT,
            ai_multi(
                "ok",
                ("record_full_name", {"full_name": "Ana García"}),
                ("record_licence", {"has_licence": True}),
                ("record_availability", {"availability": ["weekends"]}),
                ("record_schedule", {"schedule": "evening"}),
                ("record_experience", {"years": 0, "platforms": []}),
                ("record_start_date", {"start_date": START}),
                ("record_zone", {"city": "Madrid"}),
            ),
        ]
    )
    replies = drive(engine, ["sí", "todo de golpe"])
    candidate = repository.get_candidate("cand")
    assert candidate.status == Status.QUALIFIED
    assert "Ana" in replies[-1]
    assert engine.handle("cand", "gracias", "cli", external_id="after").outcome == Outcome.CLOSED


def test_empty_model_text_falls_back_to_next_question(make_engine):
    engine, _, _ = make_engine([ai("", "record_consent", {"accepted": True})])
    assert "nombre" in drive(engine, ["sí"])[-1]


def test_past_start_date_rejected_only_on_input(make_engine):
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    engine, repository, _ = make_engine(
        [
            CONSENT,
            NAME,
            LICENCE,
            ai("¿Ciudad?", "record_zone", {"city": "Madrid"}),
            ai("¿Cuándo?", "record_start_date", {"start_date": yesterday}),
        ]
    )
    replies = drive(engine, ["sí", "Ana García", "sí", "Madrid", "ayer"])
    assert "fecha" in replies[-1]
    assert repository.get_candidate("cand").status == Status.IN_PROGRESS


def test_redelivered_message_is_ignored(make_engine):
    engine, _, _ = make_engine([CONSENT])
    assert engine.handle("cand", "sí", "whatsapp", external_id="wa-1").outcome == Outcome.REPLIED
    assert engine.handle("cand", "sí", "whatsapp", external_id="wa-1").outcome == Outcome.DUPLICATE


def test_recruiter_override_is_honoured_by_engine(make_engine):
    engine, repository, _ = make_engine([CONSENT, NAME])
    drive(engine, ["sí"])
    repository.override("cand", "disqualified", "called, not eligible", actor="recruiter:test")
    assert engine.handle("cand", "Ana García", "cli", external_id="m9").outcome == Outcome.CLOSED
    candidate = repository.get_candidate("cand")
    assert candidate.status == Status.DISQUALIFIED
    assert candidate.recruiter_notes == "called, not eligible"


def test_unexposed_tool_reasks_current_stage_without_strike(make_engine):
    engine, repository, _ = make_engine(
        [
            ai("x", "record_licence", {"has_licence": True}),
            ai("y", "record_licence", {"has_licence": True}),
        ]
    )
    replies = drive(engine, ["hola", "hola"])
    candidate = repository.get_candidate("cand")
    assert "asistente de IA" in replies[0]
    assert candidate.status == Status.IN_PROGRESS
    assert candidate.stage == "consent"


def test_consent_and_name_in_one_turn_are_both_recorded(make_engine):
    engine, repository, _ = make_engine(
        [
            ai_multi(
                "ok",
                ("record_consent", {"accepted": True}),
                ("record_full_name", {"full_name": "Ana García"}),
            )
        ]
    )
    replies = drive(engine, ["sí, soy Ana García"])
    candidate = repository.get_candidate("cand")
    assert candidate.profile["full_name"] == "Ana García"
    assert candidate.stage == "has_licence"
    assert "nombre" not in replies[-1]


def test_empty_consent_turn_reasks_consent(make_engine):
    engine, _, _ = make_engine([ai("")])
    assert "asistente de IA" in drive(engine, ["hola"])[-1]


def test_off_topic_twice_closes_and_keeps_history(make_engine):
    from screening_agent.llm.guardrail import GuardrailVerdict

    engine, repository, _ = make_engine(
        [], guardrail=lambda text: GuardrailVerdict(allowed=False, reason="off_topic")
    )
    replies = drive(engine, ["¿me vendes un coche?", "¿y una moto?"])
    assert "centrarnos" in replies[0]
    assert repository.get_candidate("cand").review_reason == ReviewReason.OFF_TOPIC_CLOSE
    history = repository.load_state("cand")["messages"]
    assert [m.type for m in history] == ["human", "ai", "human", "ai"]


def test_terminal_turn_is_flagged_and_summary_runs_on_request(make_engine):
    engine, repository, _ = make_engine([ai("Hola", "record_consent", {"accepted": False})])
    result = engine.handle("cand", "no", "cli", external_id="m0")
    assert result.terminal
    assert repository.get_candidate("cand").summary is None
    engine.summarize_outcome("cand")
    assert repository.get_candidate("cand").summary == "summary"


def test_lost_dedupe_race_reports_duplicate(make_engine, monkeypatch):
    # A scripted AIMessage gets an id on first use, so the same object cannot be replayed twice.
    engine, repository, _ = make_engine([CONSENT, ai("Hola", "record_consent", {"accepted": True})])
    engine.handle("cand", "sí", "cli", external_id="same")
    monkeypatch.setattr(repository, "has_message", lambda external_id: False)
    assert engine.handle("cand", "sí", "cli", external_id="same").outcome == Outcome.DUPLICATE


def test_start_date_is_judged_in_candidate_timezone(make_engine, monkeypatch):
    from datetime import date as real_date

    from screening_agent.flow import transitions

    tijuana_today = real_date(2026, 10, 23)
    monkeypatch.setattr(transitions, "candidate_today", lambda zone: tijuana_today)
    engine, repository, _ = make_engine(
        [
            CONSENT,
            NAME,
            LICENCE,
            ai("¿Ciudad?", "record_zone", {"city": "Tijuana"}),
            ai("¿Cuándo?", "record_start_date", {"start_date": tijuana_today.isoformat()}),
        ]
    )
    drive(engine, ["sí", "Ana García", "sí", "Tijuana", "hoy"])
    assert repository.get_candidate("cand").profile["start_date"] == tijuana_today.isoformat()


def test_consent_prompt_after_opener_does_not_reintroduce():
    from langchain_core.messages import AIMessage, HumanMessage

    from screening_agent.domain.enums import Stage
    from screening_agent.flow.state import initial_state
    from screening_agent.llm.turn import build_prompt

    fresh = initial_state("c")
    fresh["messages"] = [HumanMessage(content="hola")]
    assert "Introduce yourself" in build_prompt(fresh, Stage.CONSENT)
    opened = initial_state("c")
    opened["messages"] = [AIMessage(content="opener"), HumanMessage(content="sí")]
    assert "Do not introduce yourself again" in build_prompt(opened, Stage.CONSENT)


def inbound_turns(repository, candidate_id: str = "cand"):
    detail = repository.get_candidate_detail(candidate_id)
    return [entry.turn for entry in detail.transcript if entry.direction == "in"]


def test_turn_record_is_saved_on_the_inbound_entry(make_engine):
    engine, repository, _ = make_engine([CONSENT, NAME])
    drive(engine, ["sí", "Ana García"])
    first, second = inbound_turns(repository)
    assert (first.stage_before, first.stage_after) == ("consent", "full_name")
    assert first.tools_exposed == ["record_consent"]
    assert [(c.name, c.accepted) for c in first.tool_calls] == [("record_consent", True)]
    assert first.reply_source == "model_text" and first.model_text is None
    assert second.stage_before == "full_name"
    assert all(
        entry.turn is None
        for entry in repository.get_candidate_detail("cand").transcript
        if entry.direction == "out"
    )


def test_turn_record_keeps_model_text_and_validator_message_when_a_template_replies(make_engine):
    engine, repository, _ = make_engine(
        [CONSENT, ai("Genial", "record_full_name", {"full_name": "A"})]
    )
    drive(engine, ["sí", "A"])
    record = inbound_turns(repository)[1]
    assert record.reply_source == "reask"
    assert record.model_text == "Genial"
    call = record.tool_calls[0]
    assert not call.accepted and call.message


def test_turn_record_carries_usage_for_the_turn_and_the_guardrail(make_engine):
    from langchain_core.messages import AIMessage

    from screening_agent.llm.guardrail import GuardrailCategory, GuardrailVerdict
    from screening_agent.llm.usage import ModelUsage

    usage = ModelUsage(
        call="guardrail", model="guard", input_tokens=7, output_tokens=1, latency_ms=3.0
    )
    scripted = AIMessage(
        content="Hola",
        tool_calls=[
            {"name": "record_consent", "args": {"accepted": True}, "id": "c1", "type": "tool_call"}
        ],
        usage_metadata={"input_tokens": 120, "output_tokens": 15, "total_tokens": 135},
    )
    engine, repository, _ = make_engine(
        [scripted],
        guardrail=lambda text: GuardrailVerdict(
            allowed=True, category=GuardrailCategory.ON_TOPIC, usage=usage
        ),
    )
    drive(engine, ["sí"])
    record = inbound_turns(repository)[0]
    assert record.guardrail_category == "on_topic"
    by_call = {u.call: u for u in record.usage}
    assert (by_call["turn"].input_tokens, by_call["turn"].output_tokens) == (120, 15)
    assert by_call["guardrail"].input_tokens == 7
    assert record.latency_ms >= 0


def test_blocked_message_records_the_guardrail_and_no_model_call(make_engine):
    from screening_agent.llm.guardrail import GuardrailCategory, GuardrailVerdict

    engine, repository, _ = make_engine(
        [],
        guardrail=lambda text: GuardrailVerdict(
            allowed=False, reason="off_topic", category=GuardrailCategory.OFF_TOPIC
        ),
    )
    drive(engine, ["¿me vendes un coche?"])
    record = inbound_turns(repository)[0]
    assert record.guardrail_category == "off_topic"
    assert record.reply_source == "guardrail_redirect"
    assert record.tools_exposed == [] and record.tool_calls == []
    assert "turn" not in repository.load_state("cand")


def test_exhausted_stale_retries_raise_without_the_candidate_id(make_engine, monkeypatch):
    import pytest

    from screening_agent.storage.repository import StaleStateError

    engine, repository, _ = make_engine([CONSENT, CONSENT])

    def always_stale(*args, **kwargs):
        raise StaleStateError("version no longer current")

    monkeypatch.setattr(repository, "save_turn", always_stale)
    with pytest.raises(StaleStateError) as raised:
        engine.handle("+34600111222", "sí", "whatsapp", external_id="m0")
    assert "34600111222" not in str(raised.value)


def test_reply_breaking_the_policy_is_replaced_by_the_next_fixed_question(make_engine):
    from screening_agent.domain.enums import Language, Stage
    from screening_agent.flow import replies

    engine, repository, _ = make_engine(
        [ai("**Genial**. ¿Nombre? ¿Y apellidos?", "record_consent", {"accepted": True})]
    )
    reply = drive(engine, ["sí"])[0]
    assert reply == replies.REASK[Stage.FULL_NAME][Language.ES]
    record = inbound_turns(repository)[0]
    assert record.reply_source == "policy_fallback"
    assert record.model_text == "**Genial**. ¿Nombre? ¿Y apellidos?"
    assert set(record.violated_rules) == {"more than one question", "markdown or list"}
    assert repository.load_state("cand")["consent"] is True


def test_candidate_tone_reaches_the_turn_and_the_record_but_not_saved_state(make_engine):
    from screening_agent.llm.guardrail import CandidateTone, GuardrailVerdict

    engine, repository, model = make_engine(
        [CONSENT],
        guardrail=lambda text: GuardrailVerdict(allowed=True, tone=CandidateTone.CONFUSED),
    )
    drive(engine, ["¿qué? no entiendo nada"])
    assert inbound_turns(repository)[0].tone == "confused"
    assert "tone" not in repository.load_state("cand")


def test_prompt_adds_a_calmer_instruction_for_confused_or_frustrated_candidates():
    from langchain_core.messages import HumanMessage

    from screening_agent.domain.enums import Stage
    from screening_agent.flow.state import initial_state
    from screening_agent.llm.turn import build_prompt

    state = initial_state("c")
    state["messages"] = [HumanMessage(content="hola")]
    neutral = build_prompt(state, Stage.CONSENT)
    confused = build_prompt({**state, "tone": "confused"}, Stage.CONSENT)
    frustrated = build_prompt({**state, "tone": "frustrated"}, Stage.CONSENT)
    assert confused.startswith(neutral) and frustrated.startswith(neutral)
    assert confused != neutral and frustrated != neutral and confused != frustrated
