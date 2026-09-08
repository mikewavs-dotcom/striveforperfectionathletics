import logging
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anthropic
from selectolax.parser import HTMLParser

from backend.app.config import get_settings
from backend.collectors.base import BaseCollector
from backend.collectors.youth_orgs import parse_staff_json
from backend.compliance.minor_guard import is_minor_related
from backend.compliance.robots import hostname_of
from backend.models import Contact, ContactRole, Organization, OrgType
from backend.normalize.addresses import standardize_city, standardize_state
from backend.normalize.entities import canonical_name

logger = logging.getLogger(__name__)

CLAUDE_MODEL = "claude-sonnet-4-6"
STRUCTURED_CONFIDENCE = 0.7
CLAUDE_CONFIDENCE = 0.5
UNMAPPED_LOG = "Unmapped staff title for review"
PATTERNS: tuple[str, ...] = ("table", "definition_list", "cards")
DIRECTORY_INSTRUCTION = (
    'Return a JSON array of objects with keys "name", "title", "email", "phone". '
    "If a field cannot be extracted, use null. "
    "If you cannot identify real staff from the text, return an empty array. "
    "Do not guess."
)
_TEXT_CAP = 12000
_EMAIL = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
_PHONE = re.compile(r"\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}")
_HEADER_WORDS = frozenset(
    {
        "name",
        "staff",
        "person",
        "full name",
        "title",
        "position",
        "role",
        "title/position",
        "email",
        "e-mail",
        "phone",
        "telephone",
        "tel",
        "department",
    }
)
_NAME_HEADER = frozenset({"name", "staff", "person", "full name"})
_TITLE_HEADER = frozenset({"title", "position", "role", "title/position"})
_EMAIL_HEADER = frozenset({"email", "e-mail"})
_PHONE_HEADER = frozenset({"phone", "telephone", "tel"})
_CARD_SELECTOR = (
    ".staff-card, .staff-member, .directory-card, article.staff, "
    "article.person, li.staff, li.staff-member"
)


@dataclass(frozen=True)
class DirectoryEntry:
    name: str
    url: str
    org_type: OrgType
    pattern: str
    city: str | None
    state: str | None


@dataclass(frozen=True)
class StaffPerson:
    name: str
    title: str | None
    email: str | None
    phone: str | None


@dataclass(frozen=True)
class ParsedDirectory:
    name: str
    url: str
    org_type: OrgType
    city: str | None
    state: str | None
    people: list[StaffPerson] = field(default_factory=list)
    page_text: str = ""
    strategy: str | None = None


class StaffDirectoryCollector(BaseCollector):
    def __init__(self) -> None:
        super().__init__(requests_per_second=1.0)

    @property
    def name(self) -> str:
        return "staff_directory"

    @property
    def allowed_domains(self) -> Sequence[str]:
        path = _resolved(get_settings().directories_path)
        if not path.is_file():
            return ()
        return tuple(sorted({hostname_of(entry.url) for entry in load_directories(path)}))

    def fetch(self) -> dict[str, Any]:
        entries = load_directories(_resolved(get_settings().directories_path))
        pages: list[dict[str, str]] = []
        for entry in entries:
            try:
                html = self.fetch_html(entry.url)
            except Exception:
                logger.exception("staff_directory failed to fetch %s", entry.url)
                continue
            if html is None:
                continue
            pages.append(
                {
                    "name": entry.name,
                    "url": entry.url,
                    "org_type": entry.org_type.value,
                    "pattern": entry.pattern,
                    "city": entry.city or "",
                    "state": entry.state or "",
                    "html": html,
                }
            )
        return {"pages": pages}

    def parse(self, raw: object) -> list[ParsedDirectory]:
        if not isinstance(raw, dict):
            return []
        pages = raw.get("pages")
        if not isinstance(pages, list):
            return []
        parsed: list[ParsedDirectory] = []
        for page in pages:
            if not isinstance(page, dict):
                continue
            directory = _parsed_from_page(page)
            if directory is not None:
                parsed.append(directory)
        return parsed

    def to_records(self, parsed: object) -> Sequence[Organization | Contact]:
        if not isinstance(parsed, list):
            return []
        records: list[Organization | Contact] = []
        for item in parsed:
            if not isinstance(item, ParsedDirectory):
                continue
            records.append(_organization_from_parsed(item))
            people = item.people
            confidence = STRUCTURED_CONFIDENCE
            if len(people) == 0:
                try:
                    people = extract_directory_staff(item.page_text)
                except Exception:
                    logger.exception("Claude directory extraction failed for %s", item.url)
                    people = []
                confidence = CLAUDE_CONFIDENCE
            for person in people:
                contact = _contact_from_person(person, item.url, item.page_text, confidence)
                if contact is not None:
                    records.append(contact)
        return records


