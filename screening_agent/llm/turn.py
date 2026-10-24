from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from screening_agent.config import settings
from screening_agent.domain.clock import candidate_today
from screening_agent.domain.enums import Stage
from screening_agent.flow.state import ScreeningState

STAGE_GOAL: dict[Stage, str] = {
    Stage.CONSENT: "Introduce yourself, say you are an AI assistant and that the conversation is recorded, and ask if it is a good moment to continue. Call record_consent with their answer.",
    Stage.FULL_NAME: "Ask for their full name.",
    Stage.HAS_LICENCE: "Ask whether they hold a valid driving licence.",
    Stage.ZONE: "Ask which city they live in so you can check for a nearby restaurant.",
    Stage.AVAILABILITY: "Ask their availability: full_time, part_time, weekends (several allowed).",
    Stage.SCHEDULE: "Ask their preferred shift: morning, afternoon, evening or flexible.",
    Stage.EXPERIENCE: "Ask years of delivery experience and platforms. Zero is a fine answer.",
    Stage.START_DATE: "Ask when they could start and resolve relative dates to an ISO date.",
    Stage.OUTCOME: "Thank them. The outcome message is sent by the system.",
}


def build_prompt(state: ScreeningState, stage: Stage) -> str:
    pending = state.get("pending_zone")
    goal = (
        f"The candidate's city was not an exact match; the closest service area is {pending}. "
        f"Ask if they mean {pending} and call confirm_zone with their answer."
        if pending
        else STAGE_GOAL[stage]
    )
    today = candidate_today(state.get("profile", {}).get("zone"))
    return (
        f"You are {settings.assistant_name}, the hiring assistant for Grupo Sazón, a restaurant chain hiring "
        "delivery drivers in Spain and Mexico. You are an AI and never pretend to be human.\n"
        "Style: warm, informal-professional (use tú in Spanish), one question per message, at most two short "
        "sentences, at most one emoji, say briefly why you ask. Reply in the language of the candidate's last "
        "message (Spanish or English). This is messaging, not email: no greetings beyond the first message, "
        "no bullet lists.\n"
        f"Today is {today.isoformat()} where the candidate lives.\n"
        f"Current goal: {goal}\n"
        "Whenever the candidate gives information that one of your tools records, call that tool in the same "
        "message as your reply. If they answer several questions at once, call several tools. If the answer is "
        "ambiguous, still call the tool with your best reading; the system validates it and asks again if needed. "
        "If they ask something you cannot answer, say a recruiter will follow up and return to the current question."
    )


def live_model() -> BaseChatModel:
    return init_chat_model(
        settings.live_model,
        temperature=0,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )
