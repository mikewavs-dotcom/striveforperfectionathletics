from collections.abc import Generator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.config import Settings, get_settings
from backend.app.db import get_session_factory
from backend.enrich.keys import is_configured
from backend.enrich.pipeline import EnrichmentError, enrich_organizations, enrichment_keys_configured

router = APIRouter(prefix="/enrichment")

_NOT_CONFIGURED_DETAIL = (
    "Apollo and Hunter are not configured. Add APOLLO_API_KEY and HUNTER_API_KEY "
    "to .env and restart the API."
)


class EnrichmentStatus(BaseModel):
    apollo: bool
    hunter: bool


class EnrichOrganizationsBody(BaseModel):
    organization_ids: list[UUID]


class EnrichOrganizationsResult(BaseModel):
    found: int
    persisted: int
    skipped_minor: int
    skipped_unverified: int
    skipped_no_people: int


def get_session() -> Generator[Session, None, None]:
    factory = get_session_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()


def _unconfigured() -> JSONResponse:
    settings = get_settings()
    return JSONResponse(
        status_code=503,
        content={
            "apollo": is_configured(settings.apollo_api_key),
            "hunter": is_configured(settings.hunter_api_key),
            "detail": _NOT_CONFIGURED_DETAIL,
        },
    )


def _configured_settings() -> Settings | None:
    settings = get_settings()
    if not enrichment_keys_configured(settings):
        return None
    return settings


@router.get("/status", response_model=EnrichmentStatus)
def enrichment_status() -> EnrichmentStatus:
    settings = get_settings()
    return EnrichmentStatus(
        apollo=is_configured(settings.apollo_api_key),
        hunter=is_configured(settings.hunter_api_key),
    )


@router.post("/organizations", response_model=None)
def enrich_organization_contacts(
    body: EnrichOrganizationsBody,
    session: Annotated[Session, Depends(get_session)],
) -> JSONResponse | EnrichOrganizationsResult:
    settings = _configured_settings()
    if settings is None:
        return _unconfigured()
    try:
        counts = enrich_organizations(session, body.organization_ids, settings)
        session.commit()
    except EnrichmentError as exc:
        session.rollback()
        return JSONResponse(status_code=502, content={"detail": str(exc)})
    return EnrichOrganizationsResult(
        found=counts.found,
        persisted=counts.persisted,
        skipped_minor=counts.skipped_minor,
        skipped_unverified=counts.skipped_unverified,
        skipped_no_people=counts.skipped_no_people,
    )
