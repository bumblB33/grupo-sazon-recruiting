from collections.abc import Mapping
from typing import Any

from screening_agent.config import settings
from screening_agent.domain.enums import DisqualifyReason, Language, ReviewReason, Stage
from screening_agent.flow.state import stage_of

REASK: dict[Stage, dict[Language, str]] = {
    Stage.CONSENT: {
        Language.ES: "Antes de empezar necesito tu permiso. Soy una IA y la conversación queda registrada para el equipo de selección. ¿Quieres que sigamos por aquí?",
        Language.EN: "Before we start I need your okay. I'm an AI and this chat is recorded for the recruiting team. Would you like to continue here?",
    },
    Stage.FULL_NAME: {
        Language.ES: "¿Me dices tu nombre completo, por favor? Por ejemplo: Ana García López.",
        Language.EN: "Could you tell me your full name, please? For example: Ana García López.",
    },
    Stage.HAS_LICENCE: {
        Language.ES: "¿Tienes carnet de conducir vigente? Lo pregunto porque hace falta para repartir.",
        Language.EN: "Do you have a valid driving licence? I ask because the role needs one.",
    },
    Stage.ZONE: {
        Language.ES: "¿En qué ciudad vives? Así veo si tenemos restaurante cerca.",
        Language.EN: "Which city do you live in? I'll check if we have a restaurant nearby.",
    },
    Stage.AVAILABILITY: {
        Language.ES: "¿Cómo te vendría mejor trabajar: jornada completa, media jornada o fines de semana?",
        Language.EN: "What would suit you best: full-time, part-time or weekends?",
    },
    Stage.SCHEDULE: {
        Language.ES: "¿Qué turno te viene mejor: mañana, tarde, noche o te da igual?",
        Language.EN: "Which shift suits you best: morning, afternoon, evening, or are you flexible?",
    },
    Stage.EXPERIENCE: {
        Language.ES: "¿Cuánto tiempo llevas repartiendo y con qué plataformas? Si sería tu primera vez, no pasa nada, dime 0.",
        Language.EN: "How long have you been doing deliveries, and with which platforms? If this would be your first time, that's fine, just say 0.",
    },
    Stage.START_DATE: {
        Language.ES: "¿Cuándo te vendría bien empezar? Por ejemplo, el 3 de noviembre.",
        Language.EN: "When would suit you to start? For example, 3 November.",
    },
}

ZONE_CONFIRM: dict[Language, str] = {
    Language.ES: "¿Te refieres a {area}?",
    Language.EN: "Do you mean {area}?",
}

NAME_CONFIRM: dict[Language, str] = {
    Language.ES: "Para asegurarme de que hablo con la persona correcta: ¿eres {name}?",
    Language.EN: "Just so I know I'm talking to the right person: are you {name}?",
}

CONSENT_LATER: dict[Language, str] = {
    Language.ES: "Sin problema. Escríbeme por aquí cuando te venga bien y seguimos.",
    Language.EN: "No problem. Message me here whenever suits you and we'll pick it up.",
}

DISQUALIFIED: dict[DisqualifyReason, dict[Language, str]] = {
    DisqualifyReason.NO_LICENCE: {
        Language.ES: "Gracias por tu tiempo. Para repartir necesitamos carnet de conducir vigente, así que por ahora no podemos avanzar. Guardamos tu solicitud por si cambia tu situación.",
        Language.EN: "Thanks for your time. Delivery roles need a valid driving licence, so we can't move forward right now. We'll keep your application on file in case that changes.",
    },
    DisqualifyReason.OUTSIDE_SERVICE_AREA: {
        Language.ES: "Gracias por tu tiempo. Ahora mismo no tenemos restaurante en tu zona, así que no podemos avanzar. Guardamos tu solicitud por si abrimos cerca.",
        Language.EN: "Thanks for your time. We don't have a restaurant in your area right now, so we can't move forward. We'll keep your application on file in case we open nearby.",
    },
}

