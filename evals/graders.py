from dataclasses import dataclass

from screening_agent.storage.models import Candidate


@dataclass(frozen=True)
class Expectation:
    status: str
    disqualify_reason: str | None = None
    profile: dict | None = None
    max_turns: int | None = None


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    failures: tuple[str, ...]


def grade(candidate: Candidate, turns: int, expected: Expectation) -> GradeResult:
    """Graders score the final JSON and outcome only; transcript wording is judged separately."""
    failures: list[str] = []
    if candidate.status != expected.status:
        failures.append(f"status {candidate.status} != {expected.status}")
    if expected.disqualify_reason and candidate.disqualify_reason != expected.disqualify_reason:
        failures.append(f"reason {candidate.disqualify_reason} != {expected.disqualify_reason}")
    for key, value in (expected.profile or {}).items():
        if candidate.profile.get(key) != value:
            failures.append(f"profile.{key} {candidate.profile.get(key)!r} != {value!r}")
    if expected.max_turns is not None and turns > expected.max_turns:
        failures.append(f"turns {turns} > {expected.max_turns}")
    return GradeResult(passed=not failures, failures=tuple(failures))
