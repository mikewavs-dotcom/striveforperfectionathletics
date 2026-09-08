"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-08

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

org_type_enum = postgresql.ENUM(
    "booster_club",
    "nil_collective",
    "youth_sports_org",
    "travel_program",
    "showcase_operator",
    "high_school",
    "school_district",
    "college",
    "business",
    "other",
    name="org_type",
    create_type=False,
)

contact_role_enum = postgresql.ENUM(
    "athletic_director",
    "compliance_officer",
    "head_coach",
    "assistant_coach",
    "board_officer",
    "executive_director",
    "marketing_contact",
    "owner",
    "unknown",
    name="contact_role",
    create_type=False,
)

offer_enum = postgresql.ENUM(
    "camps",
    "panels",
    "media",
    name="offer",
    create_type=False,
)

policy_event_type_enum = postgresql.ENUM(
    "policy_adopted",
    "policy_amended",
    "meeting_scheduled",
    "guidance_issued",
    name="policy_event_type",
    create_type=False,
)

source_run_status_enum = postgresql.ENUM(
    "success",
    "partial",
    "failed",
    name="source_run_status",
    create_type=False,
)


def upgrade() -> None:
    org_type_enum.create(op.get_bind(), checkfirst=True)
    contact_role_enum.create(op.get_bind(), checkfirst=True)
    offer_enum.create(op.get_bind(), checkfirst=True)
    policy_event_type_enum.create(op.get_bind(), checkfirst=True)
    source_run_status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("canonical_name", sa.String(), nullable=True),
        sa.Column("org_type", org_type_enum, nullable=False),
        sa.Column("website", sa.String(), nullable=True),
        sa.Column("phone", sa.String(), nullable=True),
        sa.Column("street", sa.String(), nullable=True),
        sa.Column("city", sa.String(), nullable=True),
        sa.Column("state", sa.String(), nullable=True),
        sa.Column("postal_code", sa.String(), nullable=True),
        sa.Column("county", sa.String(), nullable=True),
        sa.Column("ein", sa.String(), nullable=True),
        sa.Column("annual_revenue", sa.Numeric(), nullable=True),
        sa.Column("program_expenses", sa.Numeric(), nullable=True),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("roster_size_estimate", sa.Integer(), nullable=True),
        sa.Column("events_per_year", sa.Integer(), nullable=True),
        sa.Column("google_place_id", sa.String(), nullable=True),
        sa.Column("google_rating", sa.Numeric(), nullable=True),
        sa.Column("google_review_count", sa.Integer(), nullable=True),
        sa.Column("location_count", sa.Integer(), nullable=True),
        sa.Column("source_urls", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "contacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("full_name", sa.String(), nullable=True),
        sa.Column("first_name", sa.String(), nullable=True),
        sa.Column("last_name", sa.String(), nullable=True),
        sa.Column("title_raw", sa.String(), nullable=True),
        sa.Column("role", contact_role_enum, nullable=True),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("phone", sa.String(), nullable=True),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("is_minor_related", sa.Boolean(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("confidence >= 0.0 AND confidence <= 1.0", name="ck_contacts_confidence"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "scores",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("offer", offer_enum, nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("signals", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("model_version", sa.String(), nullable=False),
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("score >= 0 AND score <= 100", name="ck_scores_score"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "policy_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("jurisdiction", sa.String(), nullable=False),
        sa.Column("source_url", sa.String(), nullable=False),
        sa.Column("event_type", policy_event_type_enum, nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("summary", sa.String(length=400), nullable=True),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("linked_organization_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["linked_organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "sponsors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("brand_name", sa.String(), nullable=False),
        sa.Column("detected_on_url", sa.String(), nullable=False),
        sa.Column("detected_on_organization_id", sa.Uuid(), nullable=True),
        sa.Column("logo_image_url", sa.String(), nullable=True),
        sa.Column("extraction_confidence", sa.Float(), nullable=True),
        sa.Column("matched_organization_id", sa.Uuid(), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["detected_on_organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["matched_organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "source_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("collector_name", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", source_run_status_enum, nullable=False),
        sa.Column("records_found", sa.Integer(), nullable=True),
        sa.Column("records_new", sa.Integer(), nullable=True),
        sa.Column("records_updated", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("pages_fetched", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("target_url", sa.String(), nullable=True),
        sa.Column("robots_allowed", sa.Boolean(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("source_runs")
    op.drop_table("sponsors")
    op.drop_table("policy_events")
    op.drop_table("scores")
    op.drop_table("contacts")
    op.drop_table("organizations")
    source_run_status_enum.drop(op.get_bind(), checkfirst=True)
    policy_event_type_enum.drop(op.get_bind(), checkfirst=True)
    offer_enum.drop(op.get_bind(), checkfirst=True)
    contact_role_enum.drop(op.get_bind(), checkfirst=True)
    org_type_enum.drop(op.get_bind(), checkfirst=True)
