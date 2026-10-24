from datetime import date, datetime
from zoneinfo import ZoneInfo

from screening_agent.config import settings
from screening_agent.domain.service_areas import timezone_of


def candidate_today(zone: str | None) -> date:
    """Calendar date where the candidate is, not where the server runs; a start date of "hoy" from
    Tijuana at 23:00 must not be rejected because UTC already rolled over."""
    timezone = timezone_of(zone) or ZoneInfo(settings.default_timezone)
    return datetime.now(timezone).date()
