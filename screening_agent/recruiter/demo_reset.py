from screening_agent.config import settings
from screening_agent.flow.engine import ScreeningEngine


class NotResettableError(PermissionError):
    """The candidate id is not in the demo allowlist."""


def resettable(candidate_id: str, archived: bool) -> bool:
    return candidate_id in settings.demo_phones and not archived


def reset_demo_candidate(engine: ScreeningEngine, candidate_id: str, actor: str) -> str | None:
    """Archives an allowlisted candidate so its phone can run the screening again."""
    if not resettable(candidate_id, archived=False):
        raise NotResettableError("candidate id is not a demo phone")
    return engine.archive_candidate(candidate_id, actor)
