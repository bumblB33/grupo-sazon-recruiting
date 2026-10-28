import unicodedata

from rapidfuzz import fuzz


def normalise_name(name: str) -> str:
    """Casefolded, accent-stripped alphabetic tokens in sorted order, so spelling and order do not count."""
    stripped = "".join(
        char for char in unicodedata.normalize("NFKD", name) if not unicodedata.combining(char)
    )
    tokens = "".join(char if char.isalpha() else " " for char in stripped.casefold()).split()
    return " ".join(sorted(tokens))


def name_similarity(stated: str, applicant: str) -> float:
    """0.0 to 1.0. A stated name that is a subset of the applicant's (fewer surnames) scores 1.0."""
    left, right = normalise_name(stated), normalise_name(applicant)
    if not left or not right:
        return 0.0
    return fuzz.token_set_ratio(left, right) / 100


def first_name(name: str) -> str:
    tokens = name.split()
    return tokens[0] if tokens else ""
