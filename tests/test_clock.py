from datetime import datetime
from zoneinfo import ZoneInfo

from screening_agent.config import settings
from screening_agent.domain.clock import candidate_today


def test_known_zone_uses_its_timezone():
    assert candidate_today("Tijuana") == datetime.now(ZoneInfo("America/Tijuana")).date()


def test_unknown_zone_falls_back_to_default_timezone():
    expected = datetime.now(ZoneInfo(settings.default_timezone)).date()
    assert candidate_today(None) == expected
    assert candidate_today("Atlantis") == expected
