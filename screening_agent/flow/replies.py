from screening_agent.config import settings
from screening_agent.domain.enums import DisqualifyReason, Language, ReviewReason, Stage

REASK: dict[Stage, dict[Language, str]] = {
    Stage.CONSENT: {
        Language.ES: "Soy un asistente de IA de Grupo Sazón y esta conversación queda registrada. ¿Te parece bien que sigamos? Sí o no.",
        Language.EN: "I'm an AI assistant for Grupo Sazón and this conversation is recorded. Is it okay if we continue? Yes or no.",
    },
    Stage.FULL_NAME: {
        Language.ES: "No me quedó claro tu nombre. ¿Me lo dices completo? Por ejemplo: Ana García López.",
        Language.EN: "I didn't catch your name. Could you give me your full name? For example: Ana García López.",
    },
    Stage.HAS_LICENCE: {
        Language.ES: "Solo para confirmar: ¿tienes carnet de conducir vigente? Sí o no.",
        Language.EN: "Just to confirm: do you have a valid driving licence? Yes or no.",
    },
    Stage.ZONE: {
        Language.ES: "¿En qué ciudad vives? Así veo si tenemos restaurante cerca.",
        Language.EN: "Which city do you live in? I'll check if we have a restaurant nearby.",
    },
    Stage.AVAILABILITY: {
        Language.ES: "¿Qué disponibilidad tienes: jornada completa, media jornada o fines de semana?",
        Language.EN: "What availability do you have: full-time, part-time, or weekends?",
    },
    Stage.SCHEDULE: {
        Language.ES: "¿Qué turno prefieres: mañana, tarde, noche o flexible?",
        Language.EN: "Which shift do you prefer: morning, afternoon, evening, or flexible?",
    },
    Stage.EXPERIENCE: {
        Language.ES: "¿Cuántos años llevas en reparto y con qué plataformas? Si es tu primera vez, dime 0.",
        Language.EN: "How many years of delivery experience do you have, and on which platforms? Say 0 if none.",
    },
    Stage.START_DATE: {
        Language.ES: "¿Cuándo podrías empezar? Dame una fecha, por ejemplo el 3 de noviembre.",
        Language.EN: "When could you start? Give me a date, for example 3 November.",
    },
}

ZONE_CONFIRM: dict[Language, str] = {
    Language.ES: "¿Te refieres a {area}? Sí o no.",
    Language.EN: "Do you mean {area}? Yes or no.",
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
        Language.ES: "Entendido, no seguimos por aquí. Un reclutador del equipo se pondrá en contacto contigo.",
        Language.EN: "Understood, we'll stop here. A recruiter from the team will get in touch with you.",
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
}

OFF_TOPIC_REDIRECT: dict[Language, str] = {
    Language.ES: "Vamos a centrarnos en tu solicitud, que es rápido. Sigo con la pregunta de antes.",
    Language.EN: "Let's stick to your application, it's quick. Back to the previous question.",
}

QUALIFIED: dict[Language, str] = {
    Language.ES: "¡Listo, {first_name}! Cumples lo que buscamos. Un reclutador te escribirá para agendar una entrevista corta.",
    Language.EN: "All set, {first_name}! You meet what we're looking for. A recruiter will message you to book a short interview.",
}

OPENER: dict[Language, str] = {
    Language.ES: "¡Hola! Soy {assistant}, el asistente de IA de Grupo Sazón. Recibimos tu solicitud para repartidor y esta conversación queda registrada. ¿Es buen momento para unas preguntas rápidas?",
    Language.EN: "Hi! I'm {assistant}, the AI assistant for Grupo Sazón. We received your delivery-driver application and this conversation is recorded. Is now a good moment for a few quick questions?",
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


def opener(language: Language) -> str:
    return OPENER[language].format(assistant=settings.assistant_name)


def unknown_number() -> str:
    """One bilingual message: the sender's language is unknown before any application exists."""
    return UNKNOWN_NUMBER.format(assistant=settings.assistant_name)
