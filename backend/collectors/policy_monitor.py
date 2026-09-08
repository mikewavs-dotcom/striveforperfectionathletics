import hashlib
import json
import logging
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import anthropic
from selectolax.parser import HTMLParser
from sqlalchemy import select

from backend.app.config import get_settings
from backend.app.db import get_session_factory
from backend.collectors.base import BaseCollector
from backend.compliance.robots import hostname_of
from backend.models import PolicyEvent, PolicyEventType

logger = logging.getLogger(__name__)

CLAUDE_MODEL = "claude-sonnet-4-6"
COMPARE_INSTRUCTION = (
    "Compare these two versions of a page. In under 60 words, state what "
    "substantively changed regarding NIL policy, athlete eligibility, or "
    "compliance requirements. If nothing substantive changed, respond with "
    "exactly NO_CHANGE."
)
_TEXT_CAP = 12000
_MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|November|December"
)
_EFFECTIVE_DATE = re.compile(
    rf"effective(?:\s+date)?[:\s]+((?:{_MONTHS})\s+\d{{1,2}},\s*\d{{4}}|\d{{4}}-\d{{2}}-\d{{2}})",
    re.IGNORECASE,
)
_NO_CHANGE = re.compile(r"^NO_CHANGE\.?$", re.IGNORECASE)


@dataclass(frozen=True)
class WatchEntry:
    jurisdiction: str
    url: str
    category: str


@dataclass(frozen=True)
class StoredSnapshot:
    content_hash: str
    text: str


@dataclass(frozen=True)
class ParsedPage:
    jurisdiction: str
    url: str
    category: str
    text: str
    content_hash: str
    previous_hash: str | None
    previous_text: str | None


def load_watchlist(path: Path) -> list[WatchEntry]:
    entries: list[WatchEntry] = []
    current: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if stripped == "" or stripped.startswith("#"):
            continue
        if stripped.startswith("- "):
            if current:
                entries.append(_watch_entry(current))
                current = {}
            stripped = stripped[2:].strip()
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        current[key.strip()] = value.strip().strip("\"'")
    if current:
        entries.append(_watch_entry(current))
    return entries


def extract_main_text(html: str) -> str:
    tree = HTMLParser(html)
    for node in tree.css("script, style, noscript"):
        node.decompose()
    root = tree.css_first("main, article, [role=main]")
    if root is None:
        root = tree.body
    if root is None:
        return ""
    return root.text(separator=" ", strip=True)


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


class PolicyMonitorCollector(BaseCollector):
    def __init__(self) -> None:
        super().__init__(requests_per_second=1.0)

    @property
    def name(self) -> str:
        return "policy_monitor"

    @property
    def allowed_domains(self) -> Sequence[str]:
        path = _resolved(get_settings().watchlist_path)
        if not path.is_file():
            return ()
        return tuple(sorted({hostname_of(entry.url) for entry in load_watchlist(path)}))

    def fetch(self) -> dict[str, Any]:
        settings = get_settings()
        watchlist = load_watchlist(_resolved(settings.watchlist_path))
        snapshots = _load_snapshots(_resolved(settings.watchlist_hashes_path))
        for url, digest in _hashes_from_events().items():
            if url not in snapshots:
                snapshots[url] = StoredSnapshot(content_hash=digest, text="")
        pages: list[dict[str, str]] = []
        for entry in watchlist:
            try:
                html = self.fetch_html(entry.url)
            except Exception:
                logger.exception("Policy monitor failed to fetch %s", entry.url)
                continue
            if html is None:
                continue
            pages.append(
                {
                    "jurisdiction": entry.jurisdiction,
                    "url": entry.url,
                    "category": entry.category,
                    "html": html,
                }
            )
        return {
            "pages": pages,
            "snapshots": {
                url: {"hash": snap.content_hash, "text": snap.text}
                for url, snap in snapshots.items()
            },
        }

    def parse(self, raw: object) -> list[ParsedPage]:
        if not isinstance(raw, dict):
            return []
        pages = raw.get("pages")
        snapshots_raw = raw.get("snapshots")
        if not isinstance(pages, list) or not isinstance(snapshots_raw, dict):
            return []
        snapshots = _snapshots_from_payload(snapshots_raw)
        parsed: list[ParsedPage] = []
        for page in pages:
            if not isinstance(page, dict):
                continue
            html = page.get("html")
            url = page.get("url")
            jurisdiction = page.get("jurisdiction")
            category = page.get("category")
            if not isinstance(html, str) or not isinstance(url, str):
                continue
            if not isinstance(jurisdiction, str) or not isinstance(category, str):
                continue
            text = normalize_text(extract_main_text(html))
            digest = content_hash(text)
            previous = snapshots.get(url)
            parsed.append(
                ParsedPage(
                    jurisdiction=jurisdiction,
                    url=url,
                    category=category,
                    text=text,
                    content_hash=digest,
                    previous_hash=None if previous is None else previous.content_hash,
                    previous_text=None if previous is None else previous.text,
                )
            )
        return parsed

    def to_records(self, parsed: object) -> Sequence[PolicyEvent]:
        if not isinstance(parsed, list):
            return []
        settings = get_settings()
        snapshots = _load_snapshots(_resolved(settings.watchlist_hashes_path))
        records: list[PolicyEvent] = []
        now = datetime.now(timezone.utc)
        for page in parsed:
            if not isinstance(page, ParsedPage):
                continue
            snapshots[page.url] = StoredSnapshot(content_hash=page.content_hash, text=page.text)
            if page.previous_hash is None:
                logger.info(
                    "FIRST RUN for %s: establishing baseline content hash. "
                    "No policy events generated.",
                    page.url,
                )
                continue
            if page.previous_hash == page.content_hash:
                continue
            previous_text = page.previous_text or ""
            summary = compare_versions(previous_text, page.text)
            if _is_no_change(summary):
                logger.info("NO_CHANGE for %s; no policy event written.", page.url)
                continue
            event = PolicyEvent(
                jurisdiction=page.jurisdiction,
                source_url=page.url,
                event_type=classify_event_type(summary, page.text),
                detected_at=now,
                effective_date=_extract_effective_date(f"{summary} {page.text}"),
                summary=summary[:400],
                content_hash=page.content_hash,
                linked_organization_id=None,
            )
            records.append(event)
        _save_snapshots(_resolved(settings.watchlist_hashes_path), snapshots)
        return records


