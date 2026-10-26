from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from screening_agent.config import settings
from screening_agent.domain.enums import Language


class SilenceAction(StrEnum):
    NONE = "none"
    NUDGE = "nudge"
    ABANDON = "abandon"


@dataclass(frozen=True)
class SilenceSchedule:
    nudge_hours: tuple[float, ...]
    abandon_hours: float

    @classmethod
    def before_first_reply(cls) -> "SilenceSchedule":
        return cls(tuple(settings.opener_retry_hours), settings.opener_abandon_hours)

    @classmethod
    def after_reply(cls) -> "SilenceSchedule":
        return cls(tuple(settings.silence_nudge_hours), settings.silence_abandon_hours)


@dataclass(frozen=True)
class SilenceCandidate:
    candidate_id: str
    channel: str
    language: Language
    opened_at: datetime
    last_inbound_at: datetime | None
    nudge_count: int

    @property
    def awaiting_first_reply(self) -> bool:
        return self.last_inbound_at is None

    @property
    def silent_since(self) -> datetime:
        return self.last_inbound_at or self.opened_at

    @property
    def schedule(self) -> SilenceSchedule:
        if self.awaiting_first_reply:
            return SilenceSchedule.before_first_reply()
        return SilenceSchedule.after_reply()


def nudges_due(now: datetime, candidate: SilenceCandidate) -> int:
    """Thresholds already passed. Stored as the new count so a late sweep sends one nudge, not a burst."""
    elapsed = now - candidate.silent_since
    return sum(elapsed >= timedelta(hours=hours) for hours in candidate.schedule.nudge_hours)


def silence_action(now: datetime, candidate: SilenceCandidate) -> SilenceAction:
    """Abandon wins over nudge once its threshold passes, so a stalled cron never nudges a dead thread."""
    elapsed = now - candidate.silent_since
    if elapsed >= timedelta(hours=candidate.schedule.abandon_hours):
        return SilenceAction.ABANDON
    if nudges_due(now, candidate) > candidate.nudge_count:
        return SilenceAction.NUDGE
    return SilenceAction.NONE
