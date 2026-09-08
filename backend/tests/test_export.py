from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from backend.api.main import app
from backend.app.db import get_session_factory
from backend.models import Contact, ContactRole, Organization, OrgType

MINOR_NAME = "Zara Minorguard Exportprobe"
MINOR_EMAIL = "minor-guard-export-probe@example.invalid"
MINOR_PHONE = "804-555-0199"
ADULT_NAME = "Pat Adult Exportprobe"
ADULT_EMAIL = "adult-export-probe@example.invalid"


@pytest.fixture
def export_org() -> Iterator[Organization]:
    factory = get_session_factory()
    session = factory()
    org = Organization(
        name=f"Export Probe Org {uuid4()}",
        org_type=OrgType.youth_sports_org,
        city="Richmond",
        state="VA",
        ein=f"00{uuid4().hex[:7]}",
        is_active=True,
    )
    session.add(org)
    session.flush()
    session.add(
        Contact(
            organization_id=org.id,
            full_name=MINOR_NAME,
            first_name="Zara",
            last_name="Exportprobe",
            title_raw="U-16 Roster Player",
            role=ContactRole.unknown,
            email=MINOR_EMAIL,
            phone=MINOR_PHONE,
            source_url="https://riverside-aau.example.com/roster",
            confidence=0.9,
            is_minor_related=True,
        )
    )
    session.add(
        Contact(
            organization_id=org.id,
            full_name=ADULT_NAME,
            first_name="Pat",
            last_name="Exportprobe",
            title_raw="Executive Director",
            role=ContactRole.executive_director,
            email=ADULT_EMAIL,
            phone="804-555-0100",
            source_url="https://riverside-aau.example.com/staff",
            confidence=0.9,
            is_minor_related=False,
        )
    )
    session.commit()
    org_id = org.id
    session.close()
    factory = get_session_factory()
    try:
        with factory() as lookup:
            loaded = lookup.get(Organization, org_id)
            assert loaded is not None
            yield loaded
    finally:
        with factory() as cleanup:
            cleanup.execute(delete(Contact).where(Contact.organization_id == org_id))
            cleanup.execute(delete(Organization).where(Organization.id == org_id))
            cleanup.commit()


def test_minor_related_contact_never_appears_in_csv_export(export_org: Organization) -> None:
    """Compliance guarantee: a flagged minor contact cannot leak into CSV export.

    GET /export.csv uses the same filters as GET /organizations. For every
    combination below, the file may include the adult contact. It must never
    include the flagged contact's name, email, or phone.
    """
    org_id = str(export_org.id)
    filter_combinations: list[dict[str, str]] = [
        {},
        {"organization_id": org_id},
        {"org_type": OrgType.youth_sports_org.value},
        {"state": "VA"},
        {"search": export_org.name},
        {"has_email": "true"},
        {"has_email": "false"},
        {"min_camps_score": "0"},
        {"min_panels_score": "0"},
        {"min_media_score": "0"},
        {
            "organization_id": org_id,
            "org_type": OrgType.youth_sports_org.value,
            "state": "VA",
            "search": "Export Probe",
            "has_email": "true",
            "min_camps_score": "0",
            "min_panels_score": "0",
            "min_media_score": "0",
            "sort_by": "name",
            "sort_dir": "asc",
        },
        {
            "organization_id": org_id,
            "org_type": OrgType.youth_sports_org.value,
            "state": "VA",
            "has_email": "false",
            "sort_by": "last_verified",
            "sort_dir": "desc",
        },
    ]
    forbidden = (MINOR_NAME, MINOR_EMAIL, MINOR_PHONE)
    with TestClient(app) as client:
        for params in filter_combinations:
            response = client.get("/export.csv", params=params)
            assert response.status_code == 200, params
            assert "text/csv" in response.headers["content-type"]
            body = response.text
            for token in forbidden:
                assert token not in body, (
                    f"Flagged minor contact leaked into export with filters {params}: {token}"
                )
            if list(params.keys()) == ["organization_id"]:
                assert ADULT_NAME in body
                assert ADULT_EMAIL in body
                assert MINOR_NAME not in body
