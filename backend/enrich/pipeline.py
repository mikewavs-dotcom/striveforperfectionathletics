import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.compliance.minor_guard import is_minor_related
from backend.enrich.apollo import (
    ApolloClient,
    ApolloError,
    email_from_match,
    first_name_from_match,
    last_name_from_match,
    map_people,
    title_from_match,
)
from backend.enrich.hunter import HunterClient, HunterError, verification_score, verified_email
from backend.enrich.keys import is_configured
from backend.models import Contact, ContactRole, Organization

logger = logging.getLogger(__name__)

_DENIED_HOSTS = ("linkedin.com", "instagram.com", "facebook.com", "x.com")


class EnrichmentError(Exception):
    """Raised when Apollo or Hunter enrichment fails after being logged."""


@dataclass
class EnrichmentCounts:
    found: int = 0
    persisted: int = 0
    skipped_minor: int = 0
    skipped_unverified: int = 0
    skipped_no_people: int = 0


def enrichment_keys_configured(settings: object) -> bool:
    apollo = str(getattr(settings, "apollo_api_key", "") or "")
    hunter = str(getattr(settings, "hunter_api_key", "") or "")
    return is_configured(apollo) and is_configured(hunter)


def domain_from_website(website: str | None) -> str | None:
    host = _hostname(website)
    if host is None:
        return None
    if _is_denied_host(host):
        return None
    if host.startswith("www."):
        host = host[4:]
    return host or None


def enrich_organizations(
    session: Session,
    organization_ids: list[UUID],
    settings: object,
) -> EnrichmentCounts:
    counts = EnrichmentCounts()
    if not organization_ids:
        return counts
    if not enrichment_keys_configured(settings):
        raise EnrichmentError("Apollo and Hunter API keys are not configured")

    apollo_key = str(getattr(settings, "apollo_api_key", "") or "")
    hunter_key = str(getattr(settings, "hunter_api_key", "") or "")
    apollo_base = str(getattr(settings, "apollo_base_url", "") or "https://api.apollo.io")
    hunter_base = str(getattr(settings, "hunter_base_url", "") or "https://api.hunter.io")

    orgs = session.scalars(select(Organization).where(Organization.id.in_(organization_ids))).all()
    org_by_id = {org.id: org for org in orgs}
    existing_rows = session.scalars(
        select(Contact).where(Contact.organization_id.in_(organization_ids))
    ).all()
    contacts_by_org: dict[UUID, list[Contact]] = {org_id: [] for org_id in organization_ids}
    for contact in existing_rows:
        contacts_by_org.setdefault(contact.organization_id, []).append(contact)

    try:
        with (
            ApolloClient(api_key=apollo_key, base_url=apollo_base) as apollo,
            HunterClient(api_key=hunter_key, base_url=hunter_base) as hunter,
        ):
            for org_id in organization_ids:
                org = org_by_id.get(org_id)
                if org is None:
                    counts.skipped_no_people += 1
                    continue
                existing = contacts_by_org.get(org_id, [])
                _enrich_existing(session, org, existing, apollo, hunter, counts)
                _enrich_from_search(session, org, existing, apollo, hunter, counts)
    except (ApolloError, HunterError) as exc:
        raise EnrichmentError(str(exc)) from exc
    return counts


