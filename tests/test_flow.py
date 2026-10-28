from datetime import date, timedelta

from screening_agent.domain.enums import DisqualifyReason, Language, ReviewReason, Status
from screening_agent.flow import replies as replies_module
from screening_agent.flow.engine import Outcome, _nudge_text
from screening_agent.flow.turn_record import ReplySource
from tests.conftest import FakeOutbound, ai, ai_multi

CONSENT = ai("Hola", "record_consent", {"decision": "agreed"})
NAME = ai("¿Nombre?", "record_full_name", {"full_name": "Ana García"})
LICENCE = ai("¿Carnet?", "record_licence", {"has_licence": True})
START = (date.today() + timedelta(days=7)).isoformat()
# The compose call wrote nothing, so the fixed fallback goes out.
NO_TEXT = ai("")
NAME_CONFIRM_PEDRO = "Para asegurarme de que hablo con la persona correcta: ¿eres Pedro Martínez?"


NO_QUESTIONS = ai("", "record_questions", {"questions": []})


def drive(engine, texts, candidate_id: str = "cand", language: Language = Language.ES):
    """Mimics a channel: the fixed opener first, then each text, with the summary on each terminal turn."""
    engine.start_conversation(candidate_id, "cli", language, FakeOutbound())
    replies = []
    for index, text in enumerate(texts):
        result = engine.handle(candidate_id, text, channel="cli", external_id=f"m{index}")
        replies.append(result.reply)
        if result.terminal:
            engine.summarize_outcome(candidate_id)
    return replies


def test_no_licence_is_hard_stop_then_asks_for_questions_before_closing(make_engine):
    engine, repository, _ = make_engine(
        [
            CONSENT,
            NAME,
            ai("¿Carnet?", "record_licence", {"has_licence": False}),
            ai("", "record_questions", {"questions": ["¿Abrís en Toledo?"]}),
        ]
    )
    replies = drive(engine, ["sí", "Ana García", "no tengo carnet", "¿abrís en Toledo?"])
    candidate = repository.get_candidate("cand")
    assert candidate.status == Status.DISQUALIFIED
    assert candidate.disqualify_reason == DisqualifyReason.NO_LICENCE
    assert "carnet" in replies[-2] and "alguna pregunta" in replies[-2]
    assert replies[-1] == "Anotado, el reclutador verá tus preguntas. ¡Gracias por tu tiempo!"
    assert candidate.candidate_questions == ["¿Abrís en Toledo?"]
    assert candidate.summary == "summary"
    assert engine.handle("cand", "espera", "cli", external_id="late").outcome == Outcome.CLOSED


def test_wrap_up_turn_closes_without_questions_whatever_the_model_does(make_engine):
    engine, repository, model = make_engine(
        [
            CONSENT,
            NAME,
            ai("¿Carnet?", "record_licence", {"has_licence": False}),
            ai("¡Suerte!", "record_licence", {"has_licence": True}),
        ]
    )
    replies = drive(engine, ["sí", "Ana García", "no tengo carnet", "no, gracias"])
    assert model.bound_tool_names[-1] == ["record_questions"]
    assert replies[-1] == "Perfecto. ¡Gracias por tu tiempo!"
    candidate = repository.get_candidate("cand")
    assert candidate.status == Status.DISQUALIFIED and candidate.candidate_questions == []
    assert engine.handle("cand", "hola", "cli", external_id="late").outcome == Outcome.CLOSED


