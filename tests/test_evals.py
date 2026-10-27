import sys
from datetime import UTC, datetime

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from pymongo import MongoClient

from evals import run_evals
from evals.graders import Expectation, GradeResult, grade, style_failures
from evals.guardrail_cases import GuardrailCase, GuardrailScore, score_cases, score_guardrail
from evals.html_report import render_html
from evals.judge import Verdict
from evals.personas.text_personas import PERSONAS, Persona
from evals.pricing import cost_usd
from evals.report import render
from evals.results import BakeoffResults, Gates
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


GATES = Gates(guardrail_min_accuracy=0.9, guardrail_max_latency_seconds=2.5)


def failing_run() -> PersonaRun:
    persona = Persona("p", ("hola",), Expectation(status="qualified"))
    return PersonaRun(
        persona,
        (Turn("hola", "¿Nombre? ¿Edad?", 0.5, ("more than one question",)),),
        candidate(status="in_progress", summary="Sin datos."),
        GradeResult(False, ("status in_progress != qualified",)),
        100,
        20,
        judge={"tone": Verdict(score=4, reason="warm")},
    )


def results_with(runs, guardrails=()) -> BakeoffResults:
    return BakeoffResults.from_runs(
        {"anthropic:claude-haiku-5-5": runs},
        list(guardrails),
        summary_model="s",
        guardrail_model="g",
        judge_model=None,
        gates=GATES,
    )


def test_render_lists_models_and_failures():
    text = render(results_with([failing_run()]))
    assert "| anthropic:claude-haiku-5-5 | 0/1 | 1 | 4.0 | n/a | 0.5s | $0.0000 |" in text
    assert "FAIL status in_progress != qualified" in text
    assert "style: more than one question" in text


def test_results_round_trip_through_json(tmp_path):
    results = results_with([failing_run()], [GuardrailScore("g", 18, 18, (), (0.3, 0.4))])
    results.save(tmp_path / "bakeoff.json")
    assert BakeoffResults.load(tmp_path / "bakeoff.json") == results
    assert results.models[0].personas[0].expected_status == "qualified"


def test_guardrail_gate_fails_on_accuracy_latency_or_unavailable_model():
    slow = GuardrailScore("slow", 18, 18, (), tuple([0.5] * 18 + [9.0]))
    weak = GuardrailScore("weak", 15, 18, ("miss",), tuple([0.5] * 18))
    gone = GuardrailScore("gone", 0, 18, ("unavailable: ProviderKeyMissingError",))
    good = GuardrailScore("good", 17, 18, ("miss",), tuple([0.5] * 18))
    results = results_with([], [slow, weak, gone, good])
    failures = results.guardrail_failures
    assert [f.split(":")[0] for f in failures] == ["slow", "weak", "gone"]
    assert "p95 latency 9.0s > 2.5s" in failures[0]
    assert "accuracy 83% < 90%" in failures[1]
    assert results.guardrail_passed(results.guardrails[3])
    assert not results.passed


def test_score_cases_records_a_latency_per_case():
    always_on = Guardrail(
        RunnableLambda(lambda m: Classification(category=GuardrailCategory.ON_TOPIC))
    )
    cases = (GuardrailCase("sí", GuardrailCategory.ON_TOPIC),) * 3
    score = score_cases(always_on, "fake", cases)
    assert len(score.latencies) == 3 and score.latency_p95 >= score.latency_p50 >= 0


def test_html_report_shows_gates_matrix_and_transcripts():
    results = results_with([failing_run()], [GuardrailScore("weak", 15, 18, ("miss",), (0.5,))])
    html = render_html(results)
    assert "✗ FAIL" in html
    assert 'href="#persona-p"' in html and '<details id="persona-p">' in html
    assert "¿Nombre? ¿Edad?" in html and "more than one question" in html
    assert "gate &gt;= 90%" in html and "accuracy 83% &lt; 90%" in html


def errored_run(name: str, request_id: str) -> PersonaRun:
    persona = Persona(name, ("hola",), Expectation(status="qualified"))
    error = f"Error code: 400 - {{'message': 'bad key', 'request_id': '{request_id}'}}"
    return PersonaRun(persona, (), None, GradeResult(False, (error,)), 0, 0, error=error)


def test_html_report_folds_identical_provider_errors_into_one_line():
    results = BakeoffResults.from_runs(
        {"anthropic:claude-sonnet-5-5": [errored_run("a", "req_1"), errored_run("b", "req_2")]},
        [GuardrailScore("g", 0, 2, ("'sí': classifier error boom", "'no': classifier error boom"))],
        summary_model="s",
        guardrail_model="g",
        judge_model=None,
        gates=GATES,
    )
    html = render_html(results)
    assert html.count("×2") == 2
    overview = html.partition("Outcome per persona")[0]
    assert "did not run" in overview
    assert "req_1" not in overview and "req_2" not in overview
    assert html.count('<a class="error"') == 2


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
