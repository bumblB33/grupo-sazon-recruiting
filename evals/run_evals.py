import argparse
import sys
import uuid
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit

from evals.guardrail_cases import score_guardrail
from evals.judge import JUDGE_MODEL, Judge
from evals.personas.text_personas import PERSONAS
from evals.render_report import write_reports
from evals.results import BakeoffResults, Gates
from evals.runner import ModelSet, PersonaRun, build_engine, run_persona
from screening_agent.config import settings
from screening_agent.flow.engine import ScreeningEngine
from screening_agent.llm.models import chat_model
from screening_agent.storage.repository import Repository


def main() -> int:
    args = _parse()
    judge = Judge(args.judge_model) if args.judge else None
    runs_by_model: dict[str, list[PersonaRun]] = {}
    for live_model in args.models:
        models = ModelSet(live_model, args.summary_model, args.guardrail_model)
        repository = Repository(eval_database_url(args.db, uuid.uuid4().hex[:8]))
        try:
            runs = _run_personas(live_model, build_engine(repository, models), repository, judge)
        finally:
            if args.keep_db:
                print(f"kept database {repository.db.name}", file=sys.stderr)
            else:
                repository.client.drop_database(repository.db.name)
            repository.client.close()
        runs_by_model[live_model] = runs
    guardrails = [score_guardrail(model_id) for model_id in args.guardrail_models]
    for score in guardrails:
        print(
            f"guardrail {score.model} {score.correct}/{score.total} p95 {score.latency_p95:.2f}s",
            file=sys.stderr,
        )
    results = BakeoffResults.from_runs(
        runs_by_model,
        guardrails,
        summary_model=args.summary_model,
        guardrail_model=args.guardrail_model,
        judge_model=args.judge_model if args.judge else None,
        gates=Gates(
            guardrail_min_accuracy=args.guardrail_min_accuracy,
            guardrail_max_latency_seconds=args.guardrail_max_latency_seconds,
        ),
    )
    for failure in results.guardrail_failures:
        print(f"guardrail gate failed: {failure}", file=sys.stderr)
    if args.out:
        for path in write_reports(results, Path(args.out)):
            print(f"written {path}", file=sys.stderr)
    print("PASS" if results.passed else "FAIL", file=sys.stderr)
    return 0 if results.passed else 1


def _run_personas(
    live_model: str, engine: ScreeningEngine, repository: Repository, judge: Judge | None
) -> list[PersonaRun]:
    runs = []
    for persona in PERSONAS:
        run = run_persona(engine, repository, persona)
        if judge and run.turns:
            scores = {"tone": judge.transcript(list(run.turns))}
            if run.candidate and run.candidate.summary:
                scores["summary"] = judge.summary(
                    run.candidate.summary, list(run.turns), run.candidate.profile
                )
            run = replace(run, judge={k: v for k, v in scores.items() if v is not None})
        print(
            f"{live_model} {'PASS' if run.grade.passed else 'FAIL'} {persona.name} {list(run.grade.failures)}",
            file=sys.stderr,
        )
        runs.append(run)
    return runs


def eval_database_url(database_url: str, suffix: str) -> str:
    """Each model gets its own database; the suffix goes before any connection options."""
    base, separator, query = database_url.partition("?")
    return f"{base}_eval_{suffix}{separator}{query}"


def _parse() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Persona evals and model bake-off against live providers. Examples in README."
    )
    parser.add_argument(
        "--models", type=_csv, default=[settings.live_model], help="turn models, comma separated"
    )
    parser.add_argument("--summary-model", default=settings.summary_model)
    parser.add_argument(
        "--guardrail-model",
        default=settings.guardrail_model,
        help="classifier used during persona runs",
    )
    parser.add_argument(
        "--guardrail-models",
        type=_csv,
        default=[],
        help="classifier models to score on the labelled set",
    )
    parser.add_argument(
        "--judge", action="store_true", help="score tone and summary with an LLM judge"
    )
    parser.add_argument("--judge-model", default=JUDGE_MODEL)
    parser.add_argument(
        "--guardrail-min-accuracy",
        type=float,
        default=0.9,
        help="a scored classifier below this accuracy fails the run",
    )
    parser.add_argument(
        "--guardrail-max-latency-seconds",
        type=float,
        default=2.5,
        help="a scored classifier with p95 latency above this fails the run",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="directory for bakeoff.json and bakeoff.html; without it only the verdict is printed",
    )
    parser.add_argument(
        "--db",
        default=settings.eval_database_url,
        help="Mongo for throwaway eval databases; never the app's SCREENING_DATABASE_URL",
    )
    parser.add_argument(
        "--keep-db", action="store_true", help="keep each eval database to inspect transcripts"
    )
    args = parser.parse_args()
    if not args.models:
        parser.error("--models needs at least one model id")
    if not urlsplit(args.db).path.strip("/"):
        parser.error("--db must name a database, e.g. mongodb://host:27017/screening")
    for model_id in _models_used_in_runs(args):
        try:
            chat_model(model_id)
        except Exception as exc:
            parser.error(f"{model_id}: {type(exc).__name__}: {exc}")
    return args


def _models_used_in_runs(args: argparse.Namespace) -> list[str]:
    """Checked before any paid call: a bad id mid-run would end it before results are written.
    Scored guardrail models are left out, an unusable one scores zero instead."""
    judge = [args.judge_model] if args.judge else []
    return [*args.models, args.summary_model, args.guardrail_model, *judge]


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


if __name__ == "__main__":
    sys.exit(main())
