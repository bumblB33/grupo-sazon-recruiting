from dataclasses import dataclass

from evals.graders import Expectation
from screening_agent.domain.enums import Language


@dataclass(frozen=True)
class Persona:
    """Scripted candidate. The fixed opener goes first, so the first turn answers the consent question;
    a last turn answers the closing question about questions for the recruiter."""

    name: str
    turns: tuple[str, ...]
    expected: Expectation
    language: Language = Language.ES


PERSONAS: tuple[Persona, ...] = (
    Persona(
        name="qualified_es",
        turns=(
            "sí, dime",
            "Ana García López",
            "sí, tengo carnet",
            "vivo en Madrid",
            "jornada completa",
            "por la mañana",
            "2 años con Glovo y Uber Eats",
            "en dos semanas",
            "sí, ¿cuánto se cobra la hora?",
        ),
        expected=Expectation(
            status="qualified",
            profile={
                "full_name": "Ana García López",
                "has_licence": True,
                "zone": "Madrid",
                "availability": ["full_time"],
                "schedule": "morning",
                "experience_years": 2,
            },
            max_turns=10,
            questions=True,
        ),
    ),
    Persona(
        name="qualified_en",
        language=Language.EN,
        turns=(
            "yes, go ahead",
            "John Smith",
            "yes I have a licence",
            "Mexico City",
            "weekends only",
            "evening",
            "never done delivery",
            "next Monday",
            "no questions, thanks",
        ),
        expected=Expectation(
            status="qualified",
            profile={
                "zone": "Ciudad de México",
                "availability": ["weekends"],
                "schedule": "evening",
                "experience_years": 0,
            },
            max_turns=10,
            questions=False,
        ),
    ),
    Persona(
        name="multi_answer",
        turns=(
            "sí",
            "Soy Luis Pérez, tengo carnet y vivo en Barcelona",
            "media jornada o fines de semana, turno de tarde",
            "ninguna experiencia",
            "mañana mismo",
            "no, nada",
        ),
        expected=Expectation(
            status="qualified",
            profile={
                "zone": "Barcelona",
                "availability": ["part_time", "weekends"],
                "schedule": "afternoon",
                "experience_years": 0,
            },
            max_turns=6,
        ),
    ),
    Persona(
        name="language_switch",
        turns=(
            "sí",
            "Carmen Ortiz Ruiz",
            "yes I have a driving licence",
            "I live in Valencia",
            "full-time",
            "flexible",
            "1 year with Glovo",
            "en una semana",
            "no, gracias",
        ),
        expected=Expectation(
            status="qualified",
            profile={"zone": "Valencia", "schedule": "flexible", "experience_years": 1},
            max_turns=10,
        ),
    ),
    # Every answer is valid, but a recruiter must check the record before an interview.
    Persona(
        name="criminal_record_flagged",
        turns=(
            "sí",
            "Carlos Ruiz Mora",
            "sí, aunque tengo antecedentes penales de hace unos años, no sé si importa",
            "Madrid",
            "jornada completa",
            "mañana",
            "0",
            "la semana que viene",
            "¿los antecedentes son un problema?",
        ),
        expected=Expectation(
            status="needs_recruiter_review",
            review_reason="recruiter_check",
            profile={"has_licence": True, "zone": "Madrid"},
            max_turns=10,
            concerns=True,
            questions=True,
        ),
    ),
    Persona(
        name="licence_unconfirmed_flagged",
        turns=(
            "sí",
            "Lucía Fernández Gil",
            "creo que sí, tengo que mirar si está caducado",
            "Valencia",
            "fines de semana",
            "tarde",
            "1 año con Glovo",
            "en dos semanas",
            "no",
        ),
        expected=Expectation(
            status="needs_recruiter_review",
            review_reason="recruiter_check",
            max_turns=10,
            concerns=True,
        ),
    ),
    Persona(
        name="no_licence",
        turns=("sí", "Luis Hernández", "no tengo carnet", "no, ninguna"),
        expected=Expectation(status="disqualified", disqualify_reason="no_licence", max_turns=5),
    ),
    Persona(
        name="wrong_city",
        turns=("sí", "Marta Ruiz", "sí", "vivo en Toledo", "¿abriréis en Toledo?"),
        expected=Expectation(
            status="disqualified",
            disqualify_reason="outside_service_area",
            max_turns=6,
            questions=True,
        ),
    ),
    Persona(
        name="fuzzy_zone_confirmed",
        turns=("sí", "Pedro Alonso", "sí", "Sevila", "sí, esa"),
        expected=Expectation(status="in_progress", profile={"zone": "Sevilla"}, max_turns=7),
    ),
    Persona(
        name="fuzzy_zone_denied",
        turns=("sí", "Rosa Medina", "sí", "Monterey", "no", "no"),
        expected=Expectation(
            status="needs_recruiter_review", review_reason="low_confidence_zone", max_turns=7
        ),
    ),
    Persona(
        name="consent_declined",
        turns=("no, no quiero seguir",),
        expected=Expectation(
            status="needs_recruiter_review", review_reason="consent_declined", max_turns=3
        ),
    ),
    Persona(
        name="consent_not_now",
        turns=("ahora no puedo, escríbeme luego",),
        expected=Expectation(status="in_progress", max_turns=3),
    ),
    Persona(
        name="stop_after_consent",
        turns=("sí", "Ana García López", "no quiero seguir con esto, no me escribáis más"),
        expected=Expectation(
            status="needs_recruiter_review", review_reason="stop_requested", max_turns=5
        ),
    ),
    # The prompt tells the model to call the tool with its best reading. A FAIL here means the model
    # judged "Ana" itself and skipped the tool, so code never counted a strike.
    Persona(
        name="invalid_name_twice",
        turns=("sí", "Ana", "Ana", "no"),
        expected=Expectation(
            status="needs_recruiter_review", review_reason="repeated_invalid_answer", max_turns=5
        ),
    ),
    Persona(
        name="past_start_date",
        turns=(
            "sí",
            "Jorge Blanco Díaz",
            "sí",
            "Bilbao",
            "jornada completa",
            "noche",
            "3 años con Just Eat",
            "empecé ayer en otro sitio, podría la semana pasada",
            "en dos semanas",
            "no",
        ),
        expected=Expectation(
            status="qualified", profile={"zone": "Bilbao", "schedule": "evening"}, max_turns=11
        ),
    ),
    Persona(
        name="off_topic_twice",
        turns=("sí", "¿me haces los deberes de matemáticas?", "cuéntame un chiste"),
        expected=Expectation(
            status="needs_recruiter_review", review_reason="off_topic_close", max_turns=5
        ),
    ),
)
