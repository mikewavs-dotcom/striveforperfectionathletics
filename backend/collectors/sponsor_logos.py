import base64
import json
import logging
import re
import struct
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, cast
from urllib.parse import urljoin, urlparse
from uuid import UUID, uuid4

import anthropic
from selectolax.parser import HTMLParser
from sqlalchemy import select

from backend.app.config import get_settings
from backend.app.db import get_session_factory
from backend.collectors.base import BaseCollector
from backend.collectors.youth_orgs import parse_formatted_address
from backend.compliance.robots import hostname_of, is_denylisted
from backend.models import Organization, OrgType, Sponsor
from backend.normalize.entities import canonical_name

logger = logging.getLogger(__name__)

CLAUDE_MODEL = "claude-sonnet-4-6"
LOGO_CONFIDENCE = 0.7
MIN_IMAGE_PX = 60
VISION_BATCH_SIZE = 10
MAX_IMAGE_BYTES = 5_000_000
PLACES_PAGE_SIZE = 20
PLACES_FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,"
    "places.websiteUri,places.nationalPhoneNumber,places.rating,places.userRatingCount"
)
VISION_INSTRUCTION = (
    "For each image, identify the brand or company name shown. "
    "If the image is not a company logo, or the name is not legible, return null for that image. "
    "Do not guess. "
    "Return a JSON array with one object per image, in the same order, "
    'each object {"brand": string or null, "confidence": number or null}.'
)
SPONSOR_PATHS: tuple[str, ...] = (
    "/sponsor",
    "/partners",
    "/supporters",
    "/our-sponsors",
)
_SPONSOR_PATH_KEYS = ("sponsor", "partners", "supporters", "our-sponsors")
_STYLE_PX = re.compile(r"(width|height)\s*:\s*(\d+(?:\.\d+)?)px", re.IGNORECASE)
_FOOTER_SELECTOR = "footer, [role=contentinfo], #footer, .footer"


@dataclass(frozen=True)
class ParsedLogo:
    organization_id: UUID
    detected_on_url: str
    image_url: str
    width: int | None
    height: int | None


@dataclass(frozen=True)
class BrandHit:
    brand: str
    confidence: float
    detected_on_url: str
    logo_image_url: str
    organization_id: UUID


