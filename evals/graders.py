import re
from dataclasses import dataclass

from screening_agent.domain.enums import Language
from screening_agent.domain.language import detect_language
from screening_agent.storage.models import Candidate


@dataclass(frozen=True)
class Expectation:
    status: str
    disqualify_reason: str | None = None
    review_reason: str | None = None
    profile: dict | None = None
    max_turns: int | None = None


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    failures: tuple[str, ...]


def grade(candidate: Candidate, turns: int, expected: Expectation) -> GradeResult:
    """Scores the final JSON and outcome only; wording is scored by style_failures and the judge."""
    failures: list[str] = []
    if candidate.status != expected.status:
        failures.append(f"status {candidate.status} != {expected.status}")
    if expected.disqualify_reason and candidate.disqualify_reason != expected.disqualify_reason:
        failures.append(f"reason {candidate.disqualify_reason} != {expected.disqualify_reason}")
    if expected.review_reason and candidate.review_reason != expected.review_reason:
        failures.append(f"review {candidate.review_reason} != {expected.review_reason}")
    for key, value in (expected.profile or {}).items():
        actual = candidate.profile.get(key)
        if not _same_value(actual, value):
            failures.append(f"profile.{key} {actual!r} != {value!r}")
    if expected.max_turns is not None and turns > expected.max_turns:
        failures.append(f"turns {turns} > {expected.max_turns}")
    return GradeResult(passed=not failures, failures=tuple(failures))


# One emoji may be a cluster: base, skin tone, variation selector, ZWJ-joined bases.
EMOJI = re.compile(
    r"[\U0001F300-\U0001FAFF\u2600-\u27BF](?:[\U0001F3FB-\U0001F3FF\uFE0F]|\u200d[\U0001F300-\U0001FAFF\u2600-\u27BF])*"
)
MAX_REPLY_CHARS = 280


def style_failures(reply: str, language: Language) -> list[str]:
    """Deterministic checks from the tone guidelines: one question, at most one emoji, short,
    in the candidate's language. Language ties pass, the detector is a stopword vote."""
    failures: list[str] = []
    if reply.count("?") > 1:
        failures.append("more than one question")
    if len(EMOJI.findall(reply)) > 1:
        failures.append("more than one emoji")
    if len(reply) > MAX_REPLY_CHARS:
        failures.append(f"reply longer than {MAX_REPLY_CHARS} chars")
    if detect_language(reply, default=language) != language:
        failures.append(f"reply not in {language.value}")
    return failures


def _same_value(actual, expected) -> bool:
    if isinstance(expected, list) and isinstance(actual, list):
        return sorted(actual) == sorted(expected)
    return actual == expected
