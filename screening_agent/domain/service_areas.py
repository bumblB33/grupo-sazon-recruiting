from collections.abc import Iterable
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from rapidfuzz import fuzz, process, utils


@dataclass(frozen=True)
class ServiceArea:
    name: str
    timezone: str
    aliases: tuple[str, ...] = ()


# TODO: replace fixture list with the client's 45 real locations and their local aliases
SERVICE_AREAS: tuple[ServiceArea, ...] = (
    ServiceArea("Madrid", "Europe/Madrid"),
    ServiceArea("Barcelona", "Europe/Madrid", ("Barna",)),
    ServiceArea("Valencia", "Europe/Madrid"),
    ServiceArea("Sevilla", "Europe/Madrid", ("Seville",)),
    ServiceArea("Zaragoza", "Europe/Madrid"),
    ServiceArea("Málaga", "Europe/Madrid"),
    ServiceArea("Bilbao", "Europe/Madrid"),
    ServiceArea("Alicante", "Europe/Madrid"),
    ServiceArea(
        "Ciudad de México",
        "America/Mexico_City",
        ("CDMX", "Mexico City", "DF", "Distrito Federal"),
    ),
    ServiceArea("Guadalajara", "America/Mexico_City"),
    ServiceArea("Monterrey", "America/Monterrey"),
    ServiceArea("Puebla", "America/Mexico_City"),
    ServiceArea("Querétaro", "America/Mexico_City"),
    ServiceArea("Tijuana", "America/Tijuana"),
    ServiceArea("León", "America/Mexico_City"),
    ServiceArea("Mérida", "America/Merida"),
)

CONFIRM_THRESHOLD = 70


@dataclass(frozen=True)
class ZoneMatch:
    query: str
    area: str | None
    score: float
    exact: bool = False

    @property
    def accepted(self) -> bool:
        return self.exact

    @property
    def needs_confirmation(self) -> bool:
        return self.area is not None and not self.exact


def match_zone(city: str, areas: Iterable[ServiceArea] = SERVICE_AREAS) -> ZoneMatch:
    """Only a normalised exact match on a name or alias is accepted; a fuzzy hit above CONFIRM_THRESHOLD
    is offered for confirmation, because WRatio scores substrings like "Nuevo León" as León."""
    lookup = {name: area.name for area in areas for name in (area.name, *area.aliases)}
    normalised = {utils.default_process(name): canonical for name, canonical in lookup.items()}
    exact = normalised.get(utils.default_process(city))
    if exact:
        return ZoneMatch(query=city, area=exact, score=100.0, exact=True)
    result = process.extractOne(
        city.strip(),
        list(lookup),
        scorer=fuzz.WRatio,
        processor=utils.default_process,
        score_cutoff=CONFIRM_THRESHOLD,
    )
    if result is None:
        return ZoneMatch(query=city, area=None, score=0.0)
    matched, score, _ = result
    return ZoneMatch(query=city, area=lookup[matched], score=float(score))


def timezone_of(
    area_name: str | None, areas: Iterable[ServiceArea] = SERVICE_AREAS
) -> ZoneInfo | None:
    for area in areas:
        if area.name == area_name:
            return ZoneInfo(area.timezone)
    return None