def load_directories(path: Path) -> list[DirectoryEntry]:
    if not path.is_file():
        return []
    entries: list[DirectoryEntry] = []
    current: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if stripped == "" or stripped.startswith("#"):
            continue
        if stripped.startswith("- "):
            if current:
                entry = _directory_entry(current)
                if entry is not None:
                    entries.append(entry)
                current = {}
            stripped = stripped[2:].strip()
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        current[key.strip()] = value.strip().strip("\"'")
    if current:
        entry = _directory_entry(current)
        if entry is not None:
            entries.append(entry)
    return entries


def parse_structured(html: str, preferred: str) -> tuple[list[StaffPerson], str | None]:
    strategies: dict[str, Any] = {
        "table": parse_table,
        "definition_list": parse_definition_list,
        "cards": parse_cards,
    }
    preferred_key = preferred if preferred in strategies else "table"
    order = [preferred_key] + [name for name in PATTERNS if name != preferred_key]
    for name in order:
        people = strategies[name](html)
        if len(people) > 0:
            return people, name
    return [], None


def parse_table(html: str) -> list[StaffPerson]:
    tree = HTMLParser(html)
    people: list[StaffPerson] = []
    for table in tree.css("table"):
        people.extend(_people_from_table(table))
    return _unique_people(people)


def parse_definition_list(html: str) -> list[StaffPerson]:
    tree = HTMLParser(html)
    people: list[StaffPerson] = []
    for dl in tree.css("dl"):
        pending_name: str | None = None
        child = dl.child
        while child is not None:
            tag = child.tag
            if tag == "dt":
                pending_name = _clean_text(child.text(separator=" ", strip=True))
            elif tag == "dd" and pending_name is not None:
                body = _clean_text(child.text(separator=" ", strip=True))
                email, phone = _contact_bits(child, body)
                title = _title_without_contact(body, email, phone)
                person = _staff_person(pending_name, title, email, phone)
                if person is not None:
                    people.append(person)
                pending_name = None
            child = child.next
    return _unique_people(people)


def parse_cards(html: str) -> list[StaffPerson]:
    tree = HTMLParser(html)
    nodes = tree.css(_CARD_SELECTOR)
    people: list[StaffPerson] = []
    for node in nodes:
        heading = node.css_first("h1, h2, h3, h4, .name, .staff-name")
        if heading is None:
            continue
        name = _clean_text(heading.text(separator=" ", strip=True))
        title_node = node.css_first(".title, .position, .role, p")
        title = _clean_text(title_node.text(separator=" ", strip=True)) if title_node is not None else None
        if title == name:
            title = None
        body = _clean_text(node.text(separator=" ", strip=True))
        email, phone = _contact_bits(node, body)
        person = _staff_person(name, title, email, phone)
        if person is not None:
            people.append(person)
    return _unique_people(people)


def extract_directory_staff(text: str) -> list[StaffPerson]:
    stripped = text.strip()
    if stripped == "":
        return []
    client = anthropic.Anthropic(api_key=get_settings().anthropic_api_key)
    prompt = f"{DIRECTORY_INSTRUCTION}\n\nPAGE TEXT:\n{stripped[:_TEXT_CAP]}"
    message: anthropic.types.Message | None = None
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            message = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            break
        except (anthropic.RateLimitError, anthropic.APIConnectionError) as exc:
            last_error = exc
            time.sleep(2**attempt)
        except anthropic.APIStatusError:
            logger.exception("Claude directory extraction returned an API error")
            return []
    if message is None:
        if last_error is not None:
            logger.error("Claude directory extraction failed", exc_info=last_error)
        return []
    rows = parse_staff_json(_message_text(message.content))
    people: list[StaffPerson] = []
    for row in rows:
        person = _staff_person(row.get("name"), row.get("title"), row.get("email"), row.get("phone"))
        if person is not None:
            people.append(person)
    return people


