from dataclasses import dataclass
from statistics import mean, median

from evals.guardrail_cases import GuardrailScore
from evals.pricing import cost_usd
from evals.runner import PersonaRun


@dataclass(frozen=True)
class ModelResult:
    live_model: str
    runs: tuple[PersonaRun, ...]

    @property
    def passed(self) -> int:
        return sum(run.grade.passed for run in self.runs)

    @property
    def style_failures(self) -> int:
        return sum(run.style_failure_count for run in self.runs)

    @property
    def latency_p50(self) -> float:
        latencies = [turn.latency_seconds for run in self.runs for turn in run.turns]
        return median(latencies) if latencies else 0.0

    @property
    def tone(self) -> float | None:
        scores = [run.judge["tone"].score for run in self.runs if "tone" in run.judge]
        return mean(scores) if scores else None

    @property
    def cost_per_screening(self) -> float | None:
        costs = [
            cost_usd(self.live_model, run.input_tokens, run.output_tokens) for run in self.runs
        ]
        return None if not costs or any(c is None for c in costs) else mean(costs)


def render(results: list[ModelResult], guardrails: list[GuardrailScore]) -> str:
    lines = ["# Model bake-off", "", "## Turn model", ""]
    lines.append(
        "| Model | Personas passed | Style failures | Tone (1-5) | p50 latency | Turn-model cost per screening |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for result in results:
        lines.append(
            f"| {result.live_model} | {result.passed}/{len(result.runs)} | {result.style_failures} "
            f"| {_fmt(result.tone, '{:.1f}')} | {result.latency_p50:.1f}s "
            f"| {_fmt(result.cost_per_screening, '${:.4f}')} |"
        )
    for result in results:
        lines += ["", f"### {result.live_model}", ""]
        for run in result.runs:
            status = "PASS" if run.grade.passed else "FAIL " + "; ".join(run.grade.failures)
            lines.append(f"- {run.persona.name}: {status}")
            for turn in run.turns:
                if turn.style:
                    lines.append(f"  - style: {', '.join(turn.style)}: {turn.reply!r}")
            if "tone" in run.judge:
                lines.append(f"  - tone {run.judge['tone'].score}: {run.judge['tone'].reason}")
            if "summary" in run.judge:
                lines.append(
                    f"  - summary {run.judge['summary'].score}: {run.judge['summary'].reason}"
                )
    if guardrails:
        lines += ["", "## Guardrail classifier", "", "| Model | Accuracy |", "| --- | --- |"]
        for score in guardrails:
            lines.append(
                f"| {score.model} | {score.correct}/{score.total} ({score.accuracy:.0%}) |"
            )
        for score in guardrails:
            for miss in score.misses:
                lines.append(f"- {score.model}: {miss}")
    return "\n".join(lines) + "\n"


def _fmt(value: float | None, pattern: str) -> str:
    return "n/a" if value is None else pattern.format(value)
