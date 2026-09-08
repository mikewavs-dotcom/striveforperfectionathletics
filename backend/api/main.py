import csv
import io
import logging
import threading
from collections.abc import Generator, Sequence
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import Select, asc, desc, exists, func, select
from sqlalchemy.orm import Session, aliased

from backend.app.db import get_session_factory
from backend.collectors.base import BaseCollector
from backend.collectors.nonprofit_990 import Nonprofit990Collector
from backend.collectors.policy_monitor import PolicyMonitorCollector
from backend.collectors.staff_directory import StaffDirectoryCollector
from backend.collectors.sponsor_logos import SponsorLogosCollector
from backend.collectors.youth_orgs import YouthOrgsCollector
from backend.compliance.minor_guard import is_minor_related
from backend.models import (
    Contact,
    ContactRole,
    Offer,
    Organization,
    OrgType,
    PolicyEvent,
    Score,
    SourceRun,
    SourceRunStatus,
    Sponsor,
)
from backend.schemas import (
    ContactSchema,
    OrganizationSchema,
    PolicyEventSchema,
    ScoreSchema,
    SourceRunSchema,
    SponsorSchema,
)

logger = logging.getLogger(__name__)

PAGE_SIZE = 50
COLLECTORS: dict[str, type[BaseCollector]] = {
    "nonprofit_990": Nonprofit990Collector,
    "policy_monitor": PolicyMonitorCollector,
    "youth_orgs": YouthOrgsCollector,
    "sponsor_logos": SponsorLogosCollector,
    "staff_directory": StaffDirectoryCollector,
}

SortField = Literal[
    "name",
    "state",
    "city",
    "created_at",
    "last_verified",
    "camps_score",
    "panels_score",
    "media_score",
]
SortDir = Literal["asc", "desc"]

_ROLE_PRIORITY: dict[ContactRole | None, int] = {
    ContactRole.athletic_director: 0,
    ContactRole.executive_director: 1,
    ContactRole.marketing_contact: 2,
    ContactRole.owner: 3,
    ContactRole.board_officer: 4,
    ContactRole.compliance_officer: 5,
    ContactRole.head_coach: 6,
    ContactRole.assistant_coach: 7,
    ContactRole.unknown: 8,
    None: 9,
}

app = FastAPI(title="Prospect Playground")


class OrganizationOfferScores(BaseModel):
    camps: int | None = None
    panels: int | None = None
    media: int | None = None


class OrganizationListItem(OrganizationSchema):
    scores: OrganizationOfferScores
    top_contact: ContactSchema | None


class PaginatedOrganizations(BaseModel):
    items: list[OrganizationListItem]
    page: int
    page_size: int
    total: int


class OrganizationDetail(OrganizationSchema):
    contacts: list[ContactSchema]
    scores: list[ScoreSchema]
    policy_events: list[PolicyEventSchema]
    sponsors: list[SponsorSchema]


class PaginatedPolicyEvents(BaseModel):
    items: list[PolicyEventSchema]
    page: int
    page_size: int
    total: int


class CollectorWithRuns(BaseModel):
    name: str
    runs: list[SourceRunSchema]


class CollectorRunAccepted(BaseModel):
    run_id: UUID


class DashboardStats(BaseModel):
    organization_count: int
    contact_count: int
    new_records_last_30_days: int
    policy_event_count: int


def get_session() -> Generator[Session, None, None]:
    factory = get_session_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()


def _visible_contacts(contacts: Sequence[Contact]) -> list[Contact]:
    return [contact for contact in contacts if not contact.is_minor_related]


def _top_contact(contacts: Sequence[Contact]) -> Contact | None:
    eligible = _visible_contacts(contacts)
    if not eligible:
        return None

    def sort_key(contact: Contact) -> tuple[int, float, int]:
        has_email = 0 if contact.email else 1
        confidence = -(contact.confidence if contact.confidence is not None else -1.0)
        role_rank = _ROLE_PRIORITY.get(contact.role, 9)
        return (has_email, confidence, role_rank)

    return sorted(eligible, key=sort_key)[0]


def _scores_map(rows: Sequence[Score]) -> OrganizationOfferScores:
    values: dict[Offer, int] = {}
    for row in rows:
        values[row.offer] = row.score
    return OrganizationOfferScores(
        camps=values.get(Offer.camps),
        panels=values.get(Offer.panels),
        media=values.get(Offer.media),
    )