def _enrich_existing(
    session: Session,
    org: Organization,
    existing: list[Contact],
    apollo: ApolloClient,
    hunter: HunterClient,
    counts: EnrichmentCounts,
) -> None:
    domain = domain_from_website(org.website)
    for contact in existing:
        if (contact.email or "").strip() != "":
            continue
        title = contact.title_raw or contact.full_name or ""
        page_context = _page_context(contact.full_name, contact.title_raw)
        if contact.is_minor_related or is_minor_related(
            contact.source_url or org.website or "", title, page_context
        ):
            counts.skipped_minor += 1
            continue
        try:
            match = apollo.match_person(
                first_name=contact.first_name,
                last_name=contact.last_name,
                name=contact.full_name,
                organization_name=org.name,
                domain=domain,
            )
        except ApolloError:
            logger.exception("Apollo match failed for existing contact at %s", org.name)
            counts.skipped_unverified += 1
            continue
        email = email_from_match(match)
        if email is None:
            counts.skipped_unverified += 1
            continue
        _verify_and_persist(
            session,
            org,
            existing,
            hunter,
            counts,
            email=email,
            first_name=contact.first_name or first_name_from_match(match),
            last_name=contact.last_name or last_name_from_match(match),
            full_name=contact.full_name,
            title=contact.title_raw or title_from_match(match),
            source_url=contact.source_url or org.website,
        )


def _enrich_from_search(
    session: Session,
    org: Organization,
    existing: list[Contact],
    apollo: ApolloClient,
    hunter: HunterClient,
    counts: EnrichmentCounts,
) -> None:
    domain = domain_from_website(org.website)
    location = _location(org)
    try:
        payload = apollo.search_people(
            organization_name=org.name,
            domain=domain,
            location=location,
        )
    except ApolloError:
        logger.exception("Apollo search failed for %s", org.name)
        counts.skipped_no_people += 1
        return
    people = map_people(payload)
    if not people:
        counts.skipped_no_people += 1
        return
    counts.found += len(people)
    for person in people:
        first_name = _string(person.get("first_name"))
        last_name = _string(person.get("last_name"))
        full_name = _string(person.get("name")) or _join_name(first_name, last_name)
        title = _string(person.get("title"))
        page_context = _page_context(full_name, title)
        if is_minor_related(org.website or "", title or full_name or "", page_context):
            counts.skipped_minor += 1
            continue
        if _has_verified_email(existing, full_name, first_name, last_name):
            continue
        email = _string(person.get("email"))
        if email is None:
            person_id = person.get("id")
            try:
                match = apollo.match_person(
                    person_id=person_id if isinstance(person_id, str) else None,
                    first_name=first_name,
                    last_name=last_name,
                    name=full_name,
                    organization_name=org.name,
                    domain=domain,
                )
            except ApolloError:
                logger.exception("Apollo match failed for search hit at %s", org.name)
                counts.skipped_unverified += 1
                continue
            email = email_from_match(match)
            first_name = first_name or first_name_from_match(match)
            last_name = last_name or last_name_from_match(match)
            title = title or title_from_match(match)
            if full_name is None:
                full_name = _join_name(first_name, last_name)
        if email is None:
            counts.skipped_unverified += 1
            continue
        _verify_and_persist(
            session,
            org,
            existing,
            hunter,
            counts,
            email=email,
            first_name=first_name,
            last_name=last_name,
            full_name=full_name,
            title=title,
            source_url=org.website,
        )


def _verify_and_persist(
    session: Session,
    org: Organization,
    existing: list[Contact],
    hunter: HunterClient,
    counts: EnrichmentCounts,
    *,
    email: str,
    first_name: str | None,
    last_name: str | None,
    full_name: str | None,
    title: str | None,
    source_url: str | None,
) -> None:
    page_context = _page_context(full_name, title)
    if is_minor_related(source_url or org.website or "", title or full_name or "", page_context):
        counts.skipped_minor += 1
        return
    try:
        verification = hunter.verify_email(email)
    except HunterError:
        logger.exception("Hunter verify failed for organization %s", org.name)
        counts.skipped_unverified += 1
        return
    verified = verified_email(verification)
    if verified is None:
        counts.skipped_unverified += 1
        return
    score = verification_score(verification)
    confidence = (score / 100.0) if score is not None else None
    now = datetime.now(timezone.utc)
    contact = _upsert_contact(
        session,
        org,
        existing,
        email=verified,
        first_name=first_name,
        last_name=last_name,
        full_name=full_name,
        title=title,
        source_url=_safe_source_url(source_url, org.website),
        confidence=confidence,
        now=now,
    )
    if contact is not None:
        counts.persisted += 1


