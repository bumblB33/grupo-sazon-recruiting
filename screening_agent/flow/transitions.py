from dataclasses import dataclass, field
from datetime import date
from typing import Any

from pydantic import ValidationError

from screening_agent.config import settings
from screening_agent.domain.clock import candidate_today
from screening_agent.domain.enums import DisqualifyReason, ReviewReason, Stage, Status
from screening_agent.domain.names import name_similarity
from screening_agent.domain.profile import REQUIRED_FIELD_ORDER, CandidateProfile
from screening_agent.domain.service_areas import match_zone

PATCH_STAGE: dict[str, Stage] = dict(REQUIRED_FIELD_ORDER) | {
    "experience_platforms": Stage.EXPERIENCE
}


@dataclass(frozen=True)
class Transition:
    """Result of one tool call. `error` set means the stage must be re-asked; `candidate_fault`
    False means the model misbehaved (called a tool the stage does not expose), so no strike."""

    updates: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    failed_stage: Stage | None = None
    confirm_area: str | None = None
    # Set when the stated name must be confirmed against the applicant name; the reply is a template.
    confirm_name: str | None = None
    candidate_fault: bool = True

    @classmethod
    def rejected(cls, stage: Stage, message: str, candidate_fault: bool = True) -> "Transition":
        return cls(error=message, failed_stage=stage, candidate_fault=candidate_fault)


def apply_patch(state: dict[str, Any], patch: dict[str, Any]) -> Transition:
    if "consent" in patch:
        return _apply_consent(patch["consent"])
    if "zone_query" in patch:
        return _apply_zone_query(patch["zone_query"])
    if "zone_confirmed" in patch:
        return _apply_zone_confirmation(state, patch["zone_confirmed"])
    if "name_confirmed" in patch:
        return _apply_name_confirmation(state, patch["name_confirmed"])
    return _apply_profile_fields(state, patch)


def qualify_if_complete(state: dict[str, Any]) -> dict[str, Any]:
    """Single owner of the qualified transition; runs after every accepted patch regardless of tool order."""
    if state.get("status", Status.IN_PROGRESS) != Status.IN_PROGRESS or not state.get("consent"):
        return {}
    if state.get("pending_zone") or state.get("pending_name"):
        return {}
    profile = CandidateProfile.model_validate(state.get("profile", {}))
    if profile.current_stage() == Stage.OUTCOME:
        return {"status": Status.QUALIFIED}
    return {}


def _apply_consent(accepted: bool) -> Transition:
    if accepted:
        return Transition(updates={"consent": True})
    return Transition(
        updates={
            "consent": False,
            "status": Status.NEEDS_RECRUITER_REVIEW,
            "review_reason": ReviewReason.CONSENT_DECLINED,
        }
    )


def _apply_zone_query(city: str) -> Transition:
    match = match_zone(city)
    if match.accepted:
        return Transition(updates={"profile": {"zone": match.area}})
    if match.needs_confirmation:
        return Transition(updates={"pending_zone": match.area}, confirm_area=match.area)
    return Transition(
        updates={
            "status": Status.DISQUALIFIED,
            "disqualify_reason": DisqualifyReason.OUTSIDE_SERVICE_AREA,
        }
    )


def _apply_zone_confirmation(state: dict[str, Any], confirmed: bool) -> Transition:
    pending = state.get("pending_zone")
    if confirmed and pending:
        return Transition(updates={"pending_zone": None, "profile": {"zone": pending}})
    return Transition(
        updates={
            "pending_zone": None,
            "status": Status.NEEDS_RECRUITER_REVIEW,
            "review_reason": ReviewReason.LOW_CONFIDENCE_ZONE,
        }
    )


def _apply_name_confirmation(state: dict[str, Any], confirmed: bool) -> Transition:
    pending = state.get("pending_name")
    if confirmed and pending:
        return Transition(updates={"pending_name": None, "profile": {"full_name": pending}})
    return Transition(
        updates={
            "pending_name": None,
            "status": Status.NEEDS_RECRUITER_REVIEW,
            "review_reason": ReviewReason.NAME_MISMATCH,
        }
    )


def _name_needs_confirmation(state: dict[str, Any], full_name: str) -> bool:
    applicant = state.get("applicant_name")
    if not applicant:
        return False
    return name_similarity(full_name, applicant) < settings.name_match_threshold


def _apply_profile_fields(state: dict[str, Any], patch: dict[str, Any]) -> Transition:
    current_profile = state.get("profile", {})
    if "start_date" in patch:
        start = date.fromisoformat(str(patch["start_date"]))
        if start < candidate_today(current_profile.get("zone")):
            return Transition.rejected(Stage.START_DATE, "Start date must be today or later")
    try:
        profile = CandidateProfile.model_validate({**current_profile, **patch})
    except ValidationError as exc:
        first = exc.errors()[0]
        field_name = str(first["loc"][0]) if first["loc"] else next(iter(patch))
        return Transition.rejected(PATCH_STAGE.get(field_name, Stage.FULL_NAME), first["msg"])
    updates: dict[str, Any] = {"profile": profile.model_dump(mode="json", exclude_none=True)}
    if "full_name" in patch and _name_needs_confirmation(state, str(profile.full_name)):
        # The name stays out of the profile until confirmed, so the stage stays full_name.
        updates["profile"].pop("full_name", None)
        updates["pending_name"] = profile.full_name
        return Transition(updates=updates, confirm_name=str(state.get("applicant_name")))
    if profile.has_licence is False:
        updates["status"] = Status.DISQUALIFIED
        updates["disqualify_reason"] = DisqualifyReason.NO_LICENCE
    return Transition(updates=updates)