def compare_versions(previous_text: str, new_text: str) -> str:
    client = anthropic.Anthropic(api_key=get_settings().anthropic_api_key)
    prompt = (
        f"{COMPARE_INSTRUCTION}\n\nPREVIOUS:\n{previous_text[:_TEXT_CAP]}\n\n"
        f"NEW:\n{new_text[:_TEXT_CAP]}"
    )
    message: anthropic.types.Message | None = None
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            message = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=150,
                messages=[{"role": "user", "content": prompt}],
            )
            break
        except (anthropic.RateLimitError, anthropic.APIConnectionError) as exc:
            last_error = exc
            time.sleep(2**attempt)
    if message is None:
        if last_error is not None:
            raise last_error
        raise RuntimeError("Claude policy compare request failed")
    return _message_text(message.content)


def classify_event_type(summary: str, text: str) -> PolicyEventType:
    blob = f"{summary} {text}".lower()
    if any(word in blob for word in ("meeting", "hearing", "agenda", "scheduled")):
        return PolicyEventType.meeting_scheduled
    if any(word in blob for word in ("guidance", "faq", "advisory")):
        return PolicyEventType.guidance_issued
    if any(word in blob for word in ("adopted", "enacted", "passed")):
        return PolicyEventType.policy_adopted
    return PolicyEventType.policy_amended


def _extract_effective_date(text: str) -> date | None:
    match = _EFFECTIVE_DATE.search(text)
    if match is None:
        return None
    raw = re.sub(r"\s+", " ", match.group(1)).strip()
    for fmt in ("%B %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _is_no_change(summary: str) -> bool:
    return _NO_CHANGE.fullmatch(summary.strip()) is not None


def _message_text(content: Sequence[object]) -> str:
    parts: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
    return " ".join(parts).strip()


def _resolved(path: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        return Path.cwd() / candidate
    return candidate


def _watch_entry(values: Mapping[str, str]) -> WatchEntry:
    return WatchEntry(
        jurisdiction=values["jurisdiction"],
        url=values["url"],
        category=values["category"],
    )


def _snapshots_from_payload(raw: Mapping[object, object]) -> dict[str, StoredSnapshot]:
    snapshots: dict[str, StoredSnapshot] = {}
    for key, value in raw.items():
        url = str(key)
        if isinstance(value, dict):
            digest = value.get("hash")
            text = value.get("text")
            if isinstance(digest, str) and isinstance(text, str):
                snapshots[url] = StoredSnapshot(content_hash=digest, text=text)
    return snapshots


def _load_snapshots(path: Path) -> dict[str, StoredSnapshot]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {}
    return _snapshots_from_payload(payload)


def _save_snapshots(path: Path, snapshots: Mapping[str, StoredSnapshot]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        url: {"hash": snap.content_hash, "text": snap.text}
        for url, snap in snapshots.items()
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _hashes_from_events() -> dict[str, str]:
    factory = get_session_factory()
    hashes: dict[str, str] = {}
    with factory() as session:
        rows = session.execute(
            select(PolicyEvent.source_url, PolicyEvent.content_hash, PolicyEvent.detected_at).order_by(
                PolicyEvent.detected_at.asc()
            )
        ).all()
    for url, digest, _detected in rows:
        hashes[url] = digest
    return hashes