def role_from_title(title: str | None) -> ContactRole:
    if title is None or title.strip() == "":
        return ContactRole.unknown
    lowered = re.sub(r"\s+", " ", title).strip().lower()
    if "compliance" in lowered:
        return ContactRole.compliance_officer
    if lowered in {"ad", "a.d.", "a.d"}:
        return ContactRole.athletic_director
    if "athletic director" in lowered or "director of athletics" in lowered:
        return ContactRole.athletic_director
    if re.search(r"\bad\b", lowered) is not None:
        return ContactRole.athletic_director
    if "head coach" in lowered:
        return ContactRole.head_coach
    return ContactRole.unknown


def _parsed_from_page(page: Mapping[str, Any]) -> ParsedDirectory | None:
    html = page.get("html")
    url = page.get("url")
    name = page.get("name")
    org_type_raw = page.get("org_type")
    pattern_raw = page.get("pattern")
    if not isinstance(html, str) or not isinstance(url, str) or not isinstance(name, str):
        return None
    org_type = _org_type(org_type_raw)
    if org_type is None:
        logger.warning("Skipping directory with invalid org_type: %s", org_type_raw)
        return None
    pattern = pattern_raw if isinstance(pattern_raw, str) else "table"
    people, strategy = parse_structured(html, pattern)
    city = page.get("city")
    state = page.get("state")
    return ParsedDirectory(
        name=name,
        url=url,
        org_type=org_type,
        city=standardize_city(city if isinstance(city, str) and city.strip() != "" else None),
        state=standardize_state(state if isinstance(state, str) and state.strip() != "" else None),
        people=people,
        page_text=_visible_text(html),
        strategy=strategy,
    )


def _organization_from_parsed(item: ParsedDirectory) -> Organization:
    return Organization(
        name=item.name,
        canonical_name=canonical_name(item.name),
        org_type=item.org_type,
        website=item.url,
        city=item.city,
        state=item.state,
        source_urls=[item.url],
        is_active=True,
    )


def _contact_from_person(
    person: StaffPerson, source_url: str, page_context: str, confidence: float
) -> Contact | None:
    role = role_from_title(person.title)
    if role is ContactRole.unknown:
        logger.warning("%s: %s (%s)", UNMAPPED_LOG, person.title or "", source_url)
    first_name, last_name = _split_name(person.name)
    return Contact(
        full_name=person.name,
        first_name=first_name,
        last_name=last_name,
        title_raw=person.title,
        role=role,
        email=person.email,
        phone=person.phone,
        source_url=source_url,
        confidence=confidence,
        is_minor_related=is_minor_related(source_url, person.title or person.name, page_context),
    )


def _people_from_table(table: Any) -> list[StaffPerson]:
    rows = table.css("tr")
    if len(rows) == 0:
        return []
    header_cells = [_clean_text(cell.text(separator=" ", strip=True)).lower() for cell in rows[0].css("th, td")]
    columns = _column_map(header_cells)
    start = 1 if columns is not None else 0
    if columns is None:
        if len(header_cells) < 2:
            return []
        columns = {"name": 0, "title": 1, "email": 2 if len(header_cells) > 2 else None, "phone": None}
        if header_cells[0] in _HEADER_WORDS:
            start = 1
    people: list[StaffPerson] = []
    for row in rows[start:]:
        cells = [_clean_text(cell.text(separator=" ", strip=True)) for cell in row.css("td, th")]
        if len(cells) == 0:
            continue
        name = _cell(cells, columns["name"])
        title = _cell(cells, columns["title"])
        email = _cell(cells, columns["email"])
        phone = _cell(cells, columns["phone"])
        email_from_row, phone_from_row = _contact_bits(row, " ".join(cells))
        person = _staff_person(name, title, email or email_from_row, phone or phone_from_row)
        if person is not None:
            people.append(person)
    return people


