from screening_agent.domain.enums import Language
from screening_agent.flow.reply_policy import style_failures


def test_style_failures_flag_questions_emoji_length_and_language():
    assert style_failures("¿Nombre? ¿Y apellido?", Language.ES) == ["more than one question"]
    assert "more than one emoji" in style_failures("Hola 😀🚀 ¿nombre?", Language.ES)
    assert style_failures("Hola 👍🏽 ¿nombre?", Language.ES) == []
    assert style_failures("Hola 👨‍🍳 ¿nombre?", Language.ES) == []
    assert "reply longer than 280 chars" in style_failures("a" * 281, Language.ES)
    assert style_failures(
        "¿En qué ciudad vives? Así veo si tenemos restaurante cerca.", Language.EN
    ) == ["reply not in en"]
    assert style_failures("¿En qué ciudad vives?", Language.ES) == []


def test_markdown_lists_and_links_are_flagged():
    assert style_failures("**Genial**, ¿en qué ciudad vives?", Language.ES) == ["markdown or list"]
    assert style_failures("Elige uno:\n- mañana\n- tarde", Language.ES) == ["markdown or list"]
    assert style_failures("Opciones:\n1. mañana\n2. tarde", Language.ES) == ["markdown or list"]
    assert style_failures("Mira https://gruposazon.com y dime", Language.ES) == ["link"]
    assert style_failures("Entra en www.gruposazon.com", Language.ES) == ["link"]


def test_plain_messaging_text_passes():
    assert style_failures("¿Cuál es tu nombre completo? Así te registro 🙂", Language.ES) == []
    assert style_failures("Great, which city do you live in?", Language.EN) == []
    assert style_failures("Turno de 9-14h, ¿te va bien?", Language.ES) == []