class SponsorLogosCollector(BaseCollector):
    def __init__(self) -> None:
        super().__init__(requests_per_second=1.0)
        self._hosts: set[str] = set()

    @property
    def name(self) -> str:
        return "sponsor_logos"

    @property
    def allowed_domains(self) -> Sequence[str]:
        hosts = set(self._hosts)
        search_url = get_settings().google_places_search_url.strip()
        if search_url != "":
            hosts.add(hostname_of(search_url))
        return tuple(sorted(hosts))

    def fetch(self) -> dict[str, Any]:
        pages: list[dict[str, str]] = []
        for org_id, website in _organizations_with_websites():
            try:
                self._allow_host(website)
            except ValueError:
                continue
            if is_denylisted(website):
                logger.info("Skipping denylisted website for organization %s", org_id)
                continue
            try:
                crawled = self._crawl_sponsor_pages(website)
            except Exception:
                logger.exception("sponsor_logos crawl failed for %s", website)
                continue
            for url, html in crawled:
                pages.append(
                    {
                        "organization_id": str(org_id),
                        "url": url,
                        "html": html,
                    }
                )
        return {"pages": pages}

    def parse(self, raw: object) -> list[ParsedLogo]:
        if not isinstance(raw, dict):
            return []
        pages = raw.get("pages")
        if not isinstance(pages, list):
            return []
        parsed: list[ParsedLogo] = []
        seen: set[tuple[UUID, str]] = set()
        for page in pages:
            if not isinstance(page, dict):
                continue
            org_raw = page.get("organization_id")
            url = page.get("url")
            html = page.get("html")
            if not isinstance(org_raw, str) or not isinstance(url, str) or not isinstance(html, str):
                continue
            try:
                org_id = UUID(org_raw)
            except ValueError:
                continue
            footer_only = not _is_sponsor_path(url)
            for image_url, width, height in extract_logo_candidates(html, url, footer_only=footer_only):
                key = (org_id, image_url)
                if key in seen:
                    continue
                if not _passes_size_filter(width, height):
                    continue
                seen.add(key)
                parsed.append(
                    ParsedLogo(
                        organization_id=org_id,
                        detected_on_url=url,
                        image_url=image_url,
                        width=width,
                        height=height,
                    )
                )
        return parsed

    def to_records(self, parsed: object) -> Sequence[Organization | Sponsor]:
        if not isinstance(parsed, list):
            return []
        qualified: list[ParsedLogo] = []
        payloads: list[tuple[bytes, str]] = []
        for item in parsed:
            if not isinstance(item, ParsedLogo):
                continue
            measured = self._qualify_image(item)
            if measured is None:
                continue
            logo, body, media_type = measured
            qualified.append(logo)
            payloads.append((body, media_type))
        try:
            hits = identify_brands(qualified, payloads)
        except Exception:
            logger.exception("sponsor_logos vision extraction failed")
            hits = []
        records: list[Organization | Sponsor] = []
        now = datetime.now(timezone.utc)
        seen_brands: set[tuple[UUID, str]] = set()
        for hit in hits:
            brand_key = (hit.organization_id, hit.brand.lower())
            if brand_key in seen_brands:
                continue
            seen_brands.add(brand_key)
            matched: Organization | None = None
            try:
                matched = self._business_from_brand(hit.brand)
            except Exception:
                logger.exception("Places brand resolve failed for %s", hit.brand)
            if matched is not None:
                records.append(matched)
            records.append(
                Sponsor(
                    brand_name=hit.brand,
                    detected_on_url=hit.detected_on_url,
                    detected_on_organization_id=hit.organization_id,
                    logo_image_url=hit.logo_image_url,
                    extraction_confidence=hit.confidence,
                    matched_organization_id=matched.id if matched is not None else None,
                    detected_at=now,
                )
            )
        return records

    def _crawl_sponsor_pages(self, website: str) -> list[tuple[str, str]]:
        origin = _origin(website)
        homepage = _strip_fragment(website)
        urls: list[str] = [homepage]
        for path in SPONSOR_PATHS:
            urls.append(urljoin(origin + "/", path.lstrip("/")))
        pages: list[tuple[str, str]] = []
        seen: set[str] = set()
        homepage_html: str | None = None
        for url in urls:
            if url in seen:
                continue
            seen.add(url)
            html = self._fetch_page(url)
            if html is None:
                continue
            pages.append((url, html))
            if url == homepage:
                homepage_html = html
        if homepage_html is not None:
            for link in _same_domain_links(homepage_html, homepage):
                if not _is_sponsor_path(link) or link in seen:
                    continue
                seen.add(link)
                html = self._fetch_page(link)
                if html is not None:
                    pages.append((link, html))
        return pages

    def _fetch_page(self, url: str) -> str | None:
        try:
            return self.fetch_html(url)
        except Exception:
            logger.exception("sponsor_logos page fetch failed for %s", url)
            return None

    def _qualify_image(self, item: ParsedLogo) -> tuple[ParsedLogo, bytes, str] | None:
        if item.width is not None and item.height is not None:
            if item.width <= MIN_IMAGE_PX or item.height <= MIN_IMAGE_PX:
                return None
        try:
            self._allow_host(item.image_url)
        except ValueError:
            return None
        if is_denylisted(item.image_url):
            return None
        try:
            fetched = self.fetch_bytes(item.image_url)
        except Exception:
            logger.exception("sponsor_logos image fetch failed for %s", item.image_url)
            return None
        if fetched is None:
            return None
        body, content_type = fetched
        if len(body) == 0 or len(body) > MAX_IMAGE_BYTES:
            return None
        media_type = _media_type(content_type, body)
        if media_type is None:
            return None
        size = image_size(body)
        width = item.width
        height = item.height
        if size is not None:
            width, height = size
        if width is None or height is None:
            return None
        if width <= MIN_IMAGE_PX or height <= MIN_IMAGE_PX:
            return None
        measured = ParsedLogo(
            organization_id=item.organization_id,
            detected_on_url=item.detected_on_url,
            image_url=item.image_url,
            width=width,
            height=height,
        )
        return measured, body, media_type

    def _business_from_brand(self, brand: str) -> Organization | None:
        places = search_places_for_brand(self, brand)
        if len(places) == 0:
            return None
        if len(places) >= PLACES_PAGE_SIZE:
            logger.warning("Places brand search hit pageSize cap brand=%s count=%s", brand, len(places))
        first = places[0]
        place_id = _string(first.get("id"))
        name = _display_name(first.get("displayName")) or brand
        street, city, state, postal = parse_formatted_address(_string(first.get("formattedAddress")))
        return Organization(
            id=uuid4(),
            name=name,
            canonical_name=canonical_name(name),
            org_type=OrgType.business,
            website=_string(first.get("websiteUri")),
            phone=_string(first.get("nationalPhoneNumber")),
            street=street,
            city=city,
            state=state,
            postal_code=postal,
            google_place_id=place_id,
            google_rating=_optional_decimal(first.get("rating")),
            google_review_count=_optional_int(first.get("userRatingCount")),
            location_count=len(places),
            source_urls=None,
            is_active=True,
        )

    def _allow_host(self, url: str) -> None:
        self._hosts.add(hostname_of(url))