def test_flagged_concern_sends_a_complete_profile_to_review_not_qualified(make_engine):
    engine, repository, model = make_engine(
        [
            CONSENT,
            NAME,
            ai_multi(
                "ok",
                ("record_licence", {"has_licence": True}),
                ("flag_for_recruiter", {"concern": "Says they have a criminal record"}),
            ),
            ai("ok", "record_zone", {"city": "Madrid"}),
            ai("ok", "record_availability", {"availability": ["full_time"]}),
            ai("ok", "record_schedule", {"schedule": "morning"}),
            ai("ok", "record_experience", {"years": 0, "platforms": []}),
            ai("ok", "record_start_date", {"start_date": START}),
        ]
    )
    texts = [
        "sí",
        "Ana García",
        "sí, pero tengo antecedentes",
        "Madrid",
        "completa",
        "mañana",
        "0",
        START,
    ]
    replies = drive(engine, texts)
    assert "flag_for_recruiter" not in model.bound_tool_names[0]
    assert "flag_for_recruiter" in model.bound_tool_names[1]
    candidate = repository.get_candidate("cand")
    assert candidate.status == Status.NEEDS_RECRUITER_REVIEW
    assert candidate.review_reason == ReviewReason.RECRUITER_CHECK
    assert candidate.concerns == ["Says they have a criminal record"]
    assert candidate.profile["has_licence"] is True
    assert replies[-1].startswith("Gracias, eso es todo lo que necesitaba preguntarte.")
    assert "antecedentes" not in replies[-1]
    assert repository.load_state("cand")["invalid_counts"] == {}


def test_model_sees_full_history(make_engine):
    engine, _, model = make_engine([CONSENT, NAME, LICENCE])
    drive(engine, ["sí", "Ana García", "sí"])
    third_turn = model.seen_inputs[2]
    assert [m.type for m in third_turn] == [
        "system",
        "ai",
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
    assert "jornada" in replies[-1]
    assert repository.get_candidate("cand").status == Status.IN_PROGRESS


def test_two_invalid_answers_escalate_to_recruiter(make_engine):
    engine, repository, _ = make_engine(
        [
            CONSENT,
            ai("¿Nombre?", "record_full_name", {"full_name": "Ana"}),
            NO_TEXT,
            ai("¿Nombre?", "record_full_name", {"full_name": "A"}),
        ]
    )
    drive(engine, ["sí", "Ana", "A"])
    candidate = repository.get_candidate("cand")
    assert candidate.status == Status.NEEDS_RECRUITER_REVIEW
    assert candidate.review_reason == ReviewReason.REPEATED_INVALID_ANSWER


def test_consent_declined_goes_to_recruiter(make_engine):
    engine, repository, _ = make_engine([ai("Hola", "record_consent", {"decision": "declined"})])
    drive(engine, ["no quiero"])
    assert repository.get_candidate("cand").review_reason == ReviewReason.CONSENT_DECLINED


def test_fuzzy_zone_asks_confirmation_then_accepts(make_engine):
    engine, repository, model = make_engine(
        [
            CONSENT,
            NAME,
            LICENCE,
            ai("¿Ciudad?", "record_zone", {"city": "madird"}),
            NO_TEXT,
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
            NO_QUESTIONS,
        ]
    )
    replies = drive(engine, ["sí", "todo de golpe"])
    candidate = repository.get_candidate("cand")
    assert candidate.status == Status.QUALIFIED
    assert "Ana" in replies[-1]
    assert engine.handle("cand", "gracias", "cli", external_id="after").outcome == Outcome.REPLIED
    assert engine.handle("cand", "adiós", "cli", external_id="later").outcome == Outcome.CLOSED


def test_empty_model_text_falls_back_to_next_question(make_engine):
    engine, _, _ = make_engine([ai("", "record_consent", {"decision": "agreed"})])
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
    assert "empezar" in replies[-1]
    assert repository.get_candidate("cand").status == Status.IN_PROGRESS


def test_redelivered_message_is_ignored(make_engine):
    engine, _, _ = make_engine([CONSENT])
    engine.start_conversation("cand", "whatsapp", Language.ES, FakeOutbound())
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
            NO_TEXT,
            ai("y", "record_licence", {"has_licence": True}),
        ]
    )
    replies = drive(engine, ["hola", "hola"])
    candidate = repository.get_candidate("cand")
    assert "Soy una IA" in replies[0]
    assert candidate.status == Status.IN_PROGRESS
    assert candidate.stage == "consent"


