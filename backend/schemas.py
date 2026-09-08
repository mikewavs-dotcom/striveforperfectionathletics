from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from backend.models import ContactRole, Offer, OrgType, PolicyEventType, SourceRunStatus


class OrganizationSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    canonical_name: str | None
    org_type: OrgType
    website: str | None
    phone: str | None
    street: str | None
    city: str | None
    state: str | None
    postal_code: str | None
    county: str | None
    ein: str | None
    annual_revenue: Decimal | None
    program_expenses: Decimal | None
    fiscal_year: int | None
    roster_size_estimate: int | None
    events_per_year: int | None
    google_place_id: str | None
    google_rating: Decimal | None
    google_review_count: int | None
    location_count: int | None
    source_urls: list[str] | None
    first_seen_at: datetime | None
    last_verified_at: datetime | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ContactSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    full_name: str | None
    first_name: str | None
    last_name: str | None
    title_raw: str | None
    role: ContactRole | None
    email: str | None
    phone: str | None
    source_url: str | None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    is_minor_related: bool
    first_seen_at: datetime | None
    last_verified_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ScoreSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    offer: Offer
    score: int = Field(ge=0, le=100)
    rationale: str
    signals: dict[str, object]
    model_version: str
    scored_at: datetime
    created_at: datetime
    updated_at: datetime


class PolicyEventSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    jurisdiction: str
    source_url: str
    event_type: PolicyEventType
    detected_at: datetime
    effective_date: date | None
    summary: str | None = Field(default=None, max_length=400)
    content_hash: str
    linked_organization_id: UUID | None
    created_at: datetime
    updated_at: datetime


class SponsorSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    brand_name: str
    detected_on_url: str
    detected_on_organization_id: UUID | None
    logo_image_url: str | None
    extraction_confidence: float | None
    matched_organization_id: UUID | None
    detected_at: datetime
    created_at: datetime
    updated_at: datetime


class SourceRunSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    collector_name: str
    started_at: datetime
    finished_at: datetime | None
    status: SourceRunStatus
    records_found: int | None
    records_new: int | None
    records_updated: int | None
    error_message: str | None
    pages_fetched: int | None
    created_at: datetime
    updated_at: datetime


class AuditLogSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    timestamp: datetime
    actor: str
    action: str
    target_url: str | None
    robots_allowed: bool | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