def _contact_blocked_for_export(contact: Contact) -> bool:
    title = contact.title_raw or contact.full_name or ""
    page_context = " ".join(
        part
        for part in (contact.full_name, contact.title_raw, contact.first_name, contact.last_name)
        if part
    )
    flagged = is_minor_related(contact.source_url or "", title, page_context)
    return contact.is_minor_related or flagged


def _filtered_organizations(
    *,
    org_types: Sequence[OrgType] | None,
    state: str | None,
    min_camps_score: int | None,
    min_panels_score: int | None,
    min_media_score: int | None,
    has_email: bool | None,
    search: str | None,
) -> tuple[
    Select[tuple[Organization]],
    Select[tuple[int]],
    type[Score],
    type[Score],
    type[Score],
]:
    camps = aliased(Score)
    panels = aliased(Score)
    media = aliased(Score)
    stmt = (
        select(Organization)
        .outerjoin(
            camps,
            (camps.organization_id == Organization.id) & (camps.offer == Offer.camps),
        )
        .outerjoin(
            panels,
            (panels.organization_id == Organization.id) & (panels.offer == Offer.panels),
        )
        .outerjoin(
            media,
            (media.organization_id == Organization.id) & (media.offer == Offer.media),
        )
    )
    if org_types:
        stmt = stmt.where(Organization.org_type.in_(org_types))
    if state is not None and state.strip() != "":
        stmt = stmt.where(Organization.state == state)
    if min_camps_score is not None:
        stmt = stmt.where(camps.score >= min_camps_score)
    if min_panels_score is not None:
        stmt = stmt.where(panels.score >= min_panels_score)
    if min_media_score is not None:
        stmt = stmt.where(media.score >= min_media_score)
    if search is not None and search.strip() != "":
        stmt = stmt.where(Organization.name.ilike(f"%{search.strip()}%"))
    if has_email is not None:
        email_exists = exists(
            select(Contact.id).where(
                Contact.organization_id == Organization.id,
                Contact.is_minor_related.is_(False),
                Contact.email.is_not(None),
                Contact.email != "",
            )
        )
        stmt = stmt.where(email_exists if has_email else ~email_exists)
    count_stmt = select(func.count()).select_from(
        stmt.with_only_columns(Organization.id, maintain_column_froms=True)
        .distinct()
        .order_by(None)
        .subquery()
    )
    return stmt, count_stmt, camps, panels, media


def _apply_sort(
    stmt: Select[tuple[Organization]],
    sort_by: SortField,
    sort_dir: SortDir,
    camps: type[Score],
    panels: type[Score],
    media: type[Score],
) -> Select[tuple[Organization]]:
    direction = desc if sort_dir == "desc" else asc
    columns = {
        "name": Organization.name,
        "state": Organization.state,
        "city": Organization.city,
        "created_at": Organization.created_at,
        "last_verified": Organization.last_verified_at,
        "camps_score": camps.score,
        "panels_score": panels.score,
        "media_score": media.score,
    }
    return stmt.order_by(direction(columns[sort_by]).nulls_last(), Organization.id)


def _list_item(org: Organization, scores: Sequence[Score], contacts: Sequence[Contact]) -> OrganizationListItem:
    base = OrganizationSchema.model_validate(org)
    top = _top_contact(contacts)
    return OrganizationListItem(
        **base.model_dump(),
        scores=_scores_map(scores),
        top_contact=ContactSchema.model_validate(top) if top is not None else None,
    )


def _load_scores_by_org(session: Session, org_ids: Sequence[UUID]) -> dict[UUID, list[Score]]:
    if not org_ids:
        return {}
    rows = session.scalars(select(Score).where(Score.organization_id.in_(org_ids))).all()
    grouped: dict[UUID, list[Score]] = {org_id: [] for org_id in org_ids}
    for row in rows:
        grouped.setdefault(row.organization_id, []).append(row)
    return grouped


def _load_contacts_by_org(session: Session, org_ids: Sequence[UUID]) -> dict[UUID, list[Contact]]:
    if not org_ids:
        return {}
    rows = session.scalars(
        select(Contact).where(
            Contact.organization_id.in_(org_ids),
            Contact.is_minor_related.is_(False),
        )
    ).all()
    grouped: dict[UUID, list[Contact]] = {org_id: [] for org_id in org_ids}
    for row in rows:
        grouped.setdefault(row.organization_id, []).append(row)
    return grouped


