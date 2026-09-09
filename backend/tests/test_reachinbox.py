import json
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from backend.api.main import app
from backend.app.db import get_session_factory
from backend.models import Contact, ContactRole, Organization, OrgType
from backend.outreach.reachinbox import is_configured, map_campaigns

FIXTURES = Path(__file__).resolve().parent / "fixtures"
MINOR_EMAIL = "minor-guard-reachinbox-probe@example.invalid"
ADULT_EMAIL = "adult-reachinbox-probe@example.invalid"
ONLY_MINOR_EMAIL = "only-minor-reachinbox-probe@example.invalid"
NO_EMAIL_NAME = "Pat Noemail Reachinboxprobe"

_UNCONFIGURED = SimpleNamespace(
    reachinbox_api_key="",
    reachinbox_base_url="https://api.reachinbox.ai",
)
_PLACEHOLDER = SimpleNamespace(
    reachinbox_api_key="replace-with-reachinbox-api-key",
    reachinbox_base_url="https://api.reachinbox.ai",
)
_CONFIGURED = SimpleNamespace(
    reachinbox_api_key="test-workspace-key",
    reachinbox_base_url="https://api.reachinbox.ai",
)


class FakeResponse:
    def __init__(self, payload: object, url: str, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.url = url

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", self.url)
            raise httpx.HTTPStatusError(
                "error",
                request=request,
                response=httpx.Response(self.status_code, request=request),
            )

    def json(self) -> object:
        return self._payload


def _patch_settings(monkeypatch: pytest.MonkeyPatch, settings: SimpleNamespace) -> None:
    monkeypatch.setattr("backend.api.outreach.get_settings", lambda: settings)


def _discard_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    def discard(**kwargs: object) -> None:
        return None

    monkeypatch.setattr("backend.outreach.reachinbox.log_fetch", discard)


def _install_httpx_recorder(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            return None

        def request(self, method: str, url: str | httpx.URL, **kwargs: object) -> FakeResponse:
            calls.append({"method": method, "url": str(url), "json": kwargs.get("json")})
            return FakeResponse(
                {"status": 200, "message": "ok", "data": ["firstName", "lastName"]},
                str(url),
            )

        def close(self) -> None:
            return None

    monkeypatch.setattr("backend.outreach.reachinbox.httpx.Client", FakeClient)
    _discard_audit(monkeypatch)
    return calls


def _install_httpx_blocker(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    constructed: list[str] = []

    class BoomClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            constructed.append("httpx")
            raise AssertionError("httpx must not be called")

    monkeypatch.setattr("backend.outreach.reachinbox.httpx.Client", BoomClient)
    return constructed


@pytest.fixture
def push_orgs() -> Iterator[tuple[Organization, Organization, Organization]]:
    factory = get_session_factory()
    session = factory()
    mixed = Organization(
        name=f"ReachInbox Mixed Org {uuid4()}",
        org_type=OrgType.youth_sports_org,
        city="Richmond",
        state="VA",
        is_active=True,
    )
    no_email = Organization(
        name=f"ReachInbox No Email Org {uuid4()}",
        org_type=OrgType.youth_sports_org,
        city="Richmond",
        state="VA",
        is_active=True,
    )
    only_minor = Organization(
        name=f"ReachInbox Only Minor Org {uuid4()}",
        org_type=OrgType.youth_sports_org,
        city="Richmond",
        state="VA",
        is_active=True,
    )
    session.add_all([mixed, no_email, only_minor])
    session.flush()
    session.add(
        Contact(
            organization_id=mixed.id,
            full_name="Zara Minorguard Reachinbox",
            first_name="Zara",
            last_name="Minorguard",
            title_raw="U-16 Roster Player",
            role=ContactRole.unknown,
            email=MINOR_EMAIL,
            source_url="https://riverside-aau.example.com/roster",
            confidence=0.9,
            is_minor_related=True,
        )
    )
    session.add(
        Contact(
            organization_id=mixed.id,
            full_name="Pat Adult Reachinbox",
            first_name="Pat",
            last_name="Adult",
            title_raw="Executive Director",
            role=ContactRole.executive_director,
            email=ADULT_EMAIL,
            source_url="https://riverside-aau.example.com/staff",
            confidence=0.9,
            is_minor_related=False,
        )
    )
    session.add(
        Contact(
            organization_id=no_email.id,
            full_name=NO_EMAIL_NAME,
            first_name="Pat",
            last_name="Noemail",
            title_raw="Athletic Director",
            role=ContactRole.athletic_director,
            email=None,
            source_url="https://riverside-aau.example.com/staff",
            confidence=0.9,
            is_minor_related=False,
        )
    )
    session.add(
        Contact(
            organization_id=only_minor.id,
            full_name="Sam Onlyminor Reachinbox",
            first_name="Sam",
            last_name="Onlyminor",
            title_raw="Grade 10 Athlete",
            role=ContactRole.unknown,
            email=ONLY_MINOR_EMAIL,
            source_url="https://riverside-aau.example.com/roster",
            confidence=0.9,
            is_minor_related=True,
        )
    )
    session.commit()
    mixed_id = mixed.id
    no_email_id = no_email.id
    only_minor_id = only_minor.id
    session.close()
    try:
        with factory() as lookup:
            loaded_mixed = lookup.get(Organization, mixed_id)
            loaded_no_email = lookup.get(Organization, no_email_id)
            loaded_only_minor = lookup.get(Organization, only_minor_id)
            assert loaded_mixed is not None
            assert loaded_no_email is not None
            assert loaded_only_minor is not None
            yield loaded_mixed, loaded_no_email, loaded_only_minor
    finally:
        with factory() as cleanup:
            ids = [mixed_id, no_email_id, only_minor_id]
            cleanup.execute(delete(Contact).where(Contact.organization_id.in_(ids)))
            cleanup.execute(delete(Organization).where(Organization.id.in_(ids)))
            cleanup.commit()


def test_is_configured_rejects_empty_and_placeholder() -> None:
    assert is_configured("") is False
    assert is_configured("   ") is False
    assert is_configured("replace-with-reachinbox-api-key") is False
    assert is_configured("test-workspace-key") is True


def test_campaigns_503_when_key_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch, _UNCONFIGURED)
    constructed = _install_httpx_blocker(monkeypatch)
    with TestClient(app) as client:
        response = client.get("/outreach/campaigns")
    assert response.status_code == 503
    body = response.json()
    assert body["configured"] is False
    assert "detail" in body
    assert constructed == []


def test_campaigns_503_when_key_placeholder(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch, _PLACEHOLDER)
    constructed = _install_httpx_blocker(monkeypatch)
    with TestClient(app) as client:
        response = client.get("/outreach/campaigns")
    assert response.status_code == 503
    body = response.json()
    assert body["configured"] is False
    assert "detail" in body
    assert constructed == []


def test_map_campaigns_from_saved_fixture() -> None:
    payload = json.loads((FIXTURES / "reachinbox_campaigns_all.json").read_text())
    mapped = map_campaigns(payload)
    assert mapped[0] == {"id": 147, "name": "ABC", "status": "Active"}
    assert mapped[1] == {"id": 148, "name": "Draft Campaign"}
    assert "status" not in mapped[1]
    assert "dailyLimit" not in mapped[0]
    assert "coreVariables" not in mapped[0]
    for row in mapped:
        assert set(row.keys()) <= {"id", "name", "status"}


def test_add_leads_excludes_minor_related_contacts(
    monkeypatch: pytest.MonkeyPatch,
    push_orgs: tuple[Organization, Organization, Organization],
) -> None:
    mixed, no_email, only_minor = push_orgs
    _patch_settings(monkeypatch, _CONFIGURED)
    calls = _install_httpx_recorder(monkeypatch)
    with TestClient(app) as client:
        response = client.post(
            "/outreach/campaigns/7/leads",
            json={
                "organization_ids": [str(mixed.id), str(no_email.id), str(only_minor.id)],
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["pushed"] == 1
    assert body["skipped_minor"] == 1
    assert body["skipped_no_email"] == 1
    assert body["campaign_id"] == 7
    assert len(calls) == 1
    payload = calls[0]["json"]
    assert isinstance(payload, dict)
    leads = payload["leads"]
    assert isinstance(leads, list)
    serialized = json.dumps(payload)
    assert MINOR_EMAIL not in serialized
    assert ONLY_MINOR_EMAIL not in serialized
    assert NO_EMAIL_NAME not in serialized
    assert ADULT_EMAIL in serialized
    emails = [lead["email"] for lead in leads if isinstance(lead, dict)]
    assert emails == [ADULT_EMAIL]
    for lead in leads:
        assert isinstance(lead, dict)
        assert lead.get("email") not in {MINOR_EMAIL, ONLY_MINOR_EMAIL, None, ""}


def test_add_leads_skips_contact_with_no_email(
    monkeypatch: pytest.MonkeyPatch,
    push_orgs: tuple[Organization, Organization, Organization],
) -> None:
    _mixed, no_email, _only_minor = push_orgs
    _patch_settings(monkeypatch, _CONFIGURED)
    constructed = _install_httpx_blocker(monkeypatch)
    with TestClient(app) as client:
        response = client.post(
            "/outreach/campaigns/7/leads",
            json={"organization_ids": [str(no_email.id)]},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["pushed"] == 0
    assert body["skipped_no_email"] == 1
    assert body["skipped_minor"] == 0
    assert constructed == []
