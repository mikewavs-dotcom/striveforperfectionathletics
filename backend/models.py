from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class OrgType(str, Enum):
    booster_club = "booster_club"
    nil_collective = "nil_collective"
    youth_sports_org = "youth_sports_org"
    travel_program = "travel_program"
    showcase_operator = "showcase_operator"
    high_school = "high_school"
    school_district = "school_district"
    college = "college"
    business = "business"
    other = "other"


class ContactRole(str, Enum):
    athletic_director = "athletic_director"
    compliance_officer = "compliance_officer"
    head_coach = "head_coach"
    assistant_coach = "assistant_coach"
    board_officer = "board_officer"
    executive_director = "executive_director"
    marketing_contact = "marketing_contact"
    owner = "owner"
    unknown = "unknown"


class Offer(str, Enum):
    camps = "camps"
    panels = "panels"
    media = "media"


class PolicyEventType(str, Enum):
    policy_adopted = "policy_adopted"
    policy_amended = "policy_amended"
    meeting_scheduled = "meeting_scheduled"
    guidance_issued = "guidance_issued"


class SourceRunStatus(str, Enum):
    success = "success"
    partial = "partial"
    failed = "failed"


class Organization(TimestampMixin, Base):
    __tablename__ = "organizations"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    canonical_name: Mapped[str | None] = mapped_column(String, nullable=True)
    org_type: Mapped[OrgType] = mapped_column(
        SAEnum(OrgType, name="org_type", native_enum=True),
        nullable=False,
    )
    website: Mapped[str | None] = mapped_column(String, nullable=True)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    street: Mapped[str | None] = mapped_column(String, nullable=True)
    city: Mapped[str | None] = mapped_column(String, nullable=True)
    state: Mapped[str | None] = mapped_column(String, nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String, nullable=True)
    county: Mapped[str | None] = mapped_column(String, nullable=True)
    ein: Mapped[str | None] = mapped_column(String, nullable=True)
    annual_revenue: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    program_expenses: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    fiscal_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    roster_size_estimate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    events_per_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    google_place_id: Mapped[str | None] = mapped_column(String, nullable=True)
    google_rating: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    google_review_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    location_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_urls: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    contacts: Mapped[list["Contact"]] = relationship(back_populates="organization")
    scores: Mapped[list["Score"]] = relationship(back_populates="organization")


class Contact(TimestampMixin, Base):
    __tablename__ = "contacts"
    __table_args__ = (
        CheckConstraint("confidence >= 0.0 AND confidence <= 1.0", name="ck_contacts_confidence"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id"),
        nullable=False,
    )
    full_name: Mapped[str | None] = mapped_column(String, nullable=True)
    first_name: Mapped[str | None] = mapped_column(String, nullable=True)
    last_name: Mapped[str | None] = mapped_column(String, nullable=True)
    title_raw: Mapped[str | None] = mapped_column(String, nullable=True)
    role: Mapped[ContactRole | None] = mapped_column(
        SAEnum(ContactRole, name="contact_role", native_enum=True),
        nullable=True,
    )
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_minor_related: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped[Organization] = relationship(back_populates="contacts")


class Score(TimestampMixin, Base):
    __tablename__ = "scores"
    __table_args__ = (
        CheckConstraint("score >= 0 AND score <= 100", name="ck_scores_score"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id"),
        nullable=False,
    )
    offer: Mapped[Offer] = mapped_column(
        SAEnum(Offer, name="offer", native_enum=True),
        nullable=False,
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    signals: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    model_version: Mapped[str] = mapped_column(String, nullable=False)
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    organization: Mapped[Organization] = relationship(back_populates="scores")


class PolicyEvent(TimestampMixin, Base):
    __tablename__ = "policy_events"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    jurisdiction: Mapped[str] = mapped_column(String, nullable=False)
    source_url: Mapped[str] = mapped_column(String, nullable=False)
    event_type: Mapped[PolicyEventType] = mapped_column(
        SAEnum(PolicyEventType, name="policy_event_type", native_enum=True),
        nullable=False,
    )
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    summary: Mapped[str | None] = mapped_column(String(400), nullable=True)
    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    linked_organization_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id"),
        nullable=True,
    )


class Sponsor(TimestampMixin, Base):
    __tablename__ = "sponsors"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    brand_name: Mapped[str] = mapped_column(String, nullable=False)
    detected_on_url: Mapped[str] = mapped_column(String, nullable=False)
    detected_on_organization_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id"),
        nullable=True,
    )
    logo_image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    extraction_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    matched_organization_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id"),
        nullable=True,
    )
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SourceRun(TimestampMixin, Base):
    __tablename__ = "source_runs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    collector_name: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[SourceRunStatus] = mapped_column(
        SAEnum(SourceRunStatus, name="source_run_status", native_enum=True),
        nullable=False,
    )
    records_found: Mapped[int | None] = mapped_column(Integer, nullable=True)
    records_new: Mapped[int | None] = mapped_column(Integer, nullable=True)
    records_updated: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    pages_fetched: Mapped[int | None] = mapped_column(Integer, nullable=True)


class AuditLog(TimestampMixin, Base):
    __tablename__ = "audit_log"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    target_url: Mapped[str | None] = mapped_column(String, nullable=True)
    robots_allowed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
