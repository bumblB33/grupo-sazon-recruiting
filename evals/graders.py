from dataclasses import dataclass

from screening_agent.storage.models import Candidate


@dataclass(frozen=True)
class Expectation:
    status: str
    disqualify_reason: str | None = None
    review_reason: str | None = None
    profile: dict | None = None
    max_turns: int | None = None
    # True: at least one entry expected. False: none. None: not graded.
    concerns: bool | None = None
    questions: bool | None = None


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    failures: tuple[str, ...]


def grade(candidate: Candidate, turns: int, expected: Expectation) -> GradeResult:
    """Scores the final JSON and outcome only; wording is scored by reply_policy and the judge."""
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
    recorded = {"concerns": candidate.concerns, "questions": candidate.candidate_questions}
    for name, wanted in (("concerns", expected.concerns), ("questions", expected.questions)):
        if wanted is not None and bool(recorded[name]) != wanted:
            failures.append(f"{name} {'missing' if wanted else 'recorded'}: {recorded[name]!r}")
    return GradeResult(passed=not failures, failures=tuple(failures))


def _same_value(actual, expected) -> bool:
    if isinstance(expected, list) and isinstance(actual, list):
        return sorted(actual) == sorted(expected)
    return actual == expected
