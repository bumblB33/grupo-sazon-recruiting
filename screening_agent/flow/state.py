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
    status: Required[Status]
    disqualify_reason: DisqualifyReason | None
    review_reason: ReviewReason | None
    language: Language
    invalid_counts: dict[str, int]
    reply: str
    # Mirrors Conversation.version at load time; the repository refuses a write from an older version.
    version: int


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
        version=0,
    )


def is_closed(state: Mapping[str, Any]) -> bool:
    return state.get("status", Status.IN_PROGRESS) in TERMINAL_STATUSES


def stage_of(state: Mapping[str, Any]) -> Stage:
    if not state.get("consent"):
        return Stage.CONSENT
    return CandidateProfile.model_validate(state.get("profile", {})).current_stage()
