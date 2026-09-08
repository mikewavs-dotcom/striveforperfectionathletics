import re

_STATE_NAMES: dict[str, str] = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "district of columbia": "DC",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
}

_STREET_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bavenue\b", re.IGNORECASE), "Ave"),
    (re.compile(r"\bboulevard\b", re.IGNORECASE), "Blvd"),
    (re.compile(r"\bcircle\b", re.IGNORECASE), "Cir"),
    (re.compile(r"\bcourt\b", re.IGNORECASE), "Ct"),
    (re.compile(r"\bdrive\b", re.IGNORECASE), "Dr"),
    (re.compile(r"\blane\b", re.IGNORECASE), "Ln"),
    (re.compile(r"\bparkway\b", re.IGNORECASE), "Pkwy"),
    (re.compile(r"\bplace\b", re.IGNORECASE), "Pl"),
    (re.compile(r"\broad\b", re.IGNORECASE), "Rd"),
    (re.compile(r"\bsquare\b", re.IGNORECASE), "Sq"),
    (re.compile(r"\bstreet\b", re.IGNORECASE), "St"),
    (re.compile(r"\bsuite\b", re.IGNORECASE), "Ste"),
    (re.compile(r"\bapartment\b", re.IGNORECASE), "Apt"),
    (re.compile(r"\bnorth\b", re.IGNORECASE), "N"),
    (re.compile(r"\bsouth\b", re.IGNORECASE), "S"),
    (re.compile(r"\beast\b", re.IGNORECASE), "E"),
    (re.compile(r"\bwest\b", re.IGNORECASE), "W"),
)
_WHITESPACE = re.compile(r"\s+")
_POSTAL = re.compile(r"^(\d{5})(?:[-\s]?(\d{4}))?$")


def standardize_street(street: str | None) -> str | None:
    if street is None or street.strip() == "":
        return None
    text = _WHITESPACE.sub(" ", street.strip())
    for pattern, replacement in _STREET_REPLACEMENTS:
        text = pattern.sub(replacement, text)
    return text


def standardize_city(city: str | None) -> str | None:
    if city is None or city.strip() == "":
        return None
    text = _WHITESPACE.sub(" ", city.strip()).title()
    return text


def standardize_state(state: str | None) -> str | None:
    if state is None or state.strip() == "":
        return None
    text = _WHITESPACE.sub(" ", state.strip())
    if len(text) == 2 and text.isalpha():
        return text.upper()
    mapped = _STATE_NAMES.get(text.lower())
    if mapped is None:
        return text.upper()
    return mapped


def standardize_postal_code(postal_code: str | None) -> str | None:
    if postal_code is None or postal_code.strip() == "":
        return None
    digits = postal_code.strip()
    match = _POSTAL.match(digits)
    if match is None:
        return digits
    if match.group(2) is None:
        return match.group(1)
    return f"{match.group(1)}-{match.group(2)}"


def standardize_organization_address(
    street: str | None,
    city: str | None,
    state: str | None,
    postal_code: str | None,
) -> tuple[str | None, str | None, str | None, str | None]:
    return (
        standardize_street(street),
        standardize_city(city),
        standardize_state(state),
        standardize_postal_code(postal_code),
    )
