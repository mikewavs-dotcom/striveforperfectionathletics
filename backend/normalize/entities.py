import re

_LEGAL_SUFFIXES = (
    "incorporated",
    "corporation",
    "company",
    "foundation",
    "limited",
    "l.l.c",
    "llc",
    "l.l.p",
    "llp",
    "p.l.l.c",
    "pllc",
    "l.p",
    "lp",
    "p.c",
    "pc",
    "inc",
    "corp",
    "ltd",
    "co",
    "nfp",
)

_SUFFIX_PATTERN = re.compile(
    r"(?:,\s*|\s+)(?:" + "|".join(re.escape(suffix) for suffix in _LEGAL_SUFFIXES) + r")\.?\s*$",
    re.IGNORECASE,
)
_LEADING_THE = re.compile(r"^the\s+", re.IGNORECASE)
_NON_ALNUM = re.compile(r"[^a-z0-9\s]+")
_WHITESPACE = re.compile(r"\s+")


def canonical_name(name: str) -> str:
    text = name.strip().lower()
    text = _LEADING_THE.sub("", text)
    changed = True
    while changed:
        stripped = _SUFFIX_PATTERN.sub("", text).strip()
        changed = stripped != text
        text = stripped
    text = _NON_ALNUM.sub(" ", text)
    text = _WHITESPACE.sub(" ", text).strip()
    return text
