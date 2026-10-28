from datetime import date

from langchain_core.tools import BaseTool, tool

from screening_agent.domain.enums import Availability, ConsentDecision, Schedule, Stage
from screening_agent.domain.profile import REQUIRED_FIELD_ORDER


@tool
def record_consent(decision: ConsentDecision) -> dict:
    """Record the candidate's answer to the consent question. agreed: they clearly agree to continue
    the recorded chat with an AI. declined: they do not want it. not_now: fine with it but a bad
    moment. unclear: anything else, including a bare no."""
    return {"consent_decision": decision}


@tool
def request_stop() -> dict:
    """Record that the candidate asks to stop the screening or not to be contacted any more."""
    return {"stop": True}


FLAG_FOR_RECRUITER = (
    "Flag something a recruiter must check before an interview, in one short sentence: a criminal "
    "record or pending charges, a licence that is suspended, expired, pending or that the candidate "
    "is not sure about, a work-permit or documents question, or an answer they hedge or cannot "
    "confirm. Call it in addition to the tool that records the answer. The candidate is never told."
)
RECORD_QUESTIONS = (
    "Record the questions about the job the candidate wants passed on to the recruiter, one short "
    "sentence each. An empty list means they have none."
)


@tool(description=FLAG_FOR_RECRUITER)
def flag_for_recruiter(concern: str) -> dict:
    return {"concern": concern}


@tool(description=RECORD_QUESTIONS)
def record_questions(questions: list[str]) -> dict:
    return {"questions": questions}


@tool
def record_full_name(full_name: str) -> dict:
    """Record the candidate's full name exactly as they gave it."""
    return {"full_name": full_name}


@tool
def confirm_name(confirmed: bool) -> dict:
    """Record the candidate's yes/no answer to whether they are the person on the application."""
    return {"name_confirmed": confirmed}


@tool
def record_licence(has_licence: bool) -> dict:
    """Record whether the candidate holds a valid driving licence."""
    return {"has_licence": has_licence}


@tool
def record_zone(city: str) -> dict:
    """Record the city or zone where the candidate lives and could work."""
    return {"zone_query": city}


@tool
def confirm_zone(confirmed: bool) -> dict:
    """Record the candidate's yes/no answer to the suggested city match."""
    return {"zone_confirmed": confirmed}


@tool
def record_availability(availability: list[Availability]) -> dict:
    """Record one or more availability options: full_time, part_time, weekends."""
    return {"availability": availability}


@tool
def record_schedule(schedule: Schedule) -> dict:
    """Record the preferred shift: morning, afternoon, evening or flexible."""
    return {"schedule": schedule}


@tool
def record_experience(years: int, platforms: list[str]) -> dict:
    """Record years of delivery experience (0 is valid) and platforms used, empty list if none."""
    return {"experience_years": years, "experience_platforms": platforms}


@tool
def record_start_date(start_date: date) -> dict:
    """Record the earliest start date as an ISO date, resolving relative phrases against today."""
    return {"start_date": start_date.isoformat()}


TOOLS_BY_STAGE: dict[Stage, list[BaseTool]] = {
    Stage.CONSENT: [record_consent],
    Stage.FULL_NAME: [record_full_name],
    Stage.HAS_LICENCE: [record_licence],
    Stage.ZONE: [record_zone],
    Stage.AVAILABILITY: [record_availability],
    Stage.SCHEDULE: [record_schedule],
    Stage.EXPERIENCE: [record_experience],
    Stage.START_DATE: [record_start_date],
}

ALL_TOOLS: dict[str, BaseTool] = {
    stage_tool.name: stage_tool
    for stage_tools in TOOLS_BY_STAGE.values()
    for stage_tool in stage_tools
} | {
    confirm_zone.name: confirm_zone,
    confirm_name.name: confirm_name,
    flag_for_recruiter.name: flag_for_recruiter,
    record_questions.name: record_questions,
    request_stop.name: request_stop,
}

TOOL_STAGE: dict[str, Stage] = {
    stage_tool.name: stage
    for stage, stage_tools in TOOLS_BY_STAGE.items()
    for stage_tool in stage_tools
} | {confirm_zone.name: Stage.ZONE, confirm_name.name: Stage.FULL_NAME}


def tools_for(
    stage: Stage, missing_fields: list[str], pending_zone: bool, pending_name: bool = False
) -> list[BaseTool]:
    """Exposes every tool for a still-missing field from the current stage on, so one message can fill
    several. After consent the candidate can always withdraw and the model can always flag a
    concern, so flag_for_recruiter and request_stop are always there."""
    if stage == Stage.CONSENT:
        return [record_consent]
    if stage == Stage.OUTCOME:
        return [flag_for_recruiter, request_stop]
    exposed: list[BaseTool] = []
    if pending_name:
        exposed.append(confirm_name)
    if pending_zone:
        exposed.append(confirm_zone)
    awaiting_confirmation = {Stage.ZONE: pending_zone, Stage.FULL_NAME: pending_name}
    reached = False
    for field_name, field_stage in REQUIRED_FIELD_ORDER:
        reached = reached or field_stage == stage
        if (
            reached
            and field_name in missing_fields
            and not awaiting_confirmation.get(field_stage, False)
        ):
            exposed.extend(TOOLS_BY_STAGE[field_stage])
    return [*exposed, flag_for_recruiter, request_stop]
