from screening_agent.domain.enums import Language
from screening_agent.domain.language import detect_language


def test_spanish_and_english_are_detected():
    assert detect_language("sí, tengo carnet y vivo en Madrid") == Language.ES
    assert detect_language("yes, I have a licence and live in Madrid") == Language.EN


def test_tie_and_empty_fall_back_to_default():
    assert detect_language("no", default=Language.EN) == Language.EN
    assert detect_language("", default=Language.ES) == Language.ES
