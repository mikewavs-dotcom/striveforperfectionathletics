import logging
from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.db import get_session_factory
from backend.compliance.audit import log_fetch
from backend.compliance.ratelimit import RateLimiter, user_agent
from backend.compliance.robots import RobotsGate, ensure_allowed_domain, raise_if_denylisted
from backend.models import Contact, Organization, PolicyEvent, SourceRun, SourceRunStatus, Sponsor

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    def __init__(self, *, requests_per_second: float = 1.0) -> None:
        self._robots = RobotsGate()
        self._limiter = RateLimiter(requests_per_second=requests_per_second)
        self._client = httpx.Client(
            headers={"User-Agent": user_agent()},
            timeout=30.0,
            follow_redirects=True,
        )
        self._pages_fetched = 0

    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def allowed_domains(self) -> Sequence[str]:
        raise NotImplementedError

    @abstractmethod
    def fetch(self) -> object:
        raise NotImplementedError

    @abstractmethod
    def parse(self, raw: object) -> object:
        raise NotImplementedError

    @abstractmethod
    def to_records(self, parsed: object) -> Sequence[Organization | Contact | PolicyEvent | Sponsor]:
        raise NotImplementedError

    def close(self) -> None:
        self._client.close()

    def run(self, run_id: UUID | None = None) -> UUID:
        started_at = datetime.now(timezone.utc)
        factory = get_session_factory()
        if run_id is None:
            run_id = self._start_run(factory, started_at)
        status = SourceRunStatus.failed
        error_message: str | None = None
        records_found = 0
        records_new = 0
        records_updated = 0
        try:
            raw = self.fetch()
            parsed = self.parse(raw)
            records = self.to_records(parsed)
            records_found, records_new, records_updated = self._persist(records)
            status = SourceRunStatus.success
        except Exception as exc:
            logger.exception("Collector %s failed", self.name)
            status = SourceRunStatus.failed
            error_message = str(exc)
        finally:
            self._finish_run(
                factory,
                run_id,
                status=status,
                error_message=error_message,
                records_found=records_found,
                records_new=records_new,
                records_updated=records_updated,
            )
            self.close()
        return run_id

    def fetch_json(
        self, url: str, params: dict[str, str | int] | None = None
    ) -> dict[str, Any] | None:
        request_url = str(httpx.URL(url, params=params))
        ensure_allowed_domain(request_url, self.allowed_domains)
        if not self._robots.allowed(request_url):
            return None
        last_response: httpx.Response | None = None
        for _attempt in range(5):
            self._limiter.acquire(request_url)
            response = self._client.get(url, params=params)
            self._pages_fetched += 1
            raise_if_denylisted(str(response.url))
            log_fetch(
                actor=self.name,
                action="fetch",
                target_url=str(response.url),
                robots_allowed=True,
                response_code=response.status_code,
            )
            last_response = response
            if response.status_code in (429, 503):
                self._limiter.wait_if_throttled(request_url, response.status_code)
                continue
            self._limiter.wait_if_throttled(request_url, response.status_code)
            if response.status_code in (400, 404):
                return None
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                return None
            return payload
        if last_response is not None:
            last_response.raise_for_status()
        return None

    def fetch_json_post(
        self,
        url: str,
        payload: dict[str, Any],
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any] | None:
        ensure_allowed_domain(url, self.allowed_domains)
        if not self._robots.allowed(url):
            return None
        headers = dict(extra_headers or {})
        last_response: httpx.Response | None = None
        for _attempt in range(5):
            self._limiter.acquire(url)
            response = self._client.post(url, json=payload, headers=headers)
            self._pages_fetched += 1
            raise_if_denylisted(str(response.url))
            log_fetch(
                actor=self.name,
                action="fetch",
                target_url=str(response.url),
                robots_allowed=True,
                response_code=response.status_code,
            )
            last_response = response
            if response.status_code in (429, 503):
                self._limiter.wait_if_throttled(url, response.status_code)
                continue
            self._limiter.wait_if_throttled(url, response.status_code)
            if response.status_code in (400, 404):
                return None
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict):
                return None
            return body
        if last_response is not None:
            last_response.raise_for_status()
        return None

    def fetch_html(self, url: str) -> str | None:
        ensure_allowed_domain(url, self.allowed_domains)
        if not self._robots.allowed(url):
            return None
        last_response: httpx.Response | None = None
        for _attempt in range(5):
            self._limiter.acquire(url)
            response = self._client.get(url)
            self._pages_fetched += 1
            raise_if_denylisted(str(response.url))
            log_fetch(
                actor=self.name,
                action="fetch",
                target_url=str(response.url),
                robots_allowed=True,
                response_code=response.status_code,
            )
            last_response = response
            if response.status_code in (429, 503):
                self._limiter.wait_if_throttled(url, response.status_code)
                continue
            self._limiter.wait_if_throttled(url, response.status_code)
            if response.status_code in (400, 404):
                return None
            response.raise_for_status()
            return response.text
        if last_response is not None:
            last_response.raise_for_status()
        return None

    def fetch_bytes(self, url: str) -> tuple[bytes, str] | None:
        ensure_allowed_domain(url, self.allowed_domains)
        if not self._robots.allowed(url):
            return None
        last_response: httpx.Response | None = None
        for _attempt in range(5):
            self._limiter.acquire(url)
            response = self._client.get(url)
            self._pages_fetched += 1
            raise_if_denylisted(str(response.url))
            log_fetch(
                actor=self.name,
                action="fetch",
                target_url=str(response.url),
                robots_allowed=True,
                response_code=response.status_code,
            )
            last_response = response
            if response.status_code in (429, 503):
                self._limiter.wait_if_throttled(url, response.status_code)
                continue
            self._limiter.wait_if_throttled(url, response.status_code)
            if response.status_code in (400, 404):
                return None
            response.raise_for_status()
            content_type = (response.headers.get("content-type") or "").split(";")[0].strip()
            return response.content, content_type
        if last_response is not None:
            last_response.raise_for_status()
        return None

    def _start_run(self, factory: sessionmaker[Session], started_at: datetime) -> UUID:
        with factory() as session:
            run = SourceRun(
                collector_name=self.name,
                started_at=started_at,
                status=SourceRunStatus.partial,
                pages_fetched=0,
            )
            session.add(run)
            session.commit()
            session.refresh(run)
            return run.id

    def _finish_run(
        self,
        factory: sessionmaker[Session],
        run_id: UUID,
        *,
        status: SourceRunStatus,
        error_message: str | None,
        records_found: int,
        records_new: int,
        records_updated: int,
    ) -> None:
        with factory() as session:
            run = session.get(SourceRun, run_id)
            if run is None:
                return
            run.finished_at = datetime.now(timezone.utc)
            run.status = status
            run.error_message = error_message
            run.records_found = records_found
            run.records_new = records_new
            run.records_updated = records_updated
            run.pages_fetched = self._pages_fetched
            session.commit()

    def _persist(
        self, records: Sequence[Organization | Contact | PolicyEvent | Sponsor]
    ) -> tuple[int, int, int]:
        factory = get_session_factory()
        records_new = 0
        records_updated = 0
        org_count = 0
        policy_count = 0
        sponsor_count = 0
        now = datetime.now(timezone.utc)
        current_org_id: UUID | None = None
        id_map: dict[UUID, UUID] = {}
        with factory() as session:
            for record in records:
                if isinstance(record, PolicyEvent):
                    policy_count += 1
                    session.add(record)
                    records_new += 1
                    continue
                if isinstance(record, Organization):
                    org_count += 1
                    original_id = record.id
                    persisted_id, created = self._upsert_organization(session, record, now)
                    current_org_id = persisted_id
                    if original_id is not None and persisted_id is not None:
                        id_map[original_id] = persisted_id
                    if created:
                        records_new += 1
                    else:
                        records_updated += 1
                    continue
                if isinstance(record, Contact) and current_org_id is not None:
                    self._upsert_contact(session, current_org_id, record, now)
                    continue
                if isinstance(record, Sponsor):
                    sponsor_count += 1
                    matched = record.matched_organization_id
                    if matched is not None and matched in id_map:
                        record.matched_organization_id = id_map[matched]
                    created = self._upsert_sponsor(session, record, now)
                    if created:
                        records_new += 1
                    else:
                        records_updated += 1
            session.commit()
        return (org_count + policy_count + sponsor_count, records_new, records_updated)

    def _upsert_organization(
        self, session: Session, org: Organization, now: datetime
    ) -> tuple[UUID | None, bool]:
        existing: Organization | None = None
        if org.ein is not None:
            existing = session.scalar(select(Organization).where(Organization.ein == org.ein))
        if existing is None and org.google_place_id is not None:
            existing = session.scalar(
                select(Organization).where(Organization.google_place_id == org.google_place_id)
            )
        if existing is None and org.website is not None:
            existing = session.scalar(select(Organization).where(Organization.website == org.website))
        if existing is None:
            org.first_seen_at = now
            org.last_verified_at = now
            session.add(org)
            session.flush()
            return org.id, True
        existing.name = org.name
        existing.org_type = org.org_type
        existing.city = org.city
        existing.state = org.state
        existing.ein = org.ein or existing.ein
        existing.website = org.website or existing.website
        existing.phone = org.phone or existing.phone
        existing.street = org.street or existing.street
        existing.postal_code = org.postal_code or existing.postal_code
        existing.annual_revenue = org.annual_revenue
        existing.program_expenses = org.program_expenses
        existing.fiscal_year = org.fiscal_year
        existing.google_place_id = org.google_place_id or existing.google_place_id
        if org.google_rating is not None:
            existing.google_rating = org.google_rating
        if org.google_review_count is not None:
            existing.google_review_count = org.google_review_count
        if org.roster_size_estimate is not None:
            existing.roster_size_estimate = org.roster_size_estimate
        if org.events_per_year is not None:
            existing.events_per_year = org.events_per_year
        if org.location_count is not None:
            existing.location_count = org.location_count
        existing.last_verified_at = now
        source_urls = list(existing.source_urls or [])
        for url in org.source_urls or []:
            if url not in source_urls:
                source_urls.append(url)
        existing.source_urls = source_urls or None
        session.flush()
        return existing.id, False

    def _upsert_contact(
        self, session: Session, organization_id: UUID, contact: Contact, now: datetime
    ) -> None:
        existing: Contact | None = None
        if contact.full_name is not None:
            existing = session.scalar(
                select(Contact).where(
                    Contact.organization_id == organization_id,
                    Contact.full_name == contact.full_name,
                )
            )
        if existing is not None:
            existing.title_raw = contact.title_raw
            existing.role = contact.role
            existing.confidence = contact.confidence
            existing.source_url = contact.source_url
            existing.is_minor_related = contact.is_minor_related
            existing.last_verified_at = now
            return
        contact.organization_id = organization_id
        contact.first_seen_at = now
        contact.last_verified_at = now
        session.add(contact)

    def _upsert_sponsor(self, session: Session, sponsor: Sponsor, now: datetime) -> bool:
        existing: Sponsor | None = None
        if sponsor.detected_on_organization_id is not None:
            existing = session.scalar(
                select(Sponsor).where(
                    Sponsor.brand_name == sponsor.brand_name,
                    Sponsor.detected_on_organization_id == sponsor.detected_on_organization_id,
                )
            )
        if existing is None:
            session.add(sponsor)
            session.flush()
            return True
        existing.detected_on_url = sponsor.detected_on_url
        existing.logo_image_url = sponsor.logo_image_url or existing.logo_image_url
        existing.extraction_confidence = sponsor.extraction_confidence
        existing.matched_organization_id = (
            sponsor.matched_organization_id or existing.matched_organization_id
        )
        existing.detected_at = sponsor.detected_at or now
        return False
