import json
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median

from pydantic import BaseModel, Field

from evals.guardrail_cases import GuardrailScore
from evals.pricing import cost_usd
from evals.runner import PersonaRun

# Bump on any change a renderer cannot read; an old file then fails with a clear message.
SCHEMA_VERSION = 1


class IncompatibleResultsError(ValueError):
    pass


class TurnRecord(BaseModel):
    candidate: str
    reply: str
    latency_seconds: float
    style: list[str] = Field(default_factory=list)
    model_text: str | None = None
    policy_fallback: bool = False


class JudgeVerdict(BaseModel):
    score: int
    reason: str


class PersonaRecord(BaseModel):
    name: str
    expected_status: str
    passed: bool
    failures: list[str]
    turns: list[TurnRecord]
    status: str | None = None
    profile: dict = Field(default_factory=dict)
    summary: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None
    judge: dict[str, JudgeVerdict] = Field(default_factory=dict)

    @property
    def style_failure_count(self) -> int:
        return sum(len(turn.style) for turn in self.turns)

    @property
    def completed(self) -> bool:
        """A run cut short by an error spent fewer tokens than a screening, so it would flatter cost."""
        return bool(self.turns) and self.error is None


class ModelRecord(BaseModel):
    live_model: str
    personas: list[PersonaRecord]

    @property
    def ran(self) -> bool:
        return any(p.turns for p in self.personas)

    @property
    def passed(self) -> int:
        return sum(persona.passed for persona in self.personas)

    @property
    def style_failures(self) -> int:
        return sum(persona.style_failure_count for persona in self.personas)

    @property
    def policy_fallback_rate(self) -> float | None:
        turns = [turn for p in self.personas for turn in p.turns]
        return sum(turn.policy_fallback for turn in turns) / len(turns) if turns else None

    @property
    def latency_p50(self) -> float | None:
        latencies = [turn.latency_seconds for p in self.personas for turn in p.turns]
        return median(latencies) if latencies else None

    @property
    def tone(self) -> float | None:
        return self._judge_mean("tone")

    @property
    def summary_score(self) -> float | None:
        return self._judge_mean("summary")

    @property
    def cost_per_screening(self) -> float | None:
        costs = [
            cost_usd(self.live_model, p.input_tokens, p.output_tokens)
            for p in self.personas
            if p.completed
        ]
        priced = [c for c in costs if c is not None]
        # One unpriced persona makes the mean wrong, so the report shows no cost instead.
        return mean(priced) if priced and len(priced) == len(costs) else None

    def _judge_mean(self, key: str) -> float | None:
        scores = [p.judge[key].score for p in self.personas if key in p.judge]
        return mean(scores) if scores else None


class Gates(BaseModel):
    guardrail_min_accuracy: float
    guardrail_max_latency_seconds: float
    # Zero means not gated, which is how results written before tone scoring read back.
    tone_min_accuracy: float = 0.0

    def accuracy_passes(self, score: GuardrailScore) -> bool:
        return score.accuracy >= self.guardrail_min_accuracy

    def latency_passes(self, score: GuardrailScore) -> bool:
        """No answered call means no latency to judge; such a model already fails on accuracy."""
        return not score.latencies or score.latency_p95 <= self.guardrail_max_latency_seconds

    def failures(self, score: GuardrailScore) -> list[str]:
        if score.unavailable:
            return [f"unavailable: {score.unavailable}"]
        failures = []
        if not self.accuracy_passes(score):
            failures.append(f"accuracy {score.accuracy:.0%} < {self.guardrail_min_accuracy:.0%}")
        if score.tone_accuracy < self.tone_min_accuracy:
            failures.append(
                f"tone accuracy {score.tone_accuracy:.0%} < {self.tone_min_accuracy:.0%}"
            )
        if not self.latency_passes(score):
            failures.append(
                f"p95 latency {score.latency_p95:.1f}s > {self.guardrail_max_latency_seconds:.1f}s"
            )
        return failures


class BakeoffResults(BaseModel):
    """The JSON contract between a live run and the renderer, so the report can be rebuilt offline."""

    schema_version: int = SCHEMA_VERSION
    generated_at: datetime
    summary_model: str
    guardrail_model: str
    judge_model: str | None
    gates: Gates
    models: list[ModelRecord]
    guardrails: list[GuardrailScore]

    @classmethod
    def from_runs(
        cls,
        runs_by_model: dict[str, list[PersonaRun]],
        guardrails: list[GuardrailScore],
        *,
        summary_model: str,
        guardrail_model: str,
        judge_model: str | None,
        gates: Gates,
    ) -> "BakeoffResults":
        return cls(
            generated_at=datetime.now(UTC),
            summary_model=summary_model,
            guardrail_model=guardrail_model,
            judge_model=judge_model,
            gates=gates,
            models=[
                ModelRecord(live_model=model, personas=[_persona_record(r) for r in runs])
                for model, runs in runs_by_model.items()
            ],
            guardrails=guardrails,
        )

    @property
    def persona_failures(self) -> list[str]:
        return [
            f"{m.live_model} {p.name}: {'; '.join(p.failures)}"
            for m in self.models
            for p in m.personas
            if not p.passed
        ]

    @property
    def guardrail_failures(self) -> list[str]:
        return [
            f"{g.model}: {'; '.join(reasons)}"
            for g in self.guardrails
            if (reasons := self.gates.failures(g))
        ]

    @property
    def passed(self) -> bool:
        return not self.persona_failures and not self.guardrail_failures

    def guardrail_passed(self, score: GuardrailScore) -> bool:
        return not self.gates.failures(score)

    def save(self, path: Path) -> None:
        path.write_text(self.model_dump_json(indent=2) + "\n")

    @classmethod
    def load(cls, path: Path) -> "BakeoffResults":
        text = path.read_text()
        version = json.loads(text).get("schema_version")
        if version != SCHEMA_VERSION:
            raise IncompatibleResultsError(
                f"{path} has schema version {version}, this renderer reads {SCHEMA_VERSION}; "
                "re-run the evals to produce it"
            )
        return cls.model_validate_json(text)


def _persona_record(run: PersonaRun) -> PersonaRecord:
    candidate = run.candidate
    return PersonaRecord(
        name=run.persona.name,
        expected_status=run.persona.expected.status,
        passed=run.grade.passed,
        failures=list(run.grade.failures),
        turns=[
            TurnRecord(
                candidate=t.candidate,
                reply=t.reply,
                latency_seconds=t.latency_seconds,
                style=list(t.style),
                model_text=t.model_text,
                policy_fallback=t.policy_fallback,
            )
            for t in run.turns
        ],
        status=candidate.status if candidate else None,
        profile=candidate.profile if candidate else {},
        summary=candidate.summary if candidate else None,
        input_tokens=run.input_tokens,
        output_tokens=run.output_tokens,
        error=run.error,
        judge={k: JudgeVerdict(score=v.score, reason=v.reason) for k, v in run.judge.items()},
    )
