from collections.abc import Mapping
from typing import Annotated, Any, Required, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from screening_agent.domain.enums import (
    TERMINAL_STATUSES,
    DisqualifyReason,
    Language,
    ReviewReason,
    Stage,
    Status,
)
from screening_agent.domain.profile import CandidateProfile


class ScreeningState(TypedDict, total=False):
    candidate_id: Required[str]
    messages: Required[Annotated[list[AnyMessage], add_messages]]
    profile: dict[str, Any]
    consent: bool | None
    pending_zone: str | None
    # The name on the application, when the client sent one. Never set by the candidate.
    applicant_name: str | None
    # A validated name the candidate gave that does not match the application, awaiting confirm_name.
    pending_name: str | None
    # What the model flagged for a recruiter to check; a complete profile with any entry goes to review.
    concerns: list[str]
    status: Required[Status]
    disqualify_reason: DisqualifyReason | None
    review_reason: ReviewReason | None
    # False between the outcome message, which asks for questions for the recruiter, and the reply.
    closed: bool
    candidate_questions: list[str]
    language: Language
    invalid_counts: dict[str, int]
    reply: str
    # Mirrors Conversation.version at load time; the repository refuses a write from an older version.
    version: int
    # This turn's decision record; the engine moves it onto the transcript entry, never into saved state.
    turn: dict[str, Any]
    # The guardrail's reading of this message; the prompt softens for it, and it is never saved.
    tone: str


def initial_state(candidate_id: str) -> ScreeningState:
    return ScreeningState(
        candidate_id=candidate_id,
        messages=[],
        profile={},
        consent=None,
        pending_zone=None,
        applicant_name=None,
        pending_name=None,
        concerns=[],
        status=Status.IN_PROGRESS,
        disqualify_reason=None,
        review_reason=None,
        language=Language.ES,
        invalid_counts={},
        reply="",
        version=0,
    )


def is_decided(state: Mapping[str, Any]) -> bool:
    return state.get("status", Status.IN_PROGRESS) in TERMINAL_STATUSES


def is_closed(state: Mapping[str, Any]) -> bool:
    """A decided conversation stays open for one reply with questions for the recruiter. Documents
    written before the wrap-up turn existed have no flag and count as closed."""
    return is_decided(state) and state.get("closed", True)


def awaiting_questions(state: Mapping[str, Any]) -> bool:
    return is_decided(state) and not state.get("closed", True)


def stage_of(state: Mapping[str, Any]) -> Stage:
    if not state.get("consent"):
        return Stage.CONSENT
    return CandidateProfile.model_validate(state.get("profile", {})).current_stage()