REVIEW: dict[ReviewReason, dict[Language, str]] = {
    ReviewReason.CONSENT_DECLINED: {
        Language.ES: "Entendido, no seguimos por aquí y no te escribo más. Si quieres, un reclutador del equipo puede contactarte.",
        Language.EN: "Understood, we'll stop here and I won't message you again. If you'd like, a recruiter from the team can get in touch.",
    },
    ReviewReason.LOW_CONFIDENCE_ZONE: {
        Language.ES: "No encuentro tu ciudad en nuestra lista. Un reclutador lo revisará y te escribe.",
        Language.EN: "I can't find your city on our list. A recruiter will review it and get back to you.",
    },
    ReviewReason.REPEATED_INVALID_ANSWER: {
        Language.ES: "Vamos a dejarlo aquí para no marearte. Un reclutador te escribirá para terminar.",
        Language.EN: "Let's leave it here so I don't go round in circles. A recruiter will message you to finish up.",
    },
    ReviewReason.OFF_TOPIC_CLOSE: {
        Language.ES: "Lo dejamos por hoy. Si quieres seguir con la solicitud, un reclutador te contactará.",
        Language.EN: "Let's leave it for today. If you want to continue your application, a recruiter will contact you.",
    },
    ReviewReason.STOP_REQUESTED: {
        Language.ES: "Entendido, lo dejamos aquí y no te escribo más por este chat. Si quieres retomar tu solicitud, un reclutador puede ayudarte.",
        Language.EN: "Understood, we'll stop here and I won't message you again in this chat. If you want to pick your application up later, a recruiter can help.",
    },
    ReviewReason.NAME_MISMATCH: {
        Language.ES: "Gracias. Un reclutador revisará los datos de tu solicitud y te escribe.",
        Language.EN: "Thanks. A recruiter will check your application details and get back to you.",
    },
    ReviewReason.RECRUITER_CHECK: {
        Language.ES: "Gracias, eso es todo lo que necesitaba preguntarte. Un reclutador revisará tus respuestas y te escribirá.",
        Language.EN: "Thanks, that's everything I needed to ask. A recruiter will go over your answers and get back to you.",
    },
}

OFF_TOPIC_REDIRECT: dict[Language, str] = {
    Language.ES: "Vamos a centrarnos en tu solicitud, que es rápido. Sigo con la pregunta de antes.",
    Language.EN: "Let's stick to your application, it's quick. Back to the previous question.",
}

# A passed screening is not an offer: the text promises a recruiter contact, nothing about the job.
QUALIFIED: dict[Language, str] = {
    Language.ES: "¡Gracias, {first_name}, eso es todo! Tus respuestas pasan ahora a un reclutador, que te escribirá para contarte los siguientes pasos.",
    Language.EN: "Thanks, {first_name}, that's everything! Your answers now go to a recruiter, who will message you about the next steps.",
}

# Appended to the outcome message; opt-outs (declined consent, stop request) never get it.
QUESTIONS_PROMPT: dict[Language, str] = {
    Language.ES: "Antes de despedirme: ¿tienes alguna pregunta sobre el puesto que quieras que le pase al reclutador?",
    Language.EN: "Before I go: do you have any questions about the job you'd like me to pass on to the recruiter?",
}

CLOSING_WITH_QUESTIONS: dict[Language, str] = {
    Language.ES: "Anotado, el reclutador verá tus preguntas. ¡Gracias por tu tiempo!",
    Language.EN: "Noted, the recruiter will see your questions. Thanks for your time!",
}

CLOSING_WITHOUT_QUESTIONS: dict[Language, str] = {
    Language.ES: "Perfecto. ¡Gracias por tu tiempo!",
    Language.EN: "Great. Thanks for your time!",
}

OPENER: dict[Language, str] = {
    Language.ES: "{greeting} Soy {assistant}, el asistente de IA de Grupo Sazón, no una persona. Recibimos tu solicitud para repartidor y me gustaría hacerte unas preguntas cortas por aquí. La conversación queda registrada y solo la ve el equipo de selección, y puedes parar cuando quieras diciéndomelo. ¿Te parece bien que sigamos?",
    Language.EN: "{greeting} I'm {assistant}, Grupo Sazón's AI assistant, not a person. We received your delivery-driver application and I'd like to ask you a few short questions here. This chat is recorded and only the recruiting team sees it, and you can stop whenever you want by telling me. Are you happy to go ahead?",
}

GREETING: dict[Language, tuple[str, str]] = {
    Language.ES: ("¡Hola!", "¡Hola, {first_name}!"),
    Language.EN: ("Hi!", "Hi, {first_name}!"),
}

NUDGE: dict[Language, str] = {
    Language.ES: "¿Sigues ahí? Cuando puedas: {question}",
    Language.EN: "Still there? When you can: {question}",
}


UNKNOWN_NUMBER = (
    "Hola, soy {assistant}, el asistente de IA de Grupo Sazón. No encuentro ninguna solicitud con "
    "este número, así que no puedo continuar por aquí. / Hi, I'm {assistant}, Grupo Sazón's AI "
    "assistant. I can't find an application for this number, so I can't continue here."
)


def opener(language: Language, first_name: str | None = None) -> str:
    plain, named = GREETING[language]
    greeting = named.format(first_name=first_name) if first_name else plain
    return OPENER[language].format(greeting=greeting, assistant=settings.assistant_name)


def next_question(state: Mapping[str, Any], language: Language) -> str:
    """The question the candidate still owes: a pending confirmation first, else the stage's re-ask."""
    if state.get("pending_zone"):
        return ZONE_CONFIRM[language].format(area=state["pending_zone"])
    if state.get("pending_name"):
        return NAME_CONFIRM[language].format(name=state.get("applicant_name"))
    return REASK[stage_of(state)][language]


def unknown_number() -> str:
    """One bilingual message: the sender's language is unknown before any application exists."""
    return UNKNOWN_NUMBER.format(assistant=settings.assistant_name)
