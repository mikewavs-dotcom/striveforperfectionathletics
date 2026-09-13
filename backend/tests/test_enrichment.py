import json
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from backend.api.main import app
from backend.app.db import get_session_factory
from backend.enrich.apollo import email_from_match, map_people
from backend.enrich.hunter import verification_status, verified_email
from backend.enrich.keys import is_configured
from backend.models import Contact, ContactRole, Organization, OrgType

FIXTURES = Path(__file__).resolve().parent / "fixtures"
ADULT_EMAIL = "jordan.hale@riverside-aau.example.edu"
MINOR_EMAIL = "sam.onlyminor@riverside-aau.example.edu"

_UNCONFIGURED = SimpleNamespace(
    apollo_api_key="",
    hunter_api_key="",
    apollo_base_url="https://api.apollo.io",
    hunter_base_url="https://api.hunter.io",
)
_PLACEHOLDER = SimpleNamespace(
    apollo_api_key="replace-with-apollo-api-key",
    hunter_api_key="replace-with-hunter-api-key",
    apollo_base_url="https://api.apollo.io",
    hunter_base_url="https://api.hunter.io",
)
_CONFIGURED = SimpleNamespace(
    apollo_api_key="test-apollo-key",
    hunter_api_key="test-hunter-key",
    apollo_base_url="https://api.apollo.io",
    hunter_base_url="https://api.hunter.io",
)


