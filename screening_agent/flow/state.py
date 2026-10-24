from typing import Annotated, Any, TypedDict

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
    candidate_id: str
    messages: Annotated[list[AnyMessage], add_messages]
    profile: dict[str, Any]
    consent: bool | None
    pending_zone: str | None
    status: Status
    disqualify_reason: DisqualifyReason | None
    review_reason: ReviewReason | None
    language: Language
    invalid_counts: dict[str, int]
    reply: str


def initial_state(candidate_id: str) -> ScreeningState:
    return ScreeningState(
        candidate_id=candidate_id,
        messages=[],
        profile={},
        consent=None,
        pending_zone=None,
        status=Status.IN_PROGRESS,
        disqualify_reason=None,
        review_reason=None,
        language=Language.ES,
        invalid_counts={},
        reply="",
    )


def is_closed(state: dict[str, Any]) -> bool:
    return state.get("status", Status.IN_PROGRESS) in TERMINAL_STATUSES


def stage_of(state: dict[str, Any]) -> Stage:
    if not state.get("consent"):
        return Stage.CONSENT
    return CandidateProfile.model_validate(state.get("profile", {})).current_stage()
