import time
import uuid
from dataclasses import dataclass, field

from evals.graders import GradeResult, grade
from evals.personas.text_personas import Persona
from screening_agent.domain.enums import Language
from screening_agent.domain.language import detect_language
from screening_agent.flow.engine import Outcome, ScreeningEngine
from screening_agent.flow.graph import build_graph
from screening_agent.flow.reply_policy import style_failures
from screening_agent.flow.turn_record import ReplySource, TurnRecord
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
    # The model's own text when the candidate got something else; style grades the model, not templates.
    model_text: str | None = None
    policy_fallback: bool = False


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


def build_engine(repository: Repository, models: ModelSet) -> ScreeningEngine:
    return ScreeningEngine(
        repository,
        graph=build_graph(chat_model(models.live), build_prompt, models.live),
        summarizer=make_summarizer(models.summary),
        guardrail=Guardrail.for_model(models.guardrail).check,
    )


def run_persona(engine: ScreeningEngine, repository: Repository, persona: Persona) -> PersonaRun:
    """Drives one scripted candidate like a channel would; a crash is a failed run, not a crashed suite."""
    candidate_id = f"{persona.name}-{uuid.uuid4().hex[:6]}"
    turns: list[Turn] = []
    language = persona.language
    error: str | None = None
    try:
        engine.start_conversation(candidate_id, "eval", language, _NoOutbound())
        for index, text in enumerate(persona.turns):
            started = time.perf_counter()
            result = engine.handle(
                candidate_id, text, channel="eval", external_id=f"{candidate_id}-{index}"
            )
            elapsed = time.perf_counter() - started
            if result.outcome != Outcome.REPLIED:
                break
            language = detect_language(text, default=language)
            turns.append(_turn(text, result.reply, elapsed, language, result.turn))
            if result.terminal:
                engine.summarize_outcome(candidate_id)
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


class _NoOutbound:
    """The opener and nudges go nowhere in an eval; the transcript still records them."""

    def send_text(self, candidate_id: str, text: str) -> None:
        pass

    def send_opener(self, candidate_id: str, text: str, first_name: str | None = None) -> None:
        pass


MODEL_SOURCES = frozenset({ReplySource.MODEL_TEXT, ReplySource.MODEL_COMPOSED})


def _turn(
    text: str, reply: str, elapsed: float, language: Language, record: TurnRecord | None
) -> Turn:
    """Grades what the model wrote: the sent reply when the model wrote it, else the draft a
    template replaced. A template reply with no draft behind it is not graded."""
    model_text = record.model_text if record else None
    if record is None or record.reply_source in MODEL_SOURCES:
        raw = reply
    elif model_text is not None:
        raw = model_text
    else:
        raw = ""
    return Turn(
        text,
        reply,
        elapsed,
        tuple(style_failures(raw, language)) if raw else (),
        model_text,
        record is not None and record.reply_source == ReplySource.POLICY_FALLBACK,
    )


def _usage(repository: Repository, candidate_id: str) -> tuple[int, int]:
    """Provider usage travels on each AI message; the graph stores them, so the transcript is the meter."""
    input_tokens = output_tokens = 0
    for message in repository.load_state(candidate_id).get("messages", []):
        usage = getattr(message, "usage_metadata", None) or {}
        input_tokens += usage.get("input_tokens", 0)
        output_tokens += usage.get("output_tokens", 0)
    return input_tokens, output_tokens