class FakeResponse:
    def __init__(self, payload: object, url: str, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.url = url

    def raise_for_status(self) -> None:
        if self.status_code >= 400 and self.status_code != 202:
            request = httpx.Request("GET", self.url)
            raise httpx.HTTPStatusError(
                "error",
                request=request,
                response=httpx.Response(self.status_code, request=request),
            )

    def json(self) -> object:
        return self._payload


def _patch_settings(monkeypatch: pytest.MonkeyPatch, settings: SimpleNamespace) -> None:
    monkeypatch.setattr("backend.api.enrichment.get_settings", lambda: settings)
    monkeypatch.setattr("backend.api.outreach.get_settings", lambda: settings)


def _discard_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    def discard(**kwargs: object) -> None:
        return None

    monkeypatch.setattr("backend.enrich.apollo.log_fetch", discard)
    monkeypatch.setattr("backend.enrich.hunter.log_fetch", discard)


def _payload_for_url(url: str, params: object) -> object:
    if "email-verifier" in url:
        email = ""
        if isinstance(params, dict):
            raw = params.get("email")
            if isinstance(raw, str):
                email = raw
        if "onlyminor" in email or "roster" in email:
            return {
                "data": {
                    "status": "valid",
                    "score": 90,
                    "email": email,
                }
            }
        hunter = json.loads((FIXTURES / "hunter_email_verifier.json").read_text())
        if email != "":
            hunter["data"]["email"] = email
        return hunter
    if "people/match" in url:
        return json.loads((FIXTURES / "apollo_people_match.json").read_text())
    return json.loads((FIXTURES / "apollo_people_search.json").read_text())


def _install_httpx_recorder(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            return None

        def request(self, method: str, url: str | httpx.URL, **kwargs: object) -> FakeResponse:
            calls.append(
                {
                    "method": method,
                    "url": str(url),
                    "json": kwargs.get("json"),
                    "params": kwargs.get("params"),
                }
            )
            payload = _payload_for_url(str(url), kwargs.get("params"))
            return FakeResponse(payload, str(url))

        def close(self) -> None:
            return None

    monkeypatch.setattr("backend.enrich.apollo.httpx.Client", FakeClient)
    monkeypatch.setattr("backend.enrich.hunter.httpx.Client", FakeClient)
    _discard_audit(monkeypatch)
    return calls


def _install_httpx_blocker(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    constructed: list[str] = []

    class BoomClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            constructed.append("httpx")
            raise AssertionError("httpx must not be called")

    monkeypatch.setattr("backend.enrich.apollo.httpx.Client", BoomClient)
    monkeypatch.setattr("backend.enrich.hunter.httpx.Client", BoomClient)
    return constructed


@pytest.fixture
def enrich_org() -> Iterator[Organization]:
    factory = get_session_factory()
    session = factory()
    org = Organization(
        name=f"Riverside AAU Enrich {uuid4()}",
        org_type=OrgType.youth_sports_org,
        website="https://riverside-aau.example.edu",
        city="Richmond",
        state="VA",
        is_active=True,
    )
    session.add(org)
    session.flush()
    session.add(
        Contact(
            organization_id=org.id,
            full_name="Pat Noemail Enrichprobe",
            first_name="Pat",
            last_name="Noemail",
            title_raw="Athletic Director",
            role=ContactRole.athletic_director,
            email=None,
            source_url="https://riverside-aau.example.edu/staff",
            confidence=0.9,
            is_minor_related=False,
        )
    )
    session.add(
        Contact(
            organization_id=org.id,
            full_name="Zara Minorguard Enrichprobe",
            first_name="Zara",
            last_name="Minorguard",
            title_raw="U-16 Roster Player",
            role=ContactRole.unknown,
            email=None,
            source_url="https://riverside-aau.example.edu/roster",
            confidence=0.9,
            is_minor_related=True,
        )
    )
    session.commit()
    org_id = org.id
    session.close()
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


def test_is_configured_rejects_empty_and_placeholder() -> None:
    assert is_configured("") is False
    assert is_configured("   ") is False
    assert is_configured("replace-with-apollo-api-key") is False
    assert is_configured("replace-with-hunter-api-key") is False
    assert is_configured("test-apollo-key") is True


def test_status_booleans_when_keys_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch, _UNCONFIGURED)
    constructed = _install_httpx_blocker(monkeypatch)
    with TestClient(app) as client:
        response = client.get("/enrichment/status")
    assert response.status_code == 200
    body = response.json()
    assert body == {"apollo": False, "hunter": False}
    assert "api_key" not in json.dumps(body).lower()
    assert "test-apollo-key" not in json.dumps(body)
    assert constructed == []


def test_status_booleans_when_keys_placeholder(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch, _PLACEHOLDER)
    constructed = _install_httpx_blocker(monkeypatch)
    with TestClient(app) as client:
        response = client.get("/enrichment/status")
    assert response.status_code == 200
    assert response.json() == {"apollo": False, "hunter": False}
    assert constructed == []


def test_status_booleans_when_keys_present(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch, _CONFIGURED)
    constructed = _install_httpx_blocker(monkeypatch)
    with TestClient(app) as client:
        response = client.get("/enrichment/status")
    assert response.status_code == 200
    body = response.json()
    assert body == {"apollo": True, "hunter": True}
    serialized = json.dumps(body)
    assert "test-apollo-key" not in serialized
    assert "test-hunter-key" not in serialized
    assert constructed == []


def test_map_people_from_saved_fixture() -> None:
    payload = json.loads((FIXTURES / "apollo_people_search.json").read_text())
    mapped = map_people(payload)
    assert len(mapped) > 0
    assert mapped[0]["first_name"] == "Jordan"
    assert mapped[0]["last_name"] == "Hale"
    assert mapped[0]["title"] == "Athletic Director"
    assert "email" not in mapped[0]


def test_map_people_fixture_must_keep_returning_records() -> None:
    payload = json.loads((FIXTURES / "apollo_people_search.json").read_text())
    mapped = map_people(payload)
    if len(mapped) == 0:
        raise AssertionError("Apollo people fixture previously returned records; parser returned none")


def test_email_from_match_fixture() -> None:
    payload = json.loads((FIXTURES / "apollo_people_match.json").read_text())
    assert email_from_match(payload) == ADULT_EMAIL


def test_hunter_verifier_fixture_is_valid() -> None:
    payload = json.loads((FIXTURES / "hunter_email_verifier.json").read_text())
    assert verification_status(payload) == "valid"
    assert verified_email(payload) == ADULT_EMAIL


def test_enrich_503_when_keys_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch, _UNCONFIGURED)
    constructed = _install_httpx_blocker(monkeypatch)
    with TestClient(app) as client:
        response = client.post("/enrichment/organizations", json={"organization_ids": []})
    assert response.status_code == 503
    body = response.json()
    assert body["apollo"] is False
    assert body["hunter"] is False
    assert "detail" in body
    assert constructed == []


def test_enrich_skips_minors_and_persists_verified_adult(
    monkeypatch: pytest.MonkeyPatch,
    enrich_org: Organization,
) -> None:
    _patch_settings(monkeypatch, _CONFIGURED)
    calls = _install_httpx_recorder(monkeypatch)
    with TestClient(app) as client:
        response = client.post(
            "/enrichment/organizations",
            json={"organization_ids": [str(enrich_org.id)]},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["persisted"] >= 1
    assert body["skipped_minor"] >= 1
    serialized = json.dumps(calls)
    assert MINOR_EMAIL not in serialized
    assert "U-16" not in serialized
    hunter_emails = [
        call["params"]["email"]
        for call in calls
        if isinstance(call.get("params"), dict) and "email" in call["params"]
    ]
    assert MINOR_EMAIL not in hunter_emails
    assert all("onlyminor" not in email for email in hunter_emails)

    factory = get_session_factory()
    with factory() as session:
        contacts = session.scalars(select(Contact).where(Contact.organization_id == enrich_org.id)).all()
        emails = {contact.email for contact in contacts if contact.email}
        assert ADULT_EMAIL in emails
        for contact in contacts:
            if contact.is_minor_related:
                assert contact.email in {None, ""}
            if contact.email == ADULT_EMAIL:
                assert contact.is_minor_related is False
