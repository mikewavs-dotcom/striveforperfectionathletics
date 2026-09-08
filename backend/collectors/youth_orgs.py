import json
import logging
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urljoin, urlparse

import anthropic
from selectolax.parser import HTMLParser

from backend.app.config import get_settings
from backend.collectors.base import BaseCollector
from backend.compliance.minor_guard import is_minor_related
from backend.compliance.robots import hostname_of, is_denylisted
from backend.models import Contact, ContactRole, Organization, OrgType
from backend.normalize.addresses import standardize_organization_address
from backend.normalize.entities import canonical_name

logger = logging.getLogger(__name__)

CLAUDE_MODEL = "claude-sonnet-4-6"
STAFF_CONFIDENCE = 0.6
MAX_CRAWL_PAGES = 15
PLACES_PAGE_SIZE = 20
PLACES_FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,"
    "places.websiteUri,places.nationalPhoneNumber,places.rating,places.userRatingCount"
)
STAFF_INSTRUCTION = (
    'Return a JSON array of objects with keys "name", "title", "email", "phone". '
    "If a field cannot be extracted, use null. "
    "If you cannot identify real staff or coaches from the text, return an empty array. "
    "Do not guess."
)
QUERY_TERMS: tuple[str, ...] = (
    "AAU basketball club",
    "travel baseball organization",
    "7v7 football team",
    "youth sports showcase",
    "travel softball club",
    "club volleyball",
)
ORG_TYPE_BY_QUERY: dict[str, OrgType] = {
    "AAU basketball club": OrgType.youth_sports_org,
    "travel baseball organization": OrgType.travel_program,
    "7v7 football team": OrgType.travel_program,
    "youth sports showcase": OrgType.showcase_operator,
    "travel softball club": OrgType.travel_program,
    "club volleyball": OrgType.travel_program,
}
_STAFF_KEYS = ("staff", "coach", "coaching", "directory")
_EVENTS_KEYS = ("event", "schedule", "tournament", "calendar")
_TEXT_CAP = 12000
_DATE = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)\s+\d{1,2}(?:,\s*\d{4})?\b"
    r"|\b\d{1,2}/\d{1,2}/\d{2,4}\b"
    r"|\b\d{4}-\d{2}-\d{2}\b",
    re.IGNORECASE,
)
_PERSON_NAME = re.compile(r"^[A-Z][a-z]+(?:\s+[A-Z][a-z'.-]+){1,3}$")
_ROSTER_SKIP = frozenset(
    {
        "name",
        "player",
        "players",
        "position",
        "number",
        "grade",
        "year",
        "home",
        "about",
        "contact",
        "roster",
        "team",
    }
)
_ADDRESS_STATE_ZIP = re.compile(r"^([A-Za-z]{2})\s+(\d{5}(?:-\d{4})?)$")


@dataclass(frozen=True)
class ParsedYouthOrg:
    place_id: str
    name: str
    formatted_address: str | None
    website: str | None
    phone: str | None
    rating: Decimal | None
    review_count: int | None
    query_term: str
    staff_text: str
    staff_source_url: str | None
    events_per_year: int | None
    roster_size_estimate: int | None
    source_urls: list[str]