def _column_map(headers: list[str]) -> dict[str, int | None] | None:
    name_idx: int | None = None
    title_idx: int | None = None
    email_idx: int | None = None
    phone_idx: int | None = None
    for index, header in enumerate(headers):
        if header in _NAME_HEADER and name_idx is None:
            name_idx = index
        elif header in _TITLE_HEADER and title_idx is None:
            title_idx = index
        elif header in _EMAIL_HEADER and email_idx is None:
            email_idx = index
        elif header in _PHONE_HEADER and phone_idx is None:
            phone_idx = index
    if name_idx is None or title_idx is None:
        return None
    return {"name": name_idx, "title": title_idx, "email": email_idx, "phone": phone_idx}


def _cell(cells: list[str], index: int | None) -> str | None:
    if index is None or index >= len(cells):
        return None
    value = cells[index]
    return value if value != "" else None


def _staff_person(
    name: str | None, title: str | None, email: str | None, phone: str | None
) -> StaffPerson | None:
    cleaned_name = _clean_text(name or "")
    if not _looks_like_name(cleaned_name):
        return None
    cleaned_title = _clean_text(title or "") or None
    if cleaned_title is not None and cleaned_title.lower() in _HEADER_WORDS:
        cleaned_title = None
    return StaffPerson(
        name=cleaned_name,
        title=cleaned_title,
        email=_clean_text(email or "") or None,
        phone=_clean_text(phone or "") or None,
    )


def _looks_like_name(text: str) -> bool:
    if text == "" or text.lower() in _HEADER_WORDS:
        return False
    if "@" in text:
        return False
    parts = [part for part in re.split(r"[,\s]+", text) if part]
    return len(parts) >= 2


def _contact_bits(node: Any, text: str) -> tuple[str | None, str | None]:
    email: str | None = None
    phone: str | None = None
    for link in node.css("a[href]"):
        href = link.attributes.get("href") if link.attributes else None
        if not isinstance(href, str):
            continue
        if href.lower().startswith("mailto:"):
            email = href.split(":", 1)[1].split("?")[0].strip() or email
        if href.lower().startswith("tel:"):
            phone = href.split(":", 1)[1].strip() or phone
    if email is None:
        match = _EMAIL.search(text)
        if match is not None:
            email = match.group(0)
    if phone is None:
        match = _PHONE.search(text)
        if match is not None:
            phone = match.group(0)
    return email, phone


def _title_without_contact(body: str, email: str | None, phone: str | None) -> str | None:
    text = body
    if email:
        text = text.replace(email, " ")
    if phone:
        text = text.replace(phone, " ")
    text = re.sub(r"\s+", " ", text).strip(" ,;-")
    return text or None


def _unique_people(people: Sequence[StaffPerson]) -> list[StaffPerson]:
    seen: set[str] = set()
    unique: list[StaffPerson] = []
    for person in people:
        key = person.name.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(person)
    return unique


def _visible_text(html: str) -> str:
    tree = HTMLParser(html)
    for node in tree.css("script, style, noscript"):
        node.decompose()
    root = tree.body
    if root is None:
        return ""
    return re.sub(r"\s+", " ", root.text(separator=" ", strip=True)).strip()


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _split_name(full_name: str) -> tuple[str | None, str | None]:
    if "," in full_name:
        last, first = [part.strip() for part in full_name.split(",", 1)]
        return (first or None, last or None)
    parts = full_name.split()
    if len(parts) == 0:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return parts[0], " ".join(parts[1:])


def _org_type(value: object) -> OrgType | None:
    if not isinstance(value, str) or value.strip() == "":
        return None
    try:
        return OrgType(value.strip())
    except ValueError:
        return None


def _directory_entry(values: Mapping[str, str]) -> DirectoryEntry | None:
    name = values.get("name")
    url = values.get("url")
    if not name or not url:
        return None
    org_type = _org_type(values.get("org_type"))
    if org_type is None:
        logger.warning("Skipping directory with invalid org_type: %s", values.get("org_type"))
        return None
    pattern = values.get("pattern") or "table"
    if pattern not in PATTERNS:
        pattern = "table"
    city = values.get("city")
    state = values.get("state")
    return DirectoryEntry(
        name=name,
        url=url,
        org_type=org_type,
        pattern=pattern,
        city=city if city else None,
        state=state if state else None,
    )


def _resolved(path: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        return Path.cwd() / candidate
    return candidate


def _message_text(content: Sequence[object]) -> str:
    parts: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
    return " ".join(parts).strip()


def main() -> None:
    StaffDirectoryCollector().run()


if __name__ == "__main__":
    main()
