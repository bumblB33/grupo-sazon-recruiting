from datetime import date

from pydantic import BaseModel, Field, field_validator

from screening_agent.domain.enums import Availability, Schedule, Stage

REQUIRED_FIELD_ORDER: tuple[tuple[str, Stage], ...] = (
    ("full_name", Stage.FULL_NAME),
    ("has_licence", Stage.HAS_LICENCE),
    ("zone", Stage.ZONE),
    ("availability", Stage.AVAILABILITY),
    ("schedule", Stage.SCHEDULE),
    ("experience_years", Stage.EXPERIENCE),
    ("start_date", Stage.START_DATE),
)


class CandidateProfile(BaseModel):
    """Screening JSON contract; the first None field in REQUIRED_FIELD_ORDER is the current stage."""

    full_name: str | None = None
    has_licence: bool | None = None
    zone: str | None = None
    availability: list[Availability] | None = None
    schedule: Schedule | None = None
    experience_years: int | None = Field(default=None, ge=0, le=40)
    experience_platforms: list[str] = Field(default_factory=list)
    start_date: date | None = None

    @field_validator("full_name")
    @classmethod
    def full_name_has_two_alphabetic_tokens(cls, value: str | None) -> str | None:
        if value is None:
            return None
        tokens = value.strip().split()
        if len(tokens) < 2 or not all(
            token.replace("-", "").replace("'", "").isalpha() for token in tokens
        ):
            raise ValueError("Full name needs at least two alphabetic words")
        return " ".join(tokens)

    @field_validator("availability")
    @classmethod
    def availability_not_empty(cls, value: list[Availability] | None) -> list[Availability] | None:
        if value is not None and not value:
            raise ValueError("Pick at least one availability option")
        return value

    def current_stage(self) -> Stage:
        for field_name, stage in REQUIRED_FIELD_ORDER:
            if getattr(self, field_name) is None:
                return stage
        return Stage.OUTCOME

    def missing_fields(self) -> list[str]:
        return [name for name, _ in REQUIRED_FIELD_ORDER if getattr(self, name) is None]
