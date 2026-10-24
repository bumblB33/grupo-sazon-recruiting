import re

from screening_agent.domain.enums import Language

SPANISH_MARKERS = frozenset(
    "sí si no hola gracias tengo soy puedo quiero que de la el y en para por con una un es está estoy "
    "mañana tarde noche semana carnet licencia vivo trabajo años".split()
)
ENGLISH_MARKERS = frozenset(
    "yes no hello thanks i have am can want that of the and in for with a is morning afternoon "
    "evening week licence license live work years".split()
)


def detect_language(text: str, default: Language = Language.ES) -> Language:
    """Stopword vote; ties and empty input fall back to default so the agent never guesses a third language."""
    tokens = re.findall(r"[a-záéíóúñü]+", text.lower())
    spanish = sum(token in SPANISH_MARKERS for token in tokens)
    english = sum(token in ENGLISH_MARKERS for token in tokens)
    if spanish == english:
        return default
    return Language.ES if spanish > english else Language.EN
