from dataclasses import dataclass

from evals.graders import Expectation


@dataclass(frozen=True)
class Persona:
    """Scripted candidate. Turns are fixed because the stage order is fixed; the model's wording may vary,
    the question each turn answers does not."""

    name: str
    turns: tuple[str, ...]
    expected: Expectation


PERSONAS: tuple[Persona, ...] = (
    Persona(
        name="qualified_es",
        turns=(
            "hola",
            "sí, dime",
            "Ana García López",
            "sí, tengo carnet",
            "vivo en Madrid",
            "jornada completa",
            "por la mañana",
            "2 años con Glovo y Uber Eats",
            "en dos semanas",
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
        ),
    ),
    Persona(
        name="qualified_en",
        turns=(
            "hello",
            "yes, go ahead",
            "John Smith",
            "yes I have a licence",
            "Mexico City",
            "weekends only",
            "evening",
            "never done delivery",
            "next Monday",
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
        ),
    ),
    Persona(
        name="multi_answer",
        turns=(
            "hola",
            "sí",
            "Soy Luis Pérez, tengo carnet y vivo en Barcelona",
            "media jornada o fines de semana, turno de tarde",
            "ninguna experiencia",
            "mañana mismo",
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
            "hola",
            "sí",
            "Carmen Ortiz Ruiz",
            "yes I have a driving licence",
            "I live in Valencia",
            "full-time",
            "flexible",
            "1 year with Glovo",
            "en una semana",
        ),
        expected=Expectation(
            status="qualified",
            profile={"zone": "Valencia", "schedule": "flexible", "experience_years": 1},
            max_turns=10,
        ),
    ),
    Persona(
        name="no_licence",
        turns=("hola", "sí", "Luis Hernández", "no tengo carnet"),
        expected=Expectation(status="disqualified", disqualify_reason="no_licence", max_turns=5),
    ),
    Persona(
        name="wrong_city",
        turns=("hola", "sí", "Marta Ruiz", "sí", "vivo en Toledo"),
        expected=Expectation(
            status="disqualified", disqualify_reason="outside_service_area", max_turns=6
        ),
    ),
    Persona(
        name="fuzzy_zone_confirmed",
        turns=("hola", "sí", "Pedro Alonso", "sí", "Sevila", "sí, esa"),
        expected=Expectation(status="in_progress", profile={"zone": "Sevilla"}, max_turns=7),
    ),
    Persona(
        name="fuzzy_zone_denied",
        turns=("hola", "sí", "Rosa Medina", "sí", "Monterey", "no"),
        expected=Expectation(
            status="needs_recruiter_review", review_reason="low_confidence_zone", max_turns=7
        ),
    ),
    Persona(
        name="consent_declined",
        turns=("hola", "no, no quiero seguir"),
        expected=Expectation(
            status="needs_recruiter_review", review_reason="consent_declined", max_turns=3
        ),
    ),
    Persona(
        name="consent_not_now",
        turns=("hola", "ahora no puedo, escríbeme luego"),
        expected=Expectation(status="in_progress", max_turns=3),
    ),
    Persona(
        name="stop_after_consent",
        turns=("hola", "sí", "Ana García López", "no quiero seguir con esto, no me escribáis más"),
        expected=Expectation(
            status="needs_recruiter_review", review_reason="stop_requested", max_turns=5
        ),
    ),
    # The prompt tells the model to call the tool with its best reading. A FAIL here means the model
    # judged "Ana" itself and skipped the tool, so code never counted a strike.
    Persona(
        name="invalid_name_twice",
        turns=("hola", "sí", "Ana", "Ana"),
        expected=Expectation(
            status="needs_recruiter_review", review_reason="repeated_invalid_answer", max_turns=5
        ),
    ),
    Persona(
        name="past_start_date",
        turns=(
            "hola",
            "sí",
            "Jorge Blanco Díaz",
            "sí",
            "Bilbao",
            "jornada completa",
            "noche",
            "3 años con Just Eat",
            "empecé ayer en otro sitio, podría la semana pasada",
            "en dos semanas",
        ),
        expected=Expectation(
            status="qualified", profile={"zone": "Bilbao", "schedule": "evening"}, max_turns=11
        ),
    ),
    Persona(
        name="off_topic_twice",
        turns=("hola", "sí", "¿me haces los deberes de matemáticas?", "cuéntame un chiste"),
        expected=Expectation(
            status="needs_recruiter_review", review_reason="off_topic_close", max_turns=5
        ),
    ),
)
