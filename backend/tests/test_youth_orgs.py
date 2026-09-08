import json
from pathlib import Path

from backend.collectors.youth_orgs import YouthOrgsCollector, parse_staff_json
from backend.models import Contact, Organization, OrgType
from pytest import MonkeyPatch

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_parse_youth_orgs_fixture_returns_records(monkeypatch: MonkeyPatch) -> None:
    raw = json.loads((FIXTURES / "youth_orgs_raw.json").read_text())
    monkeypatch.setattr(
        "backend.collectors.youth_orgs.extract_staff",
        lambda _text: [
            {
                "name": "Dana Brooks",
                "title": "Head Coach",
                "email": "dana@riverside-aau.example.com",
                "phone": None,
            }
        ],
    )
    collector = YouthOrgsCollector()
    try:
        parsed = collector.parse(raw)
        assert len(parsed) > 0
        records = collector.to_records(parsed)
        organizations = [record for record in records if isinstance(record, Organization)]
        contacts = [record for record in records if isinstance(record, Contact)]
        assert len(organizations) > 0
        org = organizations[0]
        assert org.name == "Riverside AAU Basketball"
        assert org.google_place_id == "ChIJTestRiversideAAU"
        assert org.website == "https://riverside-aau.example.com/"
        assert org.phone == "+1 804-555-0100"
        assert org.org_type == OrgType.youth_sports_org
        assert org.events_per_year == 3
        assert org.roster_size_estimate == 4
        assert org.google_review_count == 42
        assert len(contacts) == 1
        assert contacts[0].confidence == 0.6
        assert contacts[0].email == "dana@riverside-aau.example.com"
    finally:
        collector.close()


def test_parse_staff_json_empty_on_guessing_prose() -> None:
    assert parse_staff_json("I cannot identify any staff on this page.") == []
    assert parse_staff_json("[]") == []
