from enum import StrEnum


class Availability(StrEnum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    WEEKENDS = "weekends"


class Schedule(StrEnum):
    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"
    FLEXIBLE = "flexible"


class Language(StrEnum):
    ES = "es"
    EN = "en"


class MessageKind(StrEnum):
    REPLY = "reply"
    OPENER = "opener"
    NUDGE = "nudge"


class ConsentDecision(StrEnum):
    """Only an explicit agreement opens the screening; a bare no is unclear until the candidate says which."""

    AGREED = "agreed"
    DECLINED = "declined"
    NOT_NOW = "not_now"
    UNCLEAR = "unclear"


class Status(StrEnum):
    IN_PROGRESS = "in_progress"
    QUALIFIED = "qualified"
    DISQUALIFIED = "disqualified"
    NEEDS_RECRUITER_REVIEW = "needs_recruiter_review"
    ABANDONED = "abandoned"


TERMINAL_STATUSES = frozenset(Status) - {Status.IN_PROGRESS}


class DisqualifyReason(StrEnum):
    NO_LICENCE = "no_licence"
    OUTSIDE_SERVICE_AREA = "outside_service_area"


class ReviewReason(StrEnum):
    CONSENT_DECLINED = "consent_declined"
    LOW_CONFIDENCE_ZONE = "low_confidence_zone"
    REPEATED_INVALID_ANSWER = "repeated_invalid_answer"
    OFF_TOPIC_CLOSE = "off_topic_close"
    NAME_MISMATCH = "name_mismatch"
    STOP_REQUESTED = "stop_requested"


class Stage(StrEnum):
    CONSENT = "consent"
    FULL_NAME = "full_name"
    HAS_LICENCE = "has_licence"
    ZONE = "zone"
    AVAILABILITY = "availability"
    SCHEDULE = "schedule"
    EXPERIENCE = "experience"
    START_DATE = "start_date"
    OUTCOME = "outcome"
