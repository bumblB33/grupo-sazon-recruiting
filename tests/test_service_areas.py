from zoneinfo import ZoneInfo

from screening_agent.domain.service_areas import match_zone, timezone_of


def test_exact_match_is_accepted():
    assert match_zone("madrid").accepted


def test_typo_needs_confirmation():
    match = match_zone("madird")
    assert match.area == "Madrid"
    assert match.needs_confirmation


def test_alias_resolves_to_canonical():
    assert match_zone("Mexico City").area == "Ciudad de México"


def test_unknown_city_is_out():
    match = match_zone("Toledo")
    assert match.area is None
    assert not match.accepted
    assert not match.needs_confirmation


def test_timezone_of_known_and_unknown_area():
    assert timezone_of("Tijuana") == ZoneInfo("America/Tijuana")
    assert timezone_of("Madrid") == ZoneInfo("Europe/Madrid")
    assert timezone_of(None) is None