def _upsert_contact(
    session: Session,
    org: Organization,
    existing: list[Contact],
    *,
    email: str,
    first_name: str | None,
    last_name: str | None,
    full_name: str | None,
    title: str | None,
    source_url: str | None,
    confidence: float | None,
    now: datetime,
) -> Contact | None:
    resolved_name = full_name or _join_name(first_name, last_name)
    if resolved_name is None:
        return None
    match = _existing_contact(existing, resolved_name, first_name, last_name)
    role = _role_from_title(title)
    if match is not None:
        match.email = email
        match.first_name = first_name or match.first_name
        match.last_name = last_name or match.last_name
        match.full_name = resolved_name
        match.title_raw = title if title is not None else match.title_raw
        match.role = role
        match.confidence = confidence
        match.source_url = source_url or match.source_url
        match.is_minor_related = False
        match.last_verified_at = now
        return match
    contact = Contact(
        organization_id=org.id,
        full_name=resolved_name,
        first_name=first_name,
        last_name=last_name,
        title_raw=title,
        role=role,
        email=email,
        source_url=source_url,
        confidence=confidence,
        is_minor_related=False,
        first_seen_at=now,
        last_verified_at=now,
    )
    session.add(contact)
    existing.append(contact)
    return contact


def _existing_contact(
    existing: list[Contact],
    full_name: str,
    first_name: str | None,
    last_name: str | None,
) -> Contact | None:
    lowered = full_name.strip().lower()
    for contact in existing:
        if contact.full_name is not None and contact.full_name.strip().lower() == lowered:
            return contact
    if first_name and last_name:
        first = first_name.strip().lower()
        last = last_name.strip().lower()
        for contact in existing:
            if (
                contact.first_name is not None
                and contact.last_name is not None
                and contact.first_name.strip().lower() == first
                and contact.last_name.strip().lower() == last
            ):
                return contact
    return None


def _has_verified_email(
    existing: list[Contact],
    full_name: str | None,
    first_name: str | None,
    last_name: str | None,
) -> bool:
    if full_name is None and (first_name is None or last_name is None):
        return False
    match = _existing_contact(existing, full_name or "", first_name, last_name)
    if match is None:
        return False
    return (match.email or "").strip() != ""


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
    if "marketing" in lowered:
        return ContactRole.marketing_contact
    if compact in {"owner", "founder"}:
        return ContactRole.owner
    return ContactRole.unknown


def _location(org: Organization) -> str | None:
    city = (org.city or "").strip()
    state = (org.state or "").strip()
    if city != "" and state != "":
        return f"{city}, {state}"
    if state != "":
        return state
    if city != "":
        return city
    return None


def _page_context(*parts: str | None) -> str:
    return " ".join(part for part in parts if part)


def _join_name(first_name: str | None, last_name: str | None) -> str | None:
    parts = [part for part in (first_name, last_name) if part]
    if not parts:
        return None
    return " ".join(parts)


def _string(value: object) -> str | None:
    if isinstance(value, str) and value.strip() != "":
        return value.strip()
    return None


def _hostname(url: str | None) -> str | None:
    if url is None or url.strip() == "":
        return None
    raw = url.strip()
    if "://" not in raw:
        raw = f"https://{raw}"
    host = urlparse(raw).hostname
    if host is None or host.strip() == "":
        return None
    return host.lower()


def _is_denied_host(host: str) -> bool:
    for denied in _DENIED_HOSTS:
        if host == denied or host.endswith(f".{denied}"):
            return True
    return False


def _safe_source_url(url: str | None, fallback: str | None) -> str | None:
    for candidate in (url, fallback):
        host = _hostname(candidate)
        if host is None or _is_denied_host(host):
            continue
        return candidate
    return None
