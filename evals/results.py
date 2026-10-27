from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median

from pydantic import BaseModel, Field

from evals.guardrail_cases import GuardrailScore, latency_p50, latency_p95
from evals.pricing import cost_usd
from evals.runner import PersonaRun


class TurnRecord(BaseModel):
    candidate: str
    reply: str
    latency_seconds: float
    style: list[str] = Field(default_factory=list)


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


class ModelRecord(BaseModel):
    live_model: str
    personas: list[PersonaRecord]

    @property
    def passed(self) -> int:
        return sum(persona.passed for persona in self.personas)

    @property
    def style_failures(self) -> int:
        return sum(persona.style_failure_count for persona in self.personas)

    @property
    def latency_p50(self) -> float:
        latencies = [turn.latency_seconds for p in self.personas for turn in p.turns]
        return median(latencies) if latencies else 0.0

    @property
    def tone(self) -> float | None:
        return self._judge_mean("tone")

    @property
    def summary_score(self) -> float | None:
        return self._judge_mean("summary")

    @property
    def input_tokens(self) -> int:
        return sum(persona.input_tokens for persona in self.personas)

    @property
    def output_tokens(self) -> int:
        return sum(persona.output_tokens for persona in self.personas)

    @property
    def cost_per_screening(self) -> float | None:
        costs = [cost_usd(self.live_model, p.input_tokens, p.output_tokens) for p in self.personas]
        return None if not costs or any(c is None for c in costs) else mean(costs)

    def _judge_mean(self, key: str) -> float | None:
        scores = [p.judge[key].score for p in self.personas if key in p.judge]
        return mean(scores) if scores else None


class GuardrailRecord(BaseModel):
    model: str
    correct: int
    total: int
    misses: list[str]
    latencies: list[float] = Field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    @property
    def latency_p50(self) -> float:
        return latency_p50(self.latencies)

    @property
    def latency_p95(self) -> float:
        return latency_p95(self.latencies)

    def gate_failures(self, min_accuracy: float, max_latency_seconds: float) -> list[str]:
        """An unavailable model has no latencies and zero accuracy, so it fails on accuracy alone."""
        failures = []
        if self.accuracy < min_accuracy:
            failures.append(f"accuracy {self.accuracy:.0%} < {min_accuracy:.0%}")
        if self.latencies and self.latency_p95 > max_latency_seconds:
            failures.append(f"p95 latency {self.latency_p95:.1f}s > {max_latency_seconds:.1f}s")
        return failures


class Gates(BaseModel):
    guardrail_min_accuracy: float
    guardrail_max_latency_seconds: float


class BakeoffResults(BaseModel):
    """The JSON contract between a live run and the renderers, so the report can be rebuilt offline."""

    generated_at: datetime
    summary_model: str
    guardrail_model: str
    judge_model: str | None
    gates: Gates
    models: list[ModelRecord]
    guardrails: list[GuardrailRecord]

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
            guardrails=[
                GuardrailRecord(
                    model=s.model,
                    correct=s.correct,
                    total=s.total,
                    misses=list(s.misses),
                    latencies=list(s.latencies),
                )
                for s in guardrails
            ],
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
            if (
                reasons := g.gate_failures(
                    self.gates.guardrail_min_accuracy, self.gates.guardrail_max_latency_seconds
                )
            )
        ]

    @property
    def passed(self) -> bool:
        return not self.persona_failures and not self.guardrail_failures

    def guardrail_passed(self, record: GuardrailRecord) -> bool:
        return not record.gate_failures(
            self.gates.guardrail_min_accuracy, self.gates.guardrail_max_latency_seconds
        )

    def save(self, path: Path) -> None:
        path.write_text(self.model_dump_json(indent=2) + "\n")

    @classmethod
    def load(cls, path: Path) -> "BakeoffResults":
        return cls.model_validate_json(path.read_text())


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
