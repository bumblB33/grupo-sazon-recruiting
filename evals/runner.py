import time
import uuid
from dataclasses import dataclass, field

from evals.graders import GradeResult, grade, style_failures
from evals.personas.text_personas import Persona
from screening_agent.domain.enums import Language
from screening_agent.domain.language import detect_language
from screening_agent.flow.engine import Outcome, ScreeningEngine
from screening_agent.flow.graph import build_graph
from screening_agent.llm.guardrail import Guardrail
from screening_agent.llm.models import chat_model
from screening_agent.llm.summary import make_summarizer
from screening_agent.llm.turn import build_prompt
from screening_agent.storage.models import Candidate
from screening_agent.storage.repository import Repository


@dataclass(frozen=True)
class ModelSet:
    live: str
    summary: str
    guardrail: str


@dataclass(frozen=True)
class Turn:
    candidate: str
    reply: str
    latency_seconds: float
    style: tuple[str, ...] = ()


@dataclass(frozen=True)
class PersonaRun:
    persona: Persona
    turns: tuple[Turn, ...]
    candidate: Candidate | None
    grade: GradeResult
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None
    judge: dict = field(default_factory=dict)

    @property
    def style_failure_count(self) -> int:
        return sum(len(turn.style) for turn in self.turns)


def build_engine(repository: Repository, models: ModelSet) -> ScreeningEngine:
    return ScreeningEngine(
        repository,
        graph=build_graph(chat_model(models.live), build_prompt),
        summarizer=make_summarizer(models.summary),
        guardrail=Guardrail.for_model(models.guardrail).check,
    )


def run_persona(engine: ScreeningEngine, repository: Repository, persona: Persona) -> PersonaRun:
    """Drives one scripted candidate like a channel would; a crash is a failed run, not a crashed suite."""
    candidate_id = f"{persona.name}-{uuid.uuid4().hex[:6]}"
    turns: list[Turn] = []
    language = Language.ES
    error: str | None = None
    try:
        for index, text in enumerate(persona.turns):
            started = time.perf_counter()
            result = engine.handle(
                candidate_id, text, channel="eval", external_id=f"{candidate_id}-{index}"
            )
            elapsed = time.perf_counter() - started
            if result.outcome != Outcome.REPLIED:
                break
            language = detect_language(text, default=language)
            turns.append(
                Turn(text, result.reply, elapsed, tuple(style_failures(result.reply, language)))
            )
            if result.terminal:
                engine.summarize_outcome(candidate_id)
                break
    except Exception as exc:  # the suite reports the failure and moves to the next persona
        error = f"{type(exc).__name__}: {exc}"
    candidate = repository.get_candidate(candidate_id)
    if candidate is None:
        grade_result = GradeResult(False, (error or "no candidate saved",))
    else:
        grade_result = grade(candidate, len(turns), persona.expected)
        if error:
            grade_result = GradeResult(False, (*grade_result.failures, error))
    input_tokens, output_tokens = _usage(repository, candidate_id)
    return PersonaRun(
        persona, tuple(turns), candidate, grade_result, input_tokens, output_tokens, error
    )


def _usage(repository: Repository, candidate_id: str) -> tuple[int, int]:
    """Provider usage travels on each AI message; the graph stores them, so the transcript is the meter."""
    input_tokens = output_tokens = 0
    for message in repository.load_state(candidate_id).get("messages", []):
        usage = getattr(message, "usage_metadata", None) or {}
        input_tokens += usage.get("input_tokens", 0)
        output_tokens += usage.get("output_tokens", 0)
    return input_tokens, output_tokens
