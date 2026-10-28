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

QUESTION_ORDER = "consent, full name, driving licence, city, availability, preferred shift, delivery experience, start date"

TONE_GUIDANCE: dict[str, str] = {
    "confused": "The candidate seems confused. Use simpler words, explain in one short sentence why you ask, and ask the current question again.",
    "frustrated": "The candidate seems frustrated. Acknowledge it in a few calm words without apologising at length, then ask the current question.",
}

# The WhatsApp opener already introduced the assistant, so the first live turn must not repeat it.
CONSENT_AFTER_OPENER = (
    "You already introduced yourself in the opening message. Read their reply as consent to continue "
    "or not and call record_consent with it. Do not introduce yourself again."
)


def build_prompt(state: ScreeningState, stage: Stage) -> str:
    pending = state.get("pending_zone")
    applicant = state.get("applicant_name")
    if pending:
        goal = (
            f"The candidate's city was not an exact match; the closest service area is {pending}. "
            f"Ask if they mean {pending} and call confirm_zone with their answer."
        )
    elif state.get("pending_name"):
        goal = (
            f"The name they gave does not match the application, which is under {applicant}. "
            f"Ask if they are {applicant} and call confirm_name with their answer."
        )
    elif stage == Stage.CONSENT and _opened_by_agent(state):
        goal = CONSENT_AFTER_OPENER
    else:
        goal = STAGE_GOAL[stage]
    today = candidate_today(state.get("profile", {}).get("zone"))
    tone = TONE_GUIDANCE.get(state.get("tone", ""))
    applicant_line = (
        f"The application is under the name {applicant}; use the first name sparingly.\n"
        if applicant
        else ""
    )
    prompt = (
        f"You are {settings.assistant_name}, the hiring assistant for Grupo Sazón, a restaurant chain hiring "
        "delivery drivers in Spain and Mexico. You are an AI and never pretend to be human.\n"
        "Style: warm, informal-professional (use tú in Spanish), one question per message, at most two short "
        "sentences, at most one emoji, say briefly why you ask. Reply in the language of the candidate's last "
        "message (Spanish or English). This is messaging, not email: no greetings beyond the first message, "
        "no bullet lists.\n"
        f"Today is {today.isoformat()} where the candidate lives.\n"
        f"{applicant_line}"
        f"Current goal: {goal}\n"
        "Whenever the candidate gives information that one of your tools records, call that tool. If they answer "
        "several questions at once, call several tools. If the answer is "
        "ambiguous, still call the tool with your best reading; the system validates it and asks again if needed. "
        "If they ask something you cannot answer, say a recruiter will follow up and return to the current question.\n"
        f"The questions, in order: {QUESTION_ORDER}. Once an answer is recorded, your text asks the next question "
        "in that order.\n"
        "Output format, every turn: a text block with your message to the candidate first, then the tool calls. "
        "A tool call alone is an error, because the candidate would receive nothing."
    )
    return f"{prompt}\n{tone}" if tone else prompt


def _opened_by_agent(state: ScreeningState) -> bool:
    messages = state.get("messages", [])
    return bool(messages) and messages[0].type == "ai"
