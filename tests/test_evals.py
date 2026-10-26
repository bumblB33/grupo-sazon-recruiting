import sys
from datetime import UTC, datetime

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from pymongo import MongoClient

from evals import run_evals
from evals.graders import Expectation, GradeResult, grade, style_failures
from evals.guardrail_cases import GuardrailCase, score_cases, score_guardrail
from evals.judge import Verdict
from evals.personas.text_personas import PERSONAS, Persona
from evals.pricing import cost_usd
from evals.report import ModelResult, render
from evals.run_evals import _parse, eval_database_url
from evals.runner import PersonaRun, Turn, run_persona
from screening_agent.domain.enums import Language
from screening_agent.llm.guardrail import Classification, Guardrail, GuardrailCategory
from screening_agent.storage.models import Candidate
from tests.conftest import ai

NOW = datetime.now(UTC)


def candidate(**fields) -> Candidate:
    return Candidate(id="c", created_at=NOW, updated_at=NOW, **fields)


def test_grade_compares_lists_as_sets_and_checks_review_reason():
    expected = Expectation(
        status="needs_recruiter_review",
        review_reason="low_confidence_zone",
        profile={"availability": ["weekends", "part_time"]},
    )
    good = candidate(
        status="needs_recruiter_review",
        review_reason="low_confidence_zone",
        profile={"availability": ["part_time", "weekends"]},
    )
    assert grade(good, 3, expected).passed
    bad = candidate(status="needs_recruiter_review", review_reason="consent_declined", profile={})
    failures = grade(bad, 3, expected).failures
    assert any("review" in f for f in failures) and any("availability" in f for f in failures)


def test_style_failures_flag_questions_emoji_length_and_language():
    assert style_failures("¿Nombre? ¿Y apellido?", Language.ES) == ["more than one question"]
    assert "more than one emoji" in style_failures("Hola 😀🚀 ¿nombre?", Language.ES)
    assert style_failures("Hola 👍🏽 ¿nombre?", Language.ES) == []
    assert style_failures("Hola 👨\u200d🍳 ¿nombre?", Language.ES) == []
    assert "reply longer than 280 chars" in style_failures("a" * 281, Language.ES)
    assert style_failures(
        "¿En qué ciudad vives? Así veo si tenemos restaurante cerca.", Language.EN
    ) == ["reply not in en"]
    assert style_failures("¿En qué ciudad vives?", Language.ES) == []


def test_score_cases_counts_misses_and_classifier_errors():
    always_off = Guardrail(
        RunnableLambda(lambda m: Classification(category=GuardrailCategory.OFF_TOPIC))
    )
    cases = (
        GuardrailCase("sí", GuardrailCategory.ON_TOPIC),
        GuardrailCase("un chiste", GuardrailCategory.OFF_TOPIC),
    )
    score = score_cases(always_off, "fake", cases)
    assert (score.correct, score.total) == (1, 2)
    assert score.accuracy == 0.5

    def boom(messages):
        raise TimeoutError

    broken = Guardrail(RunnableLambda(boom))
    score = score_cases(broken, "broken", cases)
    assert score.correct == 0 and all("error" in miss for miss in score.misses)


def test_cost_known_and_unknown_models():
    assert cost_usd("anthropic:claude-haiku-5-5", 1_000_000, 1_000_000) == 0.6
    assert cost_usd("unknown:model", 10, 10) is None


def test_render_lists_models_and_failures():
    persona = Persona("p", ("hola",), Expectation(status="qualified"))
    run = PersonaRun(
        persona,
        (Turn("hola", "¿Nombre? ¿Edad?", 0.5, ("more than one question",)),),
        None,
        GradeResult(False, ("status in_progress != qualified",)),
        100,
        20,
        judge={"tone": Verdict(score=4, reason="warm")},
    )
    text = render([ModelResult("anthropic:claude-haiku-5-5", (run,))], [])
    assert "| anthropic:claude-haiku-5-5 | 0/1 | 1 | 4.0 | 0.5s | $0.0000 |" in text
    assert "FAIL status in_progress != qualified" in text
    assert "style: more than one question" in text