def test_consent_and_name_in_one_turn_are_both_recorded(make_engine):
    engine, repository, _ = make_engine(
        [
            ai_multi(
                "ok",
                ("record_consent", {"decision": "agreed"}),
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
    assert "Soy una IA" in drive(engine, ["hola"])[-1]


def test_off_topic_twice_closes_and_keeps_history(make_engine):
    from screening_agent.llm.guardrail import GuardrailVerdict

    engine, repository, _ = make_engine(
        [], guardrail=lambda text: GuardrailVerdict(allowed=False, reason="off_topic")
    )
    replies = drive(engine, ["¿me vendes un coche?", "¿y una moto?"])
    assert "centrarnos" in replies[0]
    assert repository.get_candidate("cand").review_reason == ReviewReason.OFF_TOPIC_CLOSE
    history = repository.load_state("cand")["messages"]
    assert [m.type for m in history] == ["ai", "human", "ai", "human", "ai"]
    assert "alguna pregunta" not in replies[-1]
    assert engine.handle("cand", "hola", "cli", external_id="late").outcome == Outcome.CLOSED


def test_terminal_turn_is_flagged_and_summary_runs_on_request(make_engine):
    engine, repository, _ = make_engine([ai("Hola", "record_consent", {"decision": "declined"})])
    engine.start_conversation("cand", "cli", Language.ES, FakeOutbound())
    result = engine.handle("cand", "no", "cli", external_id="m0")
    assert result.terminal
    # An opt-out closes at once: no question for the recruiter, no further turn.
    assert "pregunta" not in result.reply
    assert engine.handle("cand", "vale", "cli", external_id="m1").outcome == Outcome.CLOSED
    assert repository.get_candidate("cand").summary is None
    engine.summarize_outcome("cand")
    assert repository.get_candidate("cand").summary == "summary"


def test_lost_dedupe_race_reports_duplicate(make_engine, monkeypatch):
    # A scripted AIMessage gets an id on first use, so the same object cannot be replayed twice.
    engine, repository, _ = make_engine(
        [CONSENT, ai("Hola", "record_consent", {"decision": "agreed"})]
    )
    engine.start_conversation("cand", "cli", Language.ES, FakeOutbound())
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


def test_consent_prompt_never_asks_the_model_to_write_the_disclosure():
    from langchain_core.messages import AIMessage, HumanMessage

    from screening_agent.domain.enums import Stage
    from screening_agent.flow.state import initial_state
    from screening_agent.llm.turn import build_prompt

    opened = initial_state("c")
    opened["messages"] = [AIMessage(content="opener"), HumanMessage(content="sí")]
    prompt = build_prompt(opened, Stage.CONSENT)
    assert "Do not introduce yourself again" in prompt
    assert "Introduce yourself" not in prompt
    assert "flag_for_recruiter" in prompt


def test_wrap_up_prompt_asks_only_for_the_questions(make_engine):
    from screening_agent.domain.enums import Stage
    from screening_agent.flow.state import initial_state
    from screening_agent.llm.turn import build_prompt

    decided = initial_state("c")
    decided["status"] = Status.DISQUALIFIED
    decided["closed"] = False
    assert "record_questions" in build_prompt(decided, Stage.HAS_LICENCE)


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
            {
                "name": "record_consent",
                "args": {"decision": "agreed"},
                "id": "c1",
                "type": "tool_call",
            }
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
    engine.start_conversation("+34600111222", "whatsapp", Language.ES, FakeOutbound())

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
        [
            ai("**Genial**. ¿Nombre? ¿Y apellidos?", "record_consent", {"decision": "agreed"}),
            ai(""),
        ]
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


def start_with_name(engine, applicant_name: str) -> FakeOutbound:
    outbound = FakeOutbound()
    assert engine.start_conversation(
        "cand", "cli", Language.ES, outbound, applicant_name=applicant_name
    )
    return outbound


def test_matching_name_is_recorded_without_a_confirmation_turn(make_engine):
    engine, repository, model = make_engine([CONSENT, NAME, LICENCE])
    outbound = start_with_name(engine, "Ana María García López")
    assert outbound.openers[0][1].startswith("¡Hola, Ana!")
    assert outbound.openers[0][2] == "Ana"
    drive(engine, ["sí", "Ana García", "sí"])
    candidate = repository.get_candidate("cand")
    assert candidate.applicant_name == "Ana María García López"
    assert candidate.profile["full_name"] == "Ana García"
    assert candidate.stage == "zone"
    assert all("confirm_name" not in bound for bound in model.bound_tool_names)


def test_mismatched_name_asks_a_fixed_confirmation_then_accepts(make_engine):
    engine, repository, model = make_engine(
        [CONSENT, NAME, NO_TEXT, ai("ok", "confirm_name", {"confirmed": True}), LICENCE]
    )
    start_with_name(engine, "Pedro Martínez")
    replies = drive(engine, ["sí", "Ana García", "sí", "sí"])
    assert replies[1] == NAME_CONFIRM_PEDRO
    assert model.bound_tool_names[2][0] == "confirm_name"
    assert "record_full_name" not in model.bound_tool_names[2]
    candidate = repository.get_candidate("cand")
    assert candidate.profile["full_name"] == "Ana García"
    assert candidate.stage == "zone"
    assert candidate.status == Status.IN_PROGRESS
    detail = repository.get_candidate_detail("cand")
    assert detail.transcript[3].turn.reply_source == ReplySource.NAME_CONFIRM


def test_denied_name_confirmation_goes_to_recruiter_review(make_engine):
    engine, repository, _ = make_engine(
        [CONSENT, NAME, NO_TEXT, ai("ok", "confirm_name", {"confirmed": False})]
    )
    start_with_name(engine, "Pedro Martínez")
    replies = drive(engine, ["sí", "Ana García", "no"])
    candidate = repository.get_candidate("cand")
    assert candidate.status == Status.NEEDS_RECRUITER_REVIEW
    assert candidate.review_reason == ReviewReason.NAME_MISMATCH
    assert "reclutador" in replies[-1]
    assert candidate.profile.get("full_name") is None


def test_nudge_repeats_the_name_confirmation_while_it_is_pending(make_engine):
    engine, repository, _ = make_engine([CONSENT, NAME])
    start_with_name(engine, "Pedro Martínez")
    drive(engine, ["sí", "Ana García"])
    state = repository.load_state("cand")
    assert state["pending_name"] == "Ana García"
    assert "Pedro Martínez" in _nudge_text(state, Language.ES)


def test_no_licence_still_disqualifies_when_the_name_needs_confirmation(make_engine):
    engine, repository, _ = make_engine(
        [
            CONSENT,
            ai_multi(
                "ok",
                ("record_full_name", {"full_name": "Ana García"}),
                ("record_licence", {"has_licence": False}),
            ),
        ]
    )
    start_with_name(engine, "Pedro Martínez")
    drive(engine, ["sí", "Ana García, sin carnet"])
    candidate = repository.get_candidate("cand")
    assert candidate.status == Status.DISQUALIFIED
    assert candidate.disqualify_reason == DisqualifyReason.NO_LICENCE


def test_fallback_question_repeats_the_name_confirmation_while_pending(make_engine):
    engine, repository, model = make_engine(
        [CONSENT, NAME, ai("", "record_full_name", {"full_name": "Ana García"}), ai("")]
    )
    start_with_name(engine, "Pedro Martínez")
    replies = drive(engine, ["sí", "Ana García", "Ana García"])
    assert replies[-1] == NAME_CONFIRM_PEDRO
    assert repository.load_state("cand")["pending_name"] == "Ana García"
    assert "confirm_name" in model.bound_tool_names[-1]


def test_webhook_style_handle_does_not_create_a_conversation(make_engine):
    engine, repository, model = make_engine([CONSENT])
    result = engine.handle("ghost", "hola", "whatsapp", external_id="g-1")
    assert result.outcome == Outcome.UNKNOWN
    assert not repository.conversation_exists("ghost")
    assert model.seen_inputs == []


def test_qualified_reply_uses_the_shared_first_name_rule(make_engine):
    engine, _, _ = make_engine(
        [
            CONSENT,
            ai("ok", "record_full_name", {"full_name": "Ana  García"}),
            LICENCE,
            ai("ok", "record_zone", {"city": "Madrid"}),
            ai("ok", "record_availability", {"availability": ["full_time"]}),
            ai("ok", "record_schedule", {"schedule": "morning"}),
            ai("ok", "record_experience", {"years": 0, "platforms": []}),
            ai("ok", "record_start_date", {"start_date": START}),
        ]
    )
    replies = drive(engine, ["sí", "Ana  García", "sí", "Madrid", "completa", "mañana", "0", START])
    assert replies[-1].startswith("¡Gracias, Ana, eso es todo!")
    assert "entrevista" not in replies[-1] and "buscamos" not in replies[-1]
    assert replies[-1].endswith(replies_module.QUESTIONS_PROMPT[Language.ES])


def test_rejected_answer_is_reasked_in_the_models_words_after_it_sees_the_result(make_engine):
    engine, repository, model = make_engine(
        [
            CONSENT,
            ai("Genial", "record_full_name", {"full_name": "Ana"}),
            ai("Gracias. ¿Me dices tu nombre completo, como aparece en tu DNI?"),
        ]
    )
    reply = drive(engine, ["sí", "soy Ana"])[-1]
    assert reply == "Gracias. ¿Me dices tu nombre completo, como aparece en tu DNI?"
    record = inbound_turns(repository)[1]
    assert record.reply_source == ReplySource.MODEL_COMPOSED
    assert record.model_text == "Genial"
    assert [usage.call for usage in record.usage] == ["turn", "compose"]
    compose_input = model.seen_inputs[-1]
    assert [m.type for m in compose_input][-3:] == ["human", "ai", "tool"]
    assert "could not be recorded" in compose_input[0].content
    assert "no tool calls" in compose_input[0].content


def test_composed_reply_breaking_the_rules_falls_back_to_the_fixed_question(make_engine):
    engine, repository, _ = make_engine(
        [CONSENT, ai("", "record_full_name", {"full_name": "Ana"}), ai("¿Nombre? ¿Apellidos?")]
    )
    reply = drive(engine, ["sí", "soy Ana"])[-1]
    assert "nombre completo" in reply
    record = inbound_turns(repository)[1]
    assert record.reply_source == ReplySource.REASK
    assert record.model_text == "¿Nombre? ¿Apellidos?"
    assert record.violated_rules == ["more than one question"]


def test_compose_failure_keeps_the_turn_and_sends_the_fallback(make_engine):
    def script():
        yield ai("", "record_consent", {"decision": "agreed"})
        raise RuntimeError("provider down")

    engine, repository, _ = make_engine(script())
    reply = drive(engine, ["sí"])[-1]
    assert "nombre completo" in reply
    record = inbound_turns(repository)[0]
    assert record.reply_source == ReplySource.NEXT_QUESTION
    assert record.violated_rules == ["compose failed: RuntimeError"]
    assert repository.load_state("cand")["consent"] is True


def test_compose_history_drops_the_unsent_draft_so_the_model_starts_fresh(make_engine):
    engine, _, model = make_engine(
        [ai("¿Hola? ¿Sigues ahí?"), ai("Soy una IA y esto queda registrado. ¿Seguimos?")]
    )
    drive(engine, ["hola"])
    assert [m.type for m in model.seen_inputs[-1]] == ["system", "ai", "human"]


def test_consent_not_now_waits_without_a_strike(make_engine):
    engine, repository, _ = make_engine(
        [ai("", "record_consent", {"decision": "not_now"}), ai("Claro, escríbeme cuando puedas.")]
    )
    reply = drive(engine, ["ahora no puedo"])[-1]
    assert reply == "Claro, escríbeme cuando puedas."
    state = repository.load_state("cand")
    assert state["consent"] is None and state["invalid_counts"] == {}
    assert repository.get_candidate("cand").stage == "consent"
    assert inbound_turns(repository)[0].reply_source == ReplySource.MODEL_COMPOSED


def test_unclear_consent_is_reasked_then_escalates(make_engine):
    def unclear():
        return ai("", "record_consent", {"decision": "unclear"})

    engine, repository, _ = make_engine([unclear(), NO_TEXT, unclear()])
    replies = drive(engine, ["no", "no"])
    assert "Soy una IA" in replies[0]
    candidate = repository.get_candidate("cand")
    assert candidate.status == Status.NEEDS_RECRUITER_REVIEW
    assert candidate.review_reason == ReviewReason.REPEATED_INVALID_ANSWER


def test_stop_request_after_consent_goes_to_recruiter_review(make_engine):
    engine, repository, model = make_engine([CONSENT, ai("", "request_stop")])
    replies = drive(engine, ["sí", "no quiero seguir, dejadme"])
    assert "request_stop" not in model.bound_tool_names[0]
    assert model.bound_tool_names[1][-1] == "request_stop"
    candidate = repository.get_candidate("cand")
    assert candidate.status == Status.NEEDS_RECRUITER_REVIEW
    assert candidate.review_reason == ReviewReason.STOP_REQUESTED
    assert "no te escribo más" in replies[-1]


def test_opener_discloses_recording_opt_out_and_asks_for_agreement():
    from screening_agent.flow import replies

    for language, stop, agree in (
        (Language.EN, "you can stop whenever you want", "happy to go ahead"),
        (Language.ES, "puedes parar cuando quieras", "Te parece bien que sigamos"),
    ):
        text = replies.opener(language, "Ana")
        assert text.startswith("¡Hola, Ana!" if language == Language.ES else "Hi, Ana!")
        assert stop in text and agree in text and "recruiting team" in text or "selección" in text


def test_compose_keeps_the_stage_tools_bound_and_ignores_a_tool_call_in_its_reply(make_engine):
    engine, repository, model = make_engine(
        [
            CONSENT,
            ai("", "record_full_name", {"full_name": "Ana"}),
            ai("¿Me dices tu nombre completo?", "record_full_name", {"full_name": "Ana"}),
        ]
    )
    reply = drive(engine, ["sí", "soy Ana"])[-1]
    assert reply == "¿Me dices tu nombre completo?"
    assert model.bound_tool_names[-1][0] == "record_full_name"
    record = inbound_turns(repository)[1]
    assert record.reply_source == ReplySource.MODEL_COMPOSED
    assert [call.name for call in record.tool_calls] == ["record_full_name"]
    state = repository.load_state("cand")
    assert state["invalid_counts"] == {"full_name": 1}
    assert not state["messages"][-1].tool_calls


def test_composed_confirmation_without_the_question_falls_back(make_engine):
    engine, repository, _ = make_engine(
        [CONSENT, NAME, ai("Gracias, Ana. Pasamos a la siguiente pregunta."), LICENCE]
    )
    start_with_name(engine, "Pedro Martínez")
    reply = drive(engine, ["sí", "Ana García"])[-1]
    assert reply == NAME_CONFIRM_PEDRO
    record = inbound_turns(repository)[1]
    assert record.reply_source == ReplySource.NAME_CONFIRM
    assert record.violated_rules == ["no question"]


def test_consent_wait_message_that_asks_a_question_falls_back(make_engine):
    engine, repository, _ = make_engine(
        [ai("", "record_consent", {"decision": "not_now"}), ai("Vale. ¿Te escribo mañana?")]
    )
    reply = drive(engine, ["ahora no"])[-1]
    assert reply == "Sin problema. Escríbeme por aquí cuando te venga bien y seguimos."
    assert inbound_turns(repository)[0].violated_rules == ["asked a question"]


def test_stop_request_wins_over_a_disqualifying_answer_in_the_same_message(make_engine):
    engine, repository, _ = make_engine(
        [
            CONSENT,
            NAME,
            ai_multi("", ("record_licence", {"has_licence": False}), ("request_stop", {})),
        ]
    )
    drive(engine, ["sí", "Ana García", "no tengo carnet y no quiero seguir"])
    candidate = repository.get_candidate("cand")
    assert candidate.status == Status.NEEDS_RECRUITER_REVIEW
    assert candidate.review_reason == ReviewReason.STOP_REQUESTED
