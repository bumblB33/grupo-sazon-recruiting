from evals.results import BakeoffResults


def render(results: BakeoffResults) -> str:
    lines = ["# Model bake-off", "", f"Result: {'PASS' if results.passed else 'FAIL'}", ""]
    lines += [
        "## Turn model",
        "",
        "| Model | Personas passed | Style failures | Tone (1-5) | Summary (1-5) | p50 latency | Turn-model cost per screening |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for model in results.models:
        lines.append(
            f"| {model.live_model} | {model.passed}/{len(model.personas)} | {model.style_failures} "
            f"| {_fmt(model.tone, '{:.1f}')} | {_fmt(model.summary_score, '{:.1f}')} "
            f"| {model.latency_p50:.1f}s | {_fmt(model.cost_per_screening, '${:.4f}')} |"
        )
    for model in results.models:
        lines += ["", f"### {model.live_model}", ""]
        for persona in model.personas:
            status = "PASS" if persona.passed else "FAIL " + "; ".join(persona.failures)
            lines.append(f"- {persona.name}: {status}")
            for turn in persona.turns:
                if turn.style:
                    lines.append(f"  - style: {', '.join(turn.style)}: {turn.reply!r}")
            for key in ("tone", "summary"):
                if key in persona.judge:
                    verdict = persona.judge[key]
                    lines.append(f"  - {key} {verdict.score}: {verdict.reason}")
    if results.guardrails:
        gates = results.gates
        lines += [
            "",
            "## Guardrail classifier",
            "",
            f"Gate: accuracy >= {gates.guardrail_min_accuracy:.0%} and p95 latency <= {gates.guardrail_max_latency_seconds:.1f}s.",
            "",
            "| Model | Accuracy | p50 latency | p95 latency | Gate |",
            "| --- | --- | --- | --- | --- |",
        ]
        for score in results.guardrails:
            lines.append(
                f"| {score.model} | {score.correct}/{score.total} ({score.accuracy:.0%}) "
                f"| {score.latency_p50:.2f}s | {score.latency_p95:.2f}s "
                f"| {'PASS' if results.guardrail_passed(score) else 'FAIL'} |"
            )
        for score in results.guardrails:
            for miss in score.misses:
                lines.append(f"- {score.model}: {miss}")
    return "\n".join(lines) + "\n"


def _fmt(value: float | None, pattern: str) -> str:
    return "n/a" if value is None else pattern.format(value)