def test_eval_database_url_keeps_query_string():
    assert (
        eval_database_url("mongodb://h/screening?authSource=admin", "ab12")
        == "mongodb://h/screening_eval_ab12?authSource=admin"
    )
    assert eval_database_url("mongodb://h/screening", "ab12") == "mongodb://h/screening_eval_ab12"


def test_persona_names_are_unique():
    names = [persona.name for persona in PERSONAS]
    assert len(names) == len(set(names))


def test_run_persona_records_turns_tokens_and_grade(make_engine):
    engine, repository, _ = make_engine(
        [
            ai("Hola", "record_consent", {"accepted": True}),
            ai("¿Nombre?", "record_full_name", {"full_name": "Luis Hernández"}),
            ai("¿Carnet?", "record_licence", {"has_licence": False}),
        ]
    )
    persona = next(p for p in PERSONAS if p.name == "no_licence")
    run = run_persona(engine, repository, persona)
    assert run.grade.passed, run.grade.failures
    assert run.error is None
    # The scripted licence refusal closes the conversation on turn 3; the fourth turn is never sent.
    assert [turn.candidate for turn in run.turns] == list(persona.turns[:3])
    assert run.candidate.status == "disqualified"
    assert run.candidate.summary == "summary"
    assert run.input_tokens == 0


def test_run_persona_survives_engine_crash(make_engine):
    engine, repository, _ = make_engine([])
    run = run_persona(engine, repository, PERSONAS[0])
    assert not run.grade.passed
    assert run.error


def test_run_persona_sums_provider_usage_from_the_stored_transcript(make_engine):
    usage = {"input_tokens": 120, "output_tokens": 30, "total_tokens": 150}
    script = [
        AIMessage(
            content="Hola",
            tool_calls=[_call("record_consent", {"accepted": True})],
            usage_metadata=usage,
        ),
        AIMessage(
            content="¿Nombre?",
            tool_calls=[_call("record_full_name", {"full_name": "Luis Hernández"})],
            usage_metadata=usage,
        ),
        AIMessage(
            content="¿Carnet?",
            tool_calls=[_call("record_licence", {"has_licence": False})],
            usage_metadata=usage,
        ),
    ]
    engine, repository, _ = make_engine(script)
    run = run_persona(engine, repository, next(p for p in PERSONAS if p.name == "no_licence"))
    assert (run.input_tokens, run.output_tokens) == (360, 90)


def test_empty_models_list_is_a_usage_error(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run_evals", "--models", ""])
    with pytest.raises(SystemExit) as exit_:
        _parse()
    assert exit_.value.code == 2


def _call(name: str, args: dict) -> dict:
    return {"name": name, "args": args, "id": "c1", "type": "tool_call"}


@pytest.mark.parametrize("keep", [False, True])
def test_eval_database_is_dropped_unless_kept(mongo_url, monkeypatch, keep):
    used: list[str] = []

    def fake_run(live_model, engine, repository, judge):
        repository.candidates.insert_one({"_id": "probe"})
        used.append(repository.db.name)
        return []

    monkeypatch.setattr(run_evals, "build_engine", lambda repository, models: None)
    monkeypatch.setattr(run_evals, "_run_personas", fake_run)
    database = f"{mongo_url.rstrip('/')}/evaldrop?authSource=admin"
    argv = ["run_evals", "--models", "fake:model", "--db", database]
    monkeypatch.setattr(sys, "argv", argv + (["--keep-db"] if keep else []))
    run_evals.main()
    client = MongoClient(mongo_url)
    assert (used[0] in client.list_database_names()) is keep
    client.drop_database(used[0])


def test_db_without_database_name_is_a_usage_error(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run_evals", "--db", "mongodb://host:27017"])
    with pytest.raises(SystemExit) as exit_:
        _parse()
    assert exit_.value.code == 2


def test_unavailable_guardrail_model_scores_zero_instead_of_raising():
    score = score_guardrail("openai:gpt-6-luna")
    assert score.correct == 0 and "OPENAI_API_KEY" in score.misses[0]