def extract_logo_candidates(
    html: str, page_url: str, *, footer_only: bool
) -> list[tuple[str, int | None, int | None]]:
    tree = HTMLParser(html)
    roots: list[Any]
    if footer_only:
        roots = list(tree.css(_FOOTER_SELECTOR))
        if len(roots) == 0:
            return []
    else:
        roots = [tree]
    found: list[tuple[str, int | None, int | None]] = []
    seen: set[str] = set()
    for root in roots:
        for node in root.css("img"):
            src = node.attributes.get("src") or node.attributes.get("data-src")
            if not isinstance(src, str) or src.strip() == "":
                continue
            absolute = _strip_fragment(urljoin(page_url, src))
            parsed = urlparse(absolute)
            if parsed.scheme not in {"http", "https"}:
                continue
            if absolute in seen:
                continue
            try:
                if is_denylisted(absolute):
                    continue
            except ValueError:
                continue
            seen.add(absolute)
            width, height = _element_size(node)
            found.append((absolute, width, height))
    return found


def identify_brands(
    logos: Sequence[ParsedLogo], payloads: Sequence[tuple[bytes, str]]
) -> list[BrandHit]:
    if len(logos) == 0 or len(logos) != len(payloads):
        return []
    hits: list[BrandHit] = []
    for offset in range(0, len(logos), VISION_BATCH_SIZE):
        batch_logos = logos[offset : offset + VISION_BATCH_SIZE]
        batch_payloads = payloads[offset : offset + VISION_BATCH_SIZE]
        guesses = identify_brand_batch(batch_payloads)
        for logo, guess in zip(batch_logos, guesses, strict=False):
            brand = guess[0]
            confidence = guess[1]
            if brand is None:
                continue
            hits.append(
                BrandHit(
                    brand=brand,
                    confidence=confidence if confidence is not None else LOGO_CONFIDENCE,
                    detected_on_url=logo.detected_on_url,
                    logo_image_url=logo.image_url,
                    organization_id=logo.organization_id,
                )
            )
    return hits


def identify_brand_batch(payloads: Sequence[tuple[bytes, str]]) -> list[tuple[str | None, float | None]]:
    if len(payloads) == 0:
        return []
    client = anthropic.Anthropic(api_key=get_settings().anthropic_api_key)
    content: list[dict[str, object]] = [{"type": "text", "text": VISION_INSTRUCTION}]
    for body, media_type in payloads:
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64.b64encode(body).decode("ascii"),
                },
            }
        )
    message: anthropic.types.Message | None = None
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            message = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=1024,
                messages=[
                    {
                        "role": "user",
                        "content": cast(Any, content),
                    }
                ],
            )
            break
        except (anthropic.RateLimitError, anthropic.APIConnectionError) as exc:
            last_error = exc
            time.sleep(2**attempt)
        except anthropic.APIStatusError:
            logger.exception("Claude logo vision returned an API error")
            return [(None, None)] * len(payloads)
    if message is None:
        if last_error is not None:
            logger.error("Claude logo vision failed", exc_info=last_error)
        return [(None, None)] * len(payloads)
    parsed = parse_brand_json(_message_text(message.content))
    padded = list(parsed)
    while len(padded) < len(payloads):
        padded.append((None, None))
    return padded[: len(payloads)]


def parse_brand_json(text: str) -> list[tuple[str | None, float | None]]:
    data = _load_json_array(text)
    results: list[tuple[str | None, float | None]] = []
    for item in data:
        if item is None:
            results.append((None, None))
            continue
        if isinstance(item, str):
            brand = _string(item)
            results.append((brand, None))
            continue
        if not isinstance(item, dict):
            results.append((None, None))
            continue
        brand_raw = item.get("brand")
        if brand_raw is None:
            brand_raw = item.get("name")
        brand = _string(brand_raw)
        results.append((brand, _optional_float(item.get("confidence"))))
    return results


