import re
from datetime import date

_ROSTER_IN_URL = re.compile(r"roster", re.IGNORECASE)
_ROSTER_WORD = re.compile(r"\broster\b", re.IGNORECASE)
_STUDENT_ATHLETE = re.compile(r"\bstudent[-\s]?athletes?\b", re.IGNORECASE)
_CLASS_OF = re.compile(r"\bclass of 20\d{2}\b", re.IGNORECASE)
_BIRTH_YEAR = re.compile(
    r"(?:birth\s*year|born(?:\s+(?:in|on))?|d\.o\.b\.?|dob)[:\s,]*((?:19|20)\d{2})",
    re.IGNORECASE,
)
_U_AGE = re.compile(r"\bu-?(?:1[0-7]|[4-9])\b", re.IGNORECASE)
_U_AGE_TEAM = re.compile(
    r"\bu-?(?:1[0-7]|[4-9])\b(?:\s+|-)(?:team|club|program|division|league|squad|schedule|tournament)",
    re.IGNORECASE,
)
_U_AGE_PERSON_ROLE = re.compile(
    r"\b(?:player|athlete|student|forward|guard|goalkeeper|goalie)\b.{0,24}"
    r"\bu-?(?:1[0-7]|[4-9])\b"
    r"|\bu-?(?:1[0-7]|[4-9])\b.{0,24}"
    r"\b(?:player|athlete|student|forward|guard|goalkeeper|goalie)\b",
    re.IGNORECASE,
)
_U_AGE_PERSON_NAME = re.compile(
    r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\b.{0,16}\bu-?(?:1[0-7]|[4-9])\b"
    r"|\bu-?(?:1[0-7]|[4-9])\b.{0,16}\b[A-Z][a-z]+\s+[A-Z][a-z]+\b",
    re.IGNORECASE,
)


def is_minor_related(source_url: str, title: str, page_context: str) -> bool:
    if _ROSTER_IN_URL.search(source_url) is not None or _ROSTER_WORD.search(title) is not None:
        return True
    if _STUDENT_ATHLETE.search(title) is not None or _STUDENT_ATHLETE.search(page_context) is not None:
        return True
    if _CLASS_OF.search(title) is not None or _CLASS_OF.search(page_context) is not None:
        return True
    if _has_minor_birth_year(title, page_context):
        return True
    return _u_age_attached_to_person(title, page_context)


def _has_minor_birth_year(title: str, page_context: str) -> bool:
    text = f"{title} {page_context}"
    cutoff_year = date.today().year - 17
    for match in _BIRTH_YEAR.finditer(text):
        if int(match.group(1)) >= cutoff_year:
            return True
    return False


def _u_age_attached_to_person(title: str, page_context: str) -> bool:
    text = f"{title} {page_context}"
    if _U_AGE.search(text) is None:
        return False
    stripped = _U_AGE_TEAM.sub("", text)
    if _U_AGE.search(stripped) is None:
        return False
    if _U_AGE_PERSON_ROLE.search(stripped) is not None:
        return True
    return _U_AGE_PERSON_NAME.search(stripped) is not None
