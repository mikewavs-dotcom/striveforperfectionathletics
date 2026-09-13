import logging
from collections.abc import Generator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import Settings, get_settings
from backend.app.db import get_session_factory
from backend.models import Contact, Organization
from backend.enrich.pipeline import EnrichmentError, enrich_organizations, enrichment_keys_configured
from backend.outreach.reachinbox import (
    ReachInboxClient,
    ReachInboxError,
    is_configured,
    map_accounts,
    map_campaigns,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/outreach")

_NOT_CONFIGURED_DETAIL = (
    "ReachInbox is not configured. Add REACHINBOX_API_KEY to .env and restart the API."
)


class OutreachStatus(BaseModel):
    configured: bool


class CreateCampaignBody(BaseModel):
    name: str


class PushLeadsBody(BaseModel):
    organization_ids: list[UUID]


class PushLeadsResult(BaseModel):
    pushed: int
    skipped_minor: int
    skipped_no_email: int
    campaign_id: int


def get_session() -> Generator[Session, None, None]:
    factory = get_session_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()


def _unconfigured() -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"configured": False, "detail": _NOT_CONFIGURED_DETAIL},
    )


def _configured_settings() -> Settings | None:
    settings = get_settings()
    if not is_configured(settings.reachinbox_api_key):
        return None
    return settings


def _upstream_error(exc: ReachInboxError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@router.get("/status", response_model=OutreachStatus)
def outreach_status() -> OutreachStatus:
    settings = get_settings()
    return OutreachStatus(configured=is_configured(settings.reachinbox_api_key))


@router.get("/campaigns", response_model=None)
def list_campaigns() -> JSONResponse | dict[str, list[dict[str, object]]]:
    settings = _configured_settings()
    if settings is None:
        return _unconfigured()
    try:
        with ReachInboxClient(
            api_key=settings.reachinbox_api_key,
            base_url=settings.reachinbox_base_url,
        ) as client:
            payload = client.list_campaigns()
    except ReachInboxError as exc:
        return _upstream_error(exc)
    return {"campaigns": map_campaigns(payload)}


@router.get("/accounts", response_model=None)
def list_accounts() -> JSONResponse | dict[str, list[dict[str, object]]]:
    settings = _configured_settings()
    if settings is None:
        return _unconfigured()
    try:
        with ReachInboxClient(
            api_key=settings.reachinbox_api_key,
            base_url=settings.reachinbox_base_url,
        ) as client:
            payload = client.list_accounts()
    except ReachInboxError as exc:
        return _upstream_error(exc)
    return {"accounts": map_accounts(payload)}


@router.post("/campaigns", response_model=None)
def create_campaign(body: CreateCampaignBody) -> JSONResponse | object:
    settings = _configured_settings()
    if settings is None:
        return _unconfigured()
    try:
        with ReachInboxClient(
            api_key=settings.reachinbox_api_key,
            base_url=settings.reachinbox_base_url,
        ) as client:
            return client.create_campaign(body.name)
    except ReachInboxError as exc:
        return _upstream_error(exc)


@router.post("/campaigns/{campaign_id}/start", response_model=None)
def start_campaign(campaign_id: int) -> JSONResponse | object:
    settings = _configured_settings()
    if settings is None:
        return _unconfigured()
    try:
        with ReachInboxClient(
            api_key=settings.reachinbox_api_key,
            base_url=settings.reachinbox_base_url,
        ) as client:
            return client.start_campaign(campaign_id)
    except ReachInboxError as exc:
        return _upstream_error(exc)


@router.post("/campaigns/{campaign_id}/pause", response_model=None)
def pause_campaign(campaign_id: int) -> JSONResponse | object:
    settings = _configured_settings()
    if settings is None:
        return _unconfigured()
    try:
        with ReachInboxClient(
            api_key=settings.reachinbox_api_key,
            base_url=settings.reachinbox_base_url,
        ) as client:
            return client.pause_campaign(campaign_id)
    except ReachInboxError as exc:
        return _upstream_error(exc)


@router.post("/campaigns/{campaign_id}/leads", response_model=None)
def push_leads(
    campaign_id: int,
    body: PushLeadsBody,
    session: Annotated[Session, Depends(get_session)],
) -> JSONResponse | PushLeadsResult:
    settings = _configured_settings()
    if settings is None:
        return _unconfigured()

    pushed, skipped_minor, skipped_no_email, leads = _eligible_leads(
        session, body.organization_ids
    )
    if skipped_no_email > 0 and enrichment_keys_configured(settings):
        try:
            enrich_organizations(session, body.organization_ids, settings)
            session.commit()
        except EnrichmentError:
            session.rollback()
            logger.exception("Enrichment failed before ReachInbox push")
        pushed, skipped_minor, skipped_no_email, leads = _eligible_leads(
            session, body.organization_ids
        )
    if not leads:
        return PushLeadsResult(
            pushed=pushed,
            skipped_minor=skipped_minor,
            skipped_no_email=skipped_no_email,
            campaign_id=campaign_id,
        )
    try:
        with ReachInboxClient(
            api_key=settings.reachinbox_api_key,
            base_url=settings.reachinbox_base_url,
        ) as client:
            client.add_leads(campaign_id, leads)
    except ReachInboxError as exc:
        return _upstream_error(exc)
    return PushLeadsResult(
        pushed=len(leads),
        skipped_minor=skipped_minor,
        skipped_no_email=skipped_no_email,
        campaign_id=campaign_id,
    )


def _eligible_leads(
    session: Session,
    organization_ids: list[UUID],
) -> tuple[int, int, int, list[dict[str, str]]]:
    from backend.api.main import _top_contact

    skipped_minor = 0
    skipped_no_email = 0
    leads: list[dict[str, str]] = []
    if not organization_ids:
        return 0, 0, 0, leads

    orgs = session.scalars(
        select(Organization).where(Organization.id.in_(organization_ids))
    ).all()
    org_by_id = {org.id: org for org in orgs}
    contact_rows = session.scalars(
        select(Contact).where(Contact.organization_id.in_(organization_ids))
    ).all()
    contacts_by_org: dict[UUID, list[Contact]] = {org_id: [] for org_id in organization_ids}
    for contact in contact_rows:
        contacts_by_org.setdefault(contact.organization_id, []).append(contact)

    for org_id in organization_ids:
        org = org_by_id.get(org_id)
        contacts = contacts_by_org.get(org_id, [])
        non_minor = [contact for contact in contacts if not contact.is_minor_related]
        if org is None or not non_minor:
            skipped_minor += 1
            continue
        top = _top_contact(non_minor)
        if top is None or top.is_minor_related:
            skipped_minor += 1
            continue
        email = (top.email or "").strip()
        if email == "":
            skipped_no_email += 1
            continue
        leads.append(
            {
                "email": email,
                "firstName": top.first_name or "",
                "lastName": top.last_name or "",
                "company": org.name,
                "organizationId": str(org.id),
            }
        )
    return len(leads), skipped_minor, skipped_no_email, leads