def _run_collector(collector_name: str, run_id: UUID) -> None:
    collector_cls = COLLECTORS[collector_name]
    collector = collector_cls()
    try:
        collector.run(run_id=run_id)
    except Exception:
        logger.exception("Manual run of collector %s failed", collector_name)


@app.get("/organizations", response_model=PaginatedOrganizations)
def list_organizations(
    session: Annotated[Session, Depends(get_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    org_type: Annotated[list[OrgType] | None, Query()] = None,
    state: str | None = None,
    min_camps_score: Annotated[int | None, Query(ge=0, le=100)] = None,
    min_panels_score: Annotated[int | None, Query(ge=0, le=100)] = None,
    min_media_score: Annotated[int | None, Query(ge=0, le=100)] = None,
    has_email: bool | None = None,
    search: str | None = None,
    sort_by: SortField = "name",
    sort_dir: SortDir = "asc",
) -> PaginatedOrganizations:
    stmt, count_stmt, camps, panels, media = _filtered_organizations(
        org_types=org_type,
        state=state,
        min_camps_score=min_camps_score,
        min_panels_score=min_panels_score,
        min_media_score=min_media_score,
        has_email=has_email,
        search=search,
    )
    total = int(session.scalar(count_stmt) or 0)
    stmt = _apply_sort(stmt, sort_by, sort_dir, camps, panels, media)
    orgs = session.scalars(stmt.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)).all()
    org_ids = [org.id for org in orgs]
    scores = _load_scores_by_org(session, org_ids)
    contacts = _load_contacts_by_org(session, org_ids)
    return PaginatedOrganizations(
        items=[_list_item(org, scores.get(org.id, []), contacts.get(org.id, [])) for org in orgs],
        page=page,
        page_size=PAGE_SIZE,
        total=total,
    )


@app.get("/organizations/{organization_id}", response_model=OrganizationDetail)
def get_organization(
    organization_id: UUID,
    session: Annotated[Session, Depends(get_session)],
) -> OrganizationDetail:
    org = session.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    contacts = session.scalars(
        select(Contact).where(
            Contact.organization_id == org.id,
            Contact.is_minor_related.is_(False),
        )
    ).all()
    scores = session.scalars(select(Score).where(Score.organization_id == org.id)).all()
    policy_events = session.scalars(
        select(PolicyEvent)
        .where(PolicyEvent.linked_organization_id == org.id)
        .order_by(PolicyEvent.detected_at.desc())
    ).all()
    sponsors = session.scalars(
        select(Sponsor)
        .where(
            (Sponsor.detected_on_organization_id == org.id)
            | (Sponsor.matched_organization_id == org.id)
        )
        .order_by(Sponsor.detected_at.desc())
    ).all()
    base = OrganizationSchema.model_validate(org)
    return OrganizationDetail(
        **base.model_dump(),
        contacts=[ContactSchema.model_validate(contact) for contact in contacts],
        scores=[ScoreSchema.model_validate(score) for score in scores],
        policy_events=[PolicyEventSchema.model_validate(event) for event in policy_events],
        sponsors=[SponsorSchema.model_validate(sponsor) for sponsor in sponsors],
    )


@app.get("/stats", response_model=DashboardStats)
def get_stats(session: Annotated[Session, Depends(get_session)]) -> DashboardStats:
    organization_count = int(session.scalar(select(func.count()).select_from(Organization)) or 0)
    contact_count = int(session.scalar(select(func.count()).select_from(Contact)) or 0)
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    new_records = session.scalar(
        select(func.coalesce(func.sum(SourceRun.records_new), 0)).where(SourceRun.started_at >= cutoff)
    )
    policy_event_count = int(session.scalar(select(func.count()).select_from(PolicyEvent)) or 0)
    return DashboardStats(
        organization_count=organization_count,
        contact_count=contact_count,
        new_records_last_30_days=int(new_records or 0),
        policy_event_count=policy_event_count,
    )


@app.get("/sources", response_model=list[CollectorWithRuns])
def list_sources(session: Annotated[Session, Depends(get_session)]) -> list[CollectorWithRuns]:
    db_names = list(session.scalars(select(SourceRun.collector_name).distinct()))
    names = sorted(set(COLLECTORS) | set(db_names))
    result: list[CollectorWithRuns] = []
    for name in names:
        runs = session.scalars(
            select(SourceRun)
            .where(SourceRun.collector_name == name)
            .order_by(SourceRun.started_at.desc())
            .limit(10)
        ).all()
        result.append(
            CollectorWithRuns(
                name=name,
                runs=[SourceRunSchema.model_validate(run) for run in runs],
            )
        )
    return result


@app.post("/sources/{collector_name}/run", response_model=CollectorRunAccepted)
def trigger_source_run(
    collector_name: str,
    session: Annotated[Session, Depends(get_session)],
) -> CollectorRunAccepted:
    if collector_name not in COLLECTORS:
        raise HTTPException(status_code=404, detail="Unknown collector")
    run = SourceRun(
        collector_name=collector_name,
        started_at=datetime.now(timezone.utc),
        status=SourceRunStatus.partial,
        pages_fetched=0,
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    thread = threading.Thread(
        target=_run_collector,
        args=(collector_name, run.id),
        daemon=True,
        name=f"collector-{collector_name}-{run.id}",
    )
    thread.start()
    return CollectorRunAccepted(run_id=run.id)


@app.get("/policy-events", response_model=PaginatedPolicyEvents)
def list_policy_events(
    session: Annotated[Session, Depends(get_session)],
    page: Annotated[int, Query(ge=1)] = 1,
) -> PaginatedPolicyEvents:
    total = int(session.scalar(select(func.count()).select_from(PolicyEvent)) or 0)
    rows = session.scalars(
        select(PolicyEvent)
        .order_by(PolicyEvent.detected_at.desc(), PolicyEvent.id)
        .offset((page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
    ).all()
    return PaginatedPolicyEvents(
        items=[PolicyEventSchema.model_validate(event) for event in rows],
        page=page,
        page_size=PAGE_SIZE,
        total=total,
    )


@app.get("/export.csv")
def export_organizations_csv(
    session: Annotated[Session, Depends(get_session)],
    org_type: Annotated[list[OrgType] | None, Query()] = None,
    state: str | None = None,
    min_camps_score: Annotated[int | None, Query(ge=0, le=100)] = None,
    min_panels_score: Annotated[int | None, Query(ge=0, le=100)] = None,
    min_media_score: Annotated[int | None, Query(ge=0, le=100)] = None,
    has_email: bool | None = None,
    search: str | None = None,
    sort_by: SortField = "name",
    sort_dir: SortDir = "asc",
    organization_id: Annotated[list[UUID] | None, Query()] = None,
) -> Response:
    stmt, _, camps, panels, media = _filtered_organizations(
        org_types=org_type,
        state=state,
        min_camps_score=min_camps_score,
        min_panels_score=min_panels_score,
        min_media_score=min_media_score,
        has_email=has_email,
        search=search,
    )
    stmt = _apply_sort(stmt, sort_by, sort_dir, camps, panels, media)
    orgs = list(session.scalars(stmt).all())
    if organization_id:
        wanted = set(organization_id)
        orgs = [org for org in orgs if org.id in wanted]
    org_ids = [org.id for org in orgs]
    scores = _load_scores_by_org(session, org_ids)
    contact_rows = session.scalars(select(Contact).where(Contact.organization_id.in_(org_ids))).all() if org_ids else []
    contacts_by_org: dict[UUID, list[Contact]] = {org_id: [] for org_id in org_ids}
    for contact in contact_rows:
        contacts_by_org.setdefault(contact.organization_id, []).append(contact)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "organization_id",
            "name",
            "org_type",
            "city",
            "state",
            "ein",
            "website",
            "phone",
            "camps_score",
            "panels_score",
            "media_score",
            "contact_name",
            "contact_role",
            "contact_email",
            "contact_phone",
        ]
    )
    for org in orgs:
        offer_scores = _scores_map(scores.get(org.id, []))
        exportable = [
            contact
            for contact in contacts_by_org.get(org.id, [])
            if not _contact_blocked_for_export(contact)
        ]
        top = _top_contact(exportable)
        writer.writerow(
            [
                str(org.id),
                org.name,
                org.org_type.value,
                org.city or "",
                org.state or "",
                org.ein or "",
                org.website or "",
                org.phone or "",
                offer_scores.camps if offer_scores.camps is not None else "",
                offer_scores.panels if offer_scores.panels is not None else "",
                offer_scores.media if offer_scores.media is not None else "",
                (top.full_name if top is not None else "") or "",
                (top.role.value if top is not None and top.role is not None else "") or "",
                (top.email if top is not None else "") or "",
                (top.phone if top is not None else "") or "",
            ]
        )
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=organizations.csv"},
    )