class YouthOrgsCollector(BaseCollector):
    def __init__(self) -> None:
        super().__init__(requests_per_second=1.0)
        self._crawl_hosts: set[str] = set()

    @property
    def name(self) -> str:
        return "youth_orgs"

    @property
    def allowed_domains(self) -> Sequence[str]:
        hosts = set(self._crawl_hosts)
        search_url = get_settings().google_places_search_url.strip()
        if search_url != "":
            hosts.add(hostname_of(search_url))
        return tuple(sorted(hosts))

    def fetch(self) -> dict[str, Any]:
        settings = get_settings()
        search_url = settings.google_places_search_url.strip()
        api_key = settings.google_places_api_key.strip()
        grid_raw = settings.google_places_grid.strip()
        if search_url == "" or api_key == "" or grid_raw == "":
            raise ValueError(
                "youth_orgs requires GOOGLE_PLACES_API_KEY, "
                "GOOGLE_PLACES_SEARCH_URL, and GOOGLE_PLACES_GRID"
            )
        cells = parse_grid(grid_raw)
        places: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        headers = {
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": PLACES_FIELD_MASK,
        }
        for south, west, north, east in cells:
            for term in QUERY_TERMS:
                payload = {
                    "textQuery": term,
                    "pageSize": PLACES_PAGE_SIZE,
                    "locationRestriction": {
                        "rectangle": {
                            "low": {"latitude": south, "longitude": west},
                            "high": {"latitude": north, "longitude": east},
                        }
                    },
                }
                try:
                    body = self.fetch_json_post(search_url, payload, extra_headers=headers)
                except Exception:
                    logger.exception(
                        "Places search failed query=%s cell=%s",
                        term,
                        (south, west, north, east),
                    )
                    continue
                if body is None:
                    continue
                rows = body.get("places")
                if not isinstance(rows, list):
                    continue
                if len(rows) >= PLACES_PAGE_SIZE:
                    logger.warning(
                        "Places search hit pageSize cap query=%s cell=%s count=%s",
                        term,
                        (south, west, north, east),
                        len(rows),
                    )
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    place_id = row.get("id")
                    if not isinstance(place_id, str) or place_id.strip() == "":
                        continue
                    if place_id in seen_ids:
                        continue
                    seen_ids.add(place_id)
                    tagged = dict(row)
                    tagged["query_term"] = term
                    places.append(tagged)
        pages: list[dict[str, str]] = []
        for place in places:
            website = _string(place.get("websiteUri"))
            if website is None:
                continue
            try:
                host = hostname_of(website)
            except ValueError:
                continue
            if is_denylisted(website):
                logger.info("Skipping denylisted website for place %s", place.get("id"))
                continue
            self._crawl_hosts.add(host)
            crawled = self._crawl_site(website)
            place_id = place["id"]
            assert isinstance(place_id, str)
            for url, html in crawled:
                pages.append({"place_id": place_id, "url": url, "html": html})
        return {"places": places, "pages": pages}

    def parse(self, raw: object) -> list[ParsedYouthOrg]:
        if not isinstance(raw, dict):
            return []
        places = raw.get("places")
        pages_raw = raw.get("pages")
        if not isinstance(places, list):
            return []
        pages_by_place: dict[str, list[tuple[str, str]]] = {}
        if isinstance(pages_raw, list):
            for page in pages_raw:
                if not isinstance(page, dict):
                    continue
                place_id = page.get("place_id")
                url = page.get("url")
                html = page.get("html")
                if not isinstance(place_id, str) or not isinstance(url, str):
                    continue
                if not isinstance(html, str):
                    continue
                pages_by_place.setdefault(place_id, []).append((url, html))
        parsed: list[ParsedYouthOrg] = []
        for place in places:
            org = _parsed_from_place(place, pages_by_place)
            if org is not None:
                parsed.append(org)
        return parsed

    def to_records(self, parsed: object) -> Sequence[Organization | Contact]:
        if not isinstance(parsed, list):
            return []
        records: list[Organization | Contact] = []
        for item in parsed:
            if not isinstance(item, ParsedYouthOrg):
                continue
            records.append(_organization_from_parsed(item))
            staff_text = item.staff_text.strip()
            people: list[dict[str, str | None]] = []
            if staff_text != "":
                try:
                    people = extract_staff(staff_text)
                except Exception:
                    logger.exception("Staff extraction failed for %s", item.website)
                    people = []
            source_url = item.staff_source_url or item.website or ""
            for person in people:
                contact = _contact_from_staff(person, source_url, staff_text)
                if contact is not None:
                    records.append(contact)
        return records

    def _crawl_site(self, website: str) -> list[tuple[str, str]]:
        start = _strip_fragment(website)
        to_visit = [start]
        visited: set[str] = set()
        pages: list[tuple[str, str]] = []
        while to_visit and len(pages) < MAX_CRAWL_PAGES:
            url = to_visit.pop(0)
            if url in visited:
                continue
            visited.add(url)
            try:
                html = self.fetch_html(url)
            except Exception:
                logger.exception("youth_orgs crawl failed for %s", url)
                continue
            if html is None:
                continue
            pages.append((url, html))
            for link in _same_domain_links(html, url):
                if link in visited or link in to_visit:
                    continue
                to_visit.append(link)
            to_visit.sort(key=_link_priority)
        return pages


def parse_grid(raw: str) -> list[tuple[float, float, float, float]]:
    parts = [part.strip() for part in raw.split(",")]
    if len(parts) != 5:
        raise ValueError("GOOGLE_PLACES_GRID must be south,west,north,east,step_degrees")
    try:
        south, west, north, east, step = (float(part) for part in parts)
    except ValueError as exc:
        raise ValueError("GOOGLE_PLACES_GRID values must be numbers") from exc
    if step <= 0:
        raise ValueError("GOOGLE_PLACES_GRID step must be positive")
    if north <= south or east <= west:
        raise ValueError("GOOGLE_PLACES_GRID north/east must be greater than south/west")
    cells: list[tuple[float, float, float, float]] = []
    lat = south
    while lat < north:
        cell_north = min(lat + step, north)
        lon = west
        while lon < east:
            cell_east = min(lon + step, east)
            cells.append((lat, lon, cell_north, cell_east))
            lon += step
        lat += step
    return cells


