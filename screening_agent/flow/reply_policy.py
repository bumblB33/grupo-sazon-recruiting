import re

from screening_agent.domain.enums import Language
from screening_agent.domain.language import detect_language

# One emoji may be a cluster: base, skin tone, variation selector, ZWJ-joined bases.
EMOJI = re.compile(
    r"[\U0001F300-\U0001FAFF☀-➿](?:[\U0001F3FB-\U0001F3FF️]|‍[\U0001F300-\U0001FAFF☀-➿])*"
)
MAX_REPLY_CHARS = 280
# Emphasis, headings, code, or a line that starts a bulleted or numbered list.
MARKDOWN = re.compile(r"\*\*|__|`|^\s*(?:[-*•]\s|\d+[.)]\s|#+\s)", re.MULTILINE)
LINK = re.compile(r"https?://|www\.", re.IGNORECASE)


def style_failures(reply: str, language: Language) -> list[str]:
    """Deterministic rules from the tone guidelines, applied live to model text and offline in evals.
    Language ties pass: the detector is a stopword vote, so only a confident mismatch fails."""
    failures: list[str] = []
    if reply.count("?") > 1:
        failures.append("more than one question")
    if len(EMOJI.findall(reply)) > 1:
        failures.append("more than one emoji")
    if len(reply) > MAX_REPLY_CHARS:
        failures.append(f"reply longer than {MAX_REPLY_CHARS} chars")
    if MARKDOWN.search(reply):
        failures.append("markdown or list")
    if LINK.search(reply):
        failures.append("link")
    if detect_language(reply, default=language) != language:
        failures.append(f"reply not in {language.value}")
    return failures