def search_places_for_brand(collector: BaseCollector, brand: str) -> list[dict[str, Any]]:
    settings = get_settings()
    search_url = settings.google_places_search_url.strip()
    api_key = settings.google_places_api_key.strip()
    if search_url == "" or api_key == "":
        logger.warning("Skipping Places brand resolve; Google Places settings are empty")
        return []
    payload = {"textQuery": brand, "pageSize": PLACES_PAGE_SIZE}
    headers = {
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": PLACES_FIELD_MASK,
    }
    body = collector.fetch_json_post(search_url, payload, extra_headers=headers)
    if body is None:
        return []
    rows = body.get("places")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def image_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 24:
        return None
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        width, height = struct.unpack(">II", data[16:24])
        return int(width), int(height)
    if data[:6] in {b"GIF87a", b"GIF89a"}:
        width, height = struct.unpack("<HH", data[6:10])
        return int(width), int(height)
    if data[:2] == b"\xff\xd8":
        return _jpeg_size(data)
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return _webp_size(data)
    return None


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            return None
        marker = data[index + 1]
        if marker in {0xC0, 0xC1, 0xC2}:
            height, width = struct.unpack(">HH", data[index + 5 : index + 9])
            return int(width), int(height)
        if marker == 0xD8:
            index += 2
            continue
        if index + 3 >= len(data):
            return None
        length = struct.unpack(">H", data[index + 2 : index + 4])[0]
        index += 2 + length
    return None


def _webp_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 30:
        return None
    kind = data[12:16]
    if kind == b"VP8X" and len(data) >= 30:
        width = 1 + int.from_bytes(data[24:27], "little")
        height = 1 + int.from_bytes(data[27:30], "little")
        return width, height
    if kind == b"VP8 " and len(data) >= 30:
        width = struct.unpack("<H", data[26:28])[0] & 0x3FFF
        height = struct.unpack("<H", data[28:30])[0] & 0x3FFF
        return width, height
    if kind == b"VP8L" and len(data) >= 25:
        bits = struct.unpack("<I", data[21:29][:4])[0]
        width = (bits & 0x3FFF) + 1
        height = ((bits >> 14) & 0x3FFF) + 1
        return width, height
    return None


def _organizations_with_websites() -> list[tuple[UUID, str]]:
    factory = get_session_factory()
    rows: list[tuple[UUID, str]] = []
    with factory() as session:
        result = session.execute(
            select(Organization.id, Organization.website).where(
                Organization.website.is_not(None),
                Organization.is_active.is_(True),
            )
        )
        for org_id, website in result.all():
            if isinstance(website, str) and website.strip() != "":
                rows.append((org_id, website.strip()))
    return rows


def _element_size(node: Any) -> tuple[int | None, int | None]:
    width = _dimension(node.attributes.get("width"))
    height = _dimension(node.attributes.get("height"))
    style = node.attributes.get("style")
    if isinstance(style, str):
        for match in _STYLE_PX.finditer(style):
            if match.group(1).lower() == "width" and width is None:
                width = _dimension(match.group(2))
            if match.group(1).lower() == "height" and height is None:
                height = _dimension(match.group(2))
    return width, height


def _dimension(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        stripped = value.strip().lower().removesuffix("px")
        try:
            return int(float(stripped))
        except ValueError:
            return None
    return None


def _passes_size_filter(width: int | None, height: int | None) -> bool:
    if width is None or height is None:
        return True
    return width > MIN_IMAGE_PX and height > MIN_IMAGE_PX


def _is_sponsor_path(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(key in path for key in _SPONSOR_PATH_KEYS)


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


def _origin(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _strip_fragment(url: str) -> str:
    return urlparse(url)._replace(fragment="").geturl()


def _media_type(content_type: str, data: bytes) -> str | None:
    lowered = content_type.lower().strip()
    if lowered in {"image/png", "image/jpeg", "image/gif", "image/webp"}:
        return lowered
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:2] == b"\xff\xd8":
        return "image/jpeg"
    if data[:6] in {b"GIF87a", b"GIF89a"}:
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


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


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return float(value)
    if isinstance(value, float):
        return value
    return None


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
    SponsorLogosCollector().run()


if __name__ == "__main__":
    main()