def extract_staff(text: str) -> list[dict[str, str | None]]:
    stripped = text.strip()
    if stripped == "":
        return []
    client = anthropic.Anthropic(api_key=get_settings().anthropic_api_key)
    prompt = f"{STAFF_INSTRUCTION}\n\nPAGE TEXT:\n{stripped[:_TEXT_CAP]}"
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
            logger.exception("Claude staff extraction returned an API error")
            return []
    if message is None:
        if last_error is not None:
            logger.error("Claude staff extraction failed", exc_info=last_error)
        return []
    return parse_staff_json(_message_text(message.content))


def parse_staff_json(text: str) -> list[dict[str, str | None]]:
    data = _load_json_array(text)
    people: list[dict[str, str | None]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = _nullable_string(item.get("name"))
        if name is None:
            continue
        people.append(
            {
                "name": name,
                "title": _nullable_string(item.get("title")),
                "email": _nullable_string(item.get("email")),
                "phone": _nullable_string(item.get("phone")),
            }
        )
    return people


def count_dated_entries(html: str) -> int:
    text = _visible_text(html)
    found = {match.group(0).strip() for match in _DATE.finditer(text)}
    return len(found)


def count_roster_entries(html: str) -> int:
    tree = HTMLParser(html)
    names: set[str] = set()
    nodes = tree.css("li, tr")
    if len(nodes) == 0:
        body = tree.body
        if body is not None:
            nodes = [body]
    for node in nodes:
        text = re.sub(r"\s+", " ", node.text(separator=" ", strip=True)).strip()
        candidate = _roster_name_candidate(text)
        if candidate is not None:
            names.add(candidate)
    return len(names)


def _parsed_from_place(
    place: object, pages_by_place: Mapping[str, list[tuple[str, str]]]
) -> ParsedYouthOrg | None:
    if not isinstance(place, dict):
        return None
    place_id = _string(place.get("id"))
    name = _display_name(place.get("displayName"))
    if place_id is None or name is None:
        return None
    query_term = _string(place.get("query_term")) or QUERY_TERMS[0]
    website = _string(place.get("websiteUri"))
    pages = pages_by_place.get(place_id, [])
    staff_chunks: list[str] = []
    staff_source_url: str | None = None
    saw_events = False
    saw_roster = False
    dated = 0
    roster = 0
    source_urls: list[str] = []
    for url, html in pages:
        source_urls.append(url)
        kind = _page_kind(url)
        if kind == "staff":
            text = _visible_text(html)
            if text != "":
                staff_chunks.append(text)
                if staff_source_url is None:
                    staff_source_url = url
        elif kind == "events":
            saw_events = True
            dated += count_dated_entries(html)
        elif kind == "roster":
            saw_roster = True
            roster += count_roster_entries(html)
    if website is not None and website not in source_urls:
        source_urls.insert(0, website)
    return ParsedYouthOrg(
        place_id=place_id,
        name=name,
        formatted_address=_string(place.get("formattedAddress")),
        website=website,
        phone=_string(place.get("nationalPhoneNumber")),
        rating=_optional_decimal(place.get("rating")),
        review_count=_optional_int(place.get("userRatingCount")),
        query_term=query_term,
        staff_text="\n\n".join(staff_chunks),
        staff_source_url=staff_source_url,
        events_per_year=dated if saw_events else None,
        roster_size_estimate=roster if saw_roster else None,
        source_urls=source_urls,
    )


def _organization_from_parsed(item: ParsedYouthOrg) -> Organization:
    street, city, state, postal = parse_formatted_address(item.formatted_address)
    return Organization(
        name=item.name,
        canonical_name=canonical_name(item.name),
        org_type=ORG_TYPE_BY_QUERY.get(item.query_term, OrgType.youth_sports_org),
        website=item.website,
        phone=item.phone,
        street=street,
        city=city,
        state=state,
        postal_code=postal,
        google_place_id=item.place_id,
        google_rating=item.rating,
        google_review_count=item.review_count,
        roster_size_estimate=item.roster_size_estimate,
        events_per_year=item.events_per_year,
        source_urls=item.source_urls or None,
        is_active=True,
    )


def _contact_from_staff(
    person: Mapping[str, str | None], source_url: str, page_context: str
) -> Contact | None:
    full_name = person.get("name")
    if not isinstance(full_name, str) or full_name.strip() == "":
        return None
    title_raw = person.get("title")
    first_name, last_name = _split_name(full_name)
    return Contact(
        full_name=full_name,
        first_name=first_name,
        last_name=last_name,
        title_raw=title_raw,
        role=_role_from_title(title_raw),
        email=person.get("email"),
        phone=person.get("phone"),
        source_url=source_url or None,
        confidence=STAFF_CONFIDENCE,
        is_minor_related=is_minor_related(source_url, title_raw or full_name, page_context),
    )


def parse_formatted_address(
    value: str | None,
) -> tuple[str | None, str | None, str | None, str | None]:
    if value is None or value.strip() == "":
        return None, None, None, None
    parts = [part.strip() for part in value.split(",") if part.strip() != ""]
    if parts and parts[-1].upper() in {"USA", "US", "UNITED STATES"}:
        parts = parts[:-1]
    street: str | None = None
    city: str | None = None
    state: str | None = None
    postal: str | None = None
    if len(parts) >= 3:
        street = parts[0]
        city = parts[1]
        match = _ADDRESS_STATE_ZIP.match(parts[2])
        if match is not None:
            state = match.group(1)
            postal = match.group(2)
        else:
            state = parts[2]
    elif len(parts) == 2:
        city = parts[0]
        match = _ADDRESS_STATE_ZIP.match(parts[1])
        if match is not None:
            state = match.group(1)
            postal = match.group(2)
        else:
            state = parts[1]
    elif len(parts) == 1:
        city = parts[0]
    return standardize_organization_address(street, city, state, postal)


def _role_from_title(title: str | None) -> ContactRole:
    if title is None or title.strip() == "":
        return ContactRole.unknown
    lowered = title.lower()
    if "compliance" in lowered:
        return ContactRole.compliance_officer
    compact = re.sub(r"\s+", " ", lowered).strip()
    if compact in {"ad", "athletic director", "director of athletics"}:
        return ContactRole.athletic_director
    if "head coach" in lowered:
        return ContactRole.head_coach
    if "assistant coach" in lowered:
        return ContactRole.assistant_coach
    if "executive director" in lowered:
        return ContactRole.executive_director
    return ContactRole.unknown


def _page_kind(url: str) -> str:
    path = urlparse(url).path.lower()
    if any(key in path for key in _STAFF_KEYS):
        return "staff"
    if any(key in path for key in _EVENTS_KEYS):
        return "events"
    if "roster" in path:
        return "roster"
    if "about" in path:
        return "about"
    return "other"


def _link_priority(url: str) -> int:
    kind = _page_kind(url)
    order = {"staff": 0, "about": 1, "events": 2, "roster": 3}
    return order.get(kind, 9)


def _same_domain_links(html: str, page_url: str) -> list[str]:
    tree = HTMLParser(html)
    found: list[str] = []
    try:
        origin_host = hostname_of(page_url)
    except ValueError:
        return []
    for node in tree.css("a[href]"):
        href = node.attributes.get("href")
        if not isinstance(href, str) or href.strip() == "":
            continue
        absolute = _strip_fragment(urljoin(page_url, href))
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"}:
            continue
        try:
            if hostname_of(absolute) != origin_host:
                continue
            if is_denylisted(absolute):
                continue
        except ValueError:
            continue
        found.append(absolute)
    return found


def _strip_fragment(url: str) -> str:
    parsed = urlparse(url)
    return parsed._replace(fragment="").geturl()


def _visible_text(html: str) -> str:
    tree = HTMLParser(html)
    for node in tree.css("script, style, noscript"):
        node.decompose()
    root = tree.body
    if root is None:
        return ""
    return re.sub(r"\s+", " ", root.text(separator=" ", strip=True)).strip()


def _roster_name_candidate(text: str) -> str | None:
    if text == "":
        return None
    first_cell = text.split("  ")[0].strip() if "  " in text else text
    tokens = first_cell.split()
    if len(tokens) >= 2:
        first_cell = " ".join(tokens[:2])
    if first_cell.lower() in _ROSTER_SKIP:
        return None
    if _PERSON_NAME.fullmatch(first_cell) is None:
        return None
    return first_cell


def _display_name(value: object) -> str | None:
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, dict):
        return _string(value.get("text"))
    return None


def _string(value: object) -> str | None:
    if isinstance(value, str) and value.strip() != "":
        return value.strip()
    return None


def _nullable_string(value: object) -> str | None:
    return _string(value)


def _optional_decimal(value: object) -> Decimal | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str) and value.strip() != "":
        try:
            return Decimal(value)
        except (InvalidOperation, ValueError):
            return None
    return None


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _split_name(full_name: str) -> tuple[str | None, str | None]:
    parts = full_name.split()
    if len(parts) == 0:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return parts[0], " ".join(parts[1:])


def _load_json_array(text: str) -> list[object]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("[")
        end = stripped.rfind("]")
        if start == -1 or end == -1:
            return []
        try:
            data = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            return []
    if not isinstance(data, list):
        return []
    return data


def _message_text(content: Sequence[object]) -> str:
    parts: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
    return " ".join(parts).strip()


def main() -> None:
    YouthOrgsCollector().run()


if __name__ == "__main__":
    main()
