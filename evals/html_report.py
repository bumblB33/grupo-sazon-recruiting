import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from evals.results import BakeoffResults, GuardrailRecord, ModelRecord, PersonaRecord

SERIES_SLOTS = 8
REQUEST_ID = re.compile(r",?\s*'request_id':\s*'[^']*'")
HIGHER = "higher is better"
LOWER = "lower is better"


@dataclass(frozen=True)
class Issue:
    """One line in the verdict block. Identical errors across personas or cases collapse into one."""

    scope: str
    text: str
    count: int = 1


@dataclass(frozen=True)
class Metric:
    title: str
    direction: str
    scale_text: str | None = None


@dataclass(frozen=True)
class Cell:
    text: str
    share: float
    best: bool = False


@dataclass(frozen=True)
class ScoreRow:
    label: str
    slot: int
    cells: list[Cell]
    unavailable: str | None = None


@dataclass(frozen=True)
class MatrixCell:
    kind: str
    title: str


@dataclass(frozen=True)
class PersonaRow:
    name: str
    expected_status: str
    passes: int
    runs: list[PersonaRecord | None]
    cells: list[MatrixCell]


@dataclass(frozen=True)
class Strip:
    label: str
    slot: int
    dots: list[tuple[float, float]]
    p50_share: float | None
    p50_text: str


@dataclass(frozen=True)
class GateMeter:
    value_text: str
    share: float
    gate_share: float
    passed: bool


@dataclass(frozen=True)
class GuardrailRow:
    label: str
    slot: int
    passed: bool
    correct_text: str
    accuracy: GateMeter
    latency: GateMeter | None
    p50_text: str
    misses: list[Issue] = field(default_factory=list)


