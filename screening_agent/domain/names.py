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


NAME_PUNCTUATION = "-'.·"


def clean_applicant_name(value: str) -> str:
    """Whitespace collapsed; every token alphabetic apart from hyphens, apostrophes and periods.
    The name reaches the system prompt and the candidate's phone, so nothing else is allowed in."""
    tokens = value.split()
    if not tokens or not all(_is_name_token(token) for token in tokens):
        raise ValueError("name must be one or more words made of letters")
    return " ".join(tokens)


def _is_name_token(token: str) -> bool:
    letters = "".join(char for char in token if char not in NAME_PUNCTUATION)
    return bool(letters) and letters.isalpha()