def render_html(results: BakeoffResults) -> str:
    env = Environment(
        loader=FileSystemLoader(Path(__file__).parent / "templates"),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["short"] = short_model
    latency_scale = _latency_scale(results.models)
    return env.get_template("bakeoff.html").render(
        results=results,
        issues=issues(results),
        metrics=METRICS,
        score_rows=score_rows(results.models),
        persona_rows=persona_rows(results.models),
        strips=latency_strips(results.models, latency_scale),
        latency_ticks=_ticks(latency_scale),
        guardrail_rows=guardrail_rows(results),
    )


def short_model(model_id: str) -> str:
    return model_id.partition(":")[2] or model_id


def issues(results: BakeoffResults) -> list[Issue]:
    found = []
    for model in results.models:
        found.extend(_collapse(model.live_model, _persona_issue_texts(model)))
    gates = results.gates
    for g in results.guardrails:
        reasons = g.gate_failures(gates.guardrail_min_accuracy, gates.guardrail_max_latency_seconds)
        if reasons:
            found.append(Issue(g.model, "; ".join(reasons)))
    return found


def _persona_issue_texts(model: ModelRecord) -> list[str]:
    texts = []
    for persona in model.personas:
        if persona.passed:
            continue
        texts.append(persona.error or f"{persona.name}: {'; '.join(persona.failures)}")
    return texts


def _collapse(scope: str, texts: list[str]) -> list[Issue]:
    """Provider errors carry a per-call request id; drop it so twelve identical failures fold."""
    counts = Counter(REQUEST_ID.sub("", text) for text in texts)
    return [Issue(scope, text, count) for text, count in counts.items()]


def grouped_misses(record: GuardrailRecord) -> list[Issue]:
    """Classifier errors repeat one provider message per case; show the message once with a count."""
    errors = [
        m.partition(": classifier error ")[2] for m in record.misses if ": classifier error " in m
    ]
    wrong = [m for m in record.misses if ": classifier error " not in m]
    return [Issue(record.model, text) for text in wrong] + [
        Issue(record.model, f"classifier error {text}", count)
        for text, count in Counter(REQUEST_ID.sub("", e) for e in errors).items()
    ]


METRICS = [
    Metric("Personas passed", HIGHER),
    Metric("Style failures", LOWER, "turns breaking the reply rules"),
    Metric("Tone", HIGHER, "judge, 1-5"),
    Metric("Summary", HIGHER, "judge, 1-5"),
    Metric("p50 latency", LOWER, "per reply"),
    Metric("Cost", LOWER, "turn model, per screening"),
]


def score_rows(models: list[ModelRecord]) -> list[ScoreRow]:
    persona_count = max((len(m.personas) for m in models), default=0)
    columns: list[
        tuple[Callable[[ModelRecord], float | None], Callable[[float], str], float | None, bool]
    ] = [
        (lambda m: m.passed, lambda v: f"{v:.0f}/{persona_count}", persona_count, True),
        (lambda m: m.style_failures, lambda v: f"{v:.0f}", None, False),
        (lambda m: m.tone, lambda v: f"{v:.1f}", 5, True),
        (lambda m: m.summary_score, lambda v: f"{v:.1f}", 5, True),
        (lambda m: m.latency_p50, lambda v: f"{v:.1f}s", None, False),
        (lambda m: m.cost_per_screening, lambda v: f"${v:.4f}", None, False),
    ]
    cells_by_model: list[list[Cell]] = [[] for _ in models]
    for value_of, fmt, maximum, higher_better in columns:
        values = [value_of(m) if _ran(m) else None for m in models]
        known = [v for v in values if v is not None]
        scale = maximum if maximum is not None else max(known, default=0)
        best = (max(known) if higher_better else min(known)) if len(known) > 1 else None
        for cells, value in zip(cells_by_model, values, strict=True):
            if value is None:
                cells.append(Cell("n/a", 0.0))
            else:
                cells.append(Cell(fmt(value), _share(value, scale), best=value == best))
    return [
        ScoreRow(m.live_model, i % SERIES_SLOTS, cells, unavailable=_unavailable(m))
        for i, (m, cells) in enumerate(zip(models, cells_by_model, strict=True))
    ]


def _ran(model: ModelRecord) -> bool:
    return any(p.turns for p in model.personas)


def _unavailable(model: ModelRecord) -> str | None:
    """A model whose every persona died with the same error never ran; the number cells would lie."""
    errors = {REQUEST_ID.sub("", p.error) if p.error else None for p in model.personas}
    if model.personas and len(errors) == 1 and None not in errors and not _ran(model):
        return next(iter(errors))
    return None


def persona_rows(models: list[ModelRecord]) -> list[PersonaRow]:
    """One row per persona in first-model order, so a persona a later model skipped still shows as not run."""
    if not models:
        return []
    by_model = [{p.name: p for p in m.personas} for m in models]
    rows = []
    for persona in models[0].personas:
        runs = [personas.get(persona.name) for personas in by_model]
        passes = sum(1 for run in runs if run and run.passed)
        rows.append(
            PersonaRow(
                persona.name, persona.expected_status, passes, runs, [_matrix_cell(r) for r in runs]
            )
        )
    return rows


def _matrix_cell(run: PersonaRecord | None) -> MatrixCell:
    if run is None:
        return MatrixCell("none", "not run")
    if run.passed:
        return MatrixCell("pass", f"pass, ended {run.status}")
    if run.error and not run.turns:
        return MatrixCell("error", run.error)
    return MatrixCell("fail", "; ".join(run.failures))


def latency_strips(models: list[ModelRecord], scale: float) -> list[Strip]:
    strips = []
    for i, m in enumerate(models):
        latencies = sorted(t.latency_seconds for p in m.personas for t in p.turns)
        dots = [(_share(v, scale), v) for v in latencies]
        p50 = m.latency_p50 if latencies else None
        strips.append(
            Strip(
                m.live_model,
                i % SERIES_SLOTS,
                dots,
                None if p50 is None else _share(p50, scale),
                "no replies" if p50 is None else f"p50 {p50:.1f}s",
            )
        )
    return strips


def _latency_scale(models: list[ModelRecord]) -> float:
    longest = max(
        (t.latency_seconds for m in models for p in m.personas for t in p.turns), default=0
    )
    return max(1.0, float(int(longest) + 1))


def _ticks(scale: float) -> list[tuple[float, str]]:
    step = max(1, int(scale // 5))
    return [(_share(s, scale), f"{s}s") for s in range(0, int(scale) + 1, step)]


def guardrail_rows(results: BakeoffResults) -> list[GuardrailRow]:
    gates = results.gates
    records = results.guardrails
    latency_scale = (
        max([g.latency_p95 for g in records] + [gates.guardrail_max_latency_seconds]) * 1.15
    )
    rows = []
    for i, g in enumerate(records):
        latency = None
        if g.latencies:
            latency = GateMeter(
                f"{g.latency_p95:.2f}s",
                _share(g.latency_p95, latency_scale),
                _share(gates.guardrail_max_latency_seconds, latency_scale),
                g.latency_p95 <= gates.guardrail_max_latency_seconds,
            )
        rows.append(
            GuardrailRow(
                g.model,
                i % SERIES_SLOTS,
                results.guardrail_passed(g),
                f"{g.correct}/{g.total}",
                GateMeter(
                    f"{g.accuracy:.0%}",
                    _share(g.accuracy, 1.0),
                    _share(gates.guardrail_min_accuracy, 1.0),
                    g.accuracy >= gates.guardrail_min_accuracy,
                ),
                latency,
                f"{g.latency_p50:.2f}s" if g.latencies else "n/a",
                grouped_misses(g),
            )
        )
    return rows


def _share(value: float, scale: float) -> float:
    return round(min(value / scale, 1.0) * 100, 1) if scale else 0.0
