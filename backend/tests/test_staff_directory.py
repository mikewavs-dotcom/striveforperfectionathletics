from pathlib import Path

from backend.collectors.staff_directory import StaffDirectoryCollector, StaffPerson, UNMAPPED_LOG
from backend.models import Contact, ContactRole, Organization, OrgType
from pytest import LogCaptureFixture, MonkeyPatch

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _no_claude(_text: str) -> list[StaffPerson]:
    raise AssertionError("Claude fallback should not run")


def _page(html_name: str, *, pattern: str, org_type: str = "college") -> dict[str, str]:
    return {
        "name": "Example Athletics",
        "url": "https://www.example.com/athletics/staff",
        "org_type": org_type,
        "pattern": pattern,
        "city": "Richmond",
        "state": "VA",
        "html": (FIXTURES / html_name).read_text(),
    }


def _parse_records(html_name: str, pattern: str, monkeypatch: MonkeyPatch) -> tuple[list[Organization], list[Contact]]:
    monkeypatch.setattr(
        "backend.collectors.staff_directory.extract_directory_staff",
        _no_claude,
    )
    collector = StaffDirectoryCollector()
    try:
        parsed = collector.parse({"pages": [_page(html_name, pattern=pattern)]})
        assert len(parsed) > 0
        records = collector.to_records(parsed)
    finally:
        collector.close()
    organizations = [record for record in records if isinstance(record, Organization)]
    contacts = [record for record in records if isinstance(record, Contact)]
    return organizations, contacts


def test_table_pattern_fixture_returns_records(monkeypatch: MonkeyPatch, caplog: LogCaptureFixture) -> None:
    organizations, contacts = _parse_records("staff_directory_table.html", "table", monkeypatch)
    assert len(organizations) == 1
    assert len(contacts) > 0
    by_name = {contact.full_name: contact for contact in contacts}
    assert by_name["Jordan Hale"].role == ContactRole.athletic_director
    assert by_name["Alex Kim"].role == ContactRole.athletic_director
    assert by_name["Riley Chen"].role == ContactRole.compliance_officer
    assert by_name["Morgan Diaz"].role == ContactRole.head_coach
    assert by_name["Sam Ortiz"].role == ContactRole.unknown
    assert by_name["Sam Ortiz"].title_raw == "Sports Information Director"
    assert by_name["Jordan Hale"].email == "jhale@example.edu"
    assert all(contact.confidence == 0.7 for contact in contacts)
    assert UNMAPPED_LOG in caplog.text


def test_definition_list_pattern_fixture_returns_records(monkeypatch: MonkeyPatch) -> None:
    organizations, contacts = _parse_records("staff_directory_dl.html", "definition_list", monkeypatch)
    assert len(organizations) == 1
    assert len(contacts) == 4
    by_name = {contact.full_name: contact for contact in contacts}
    assert by_name["Jordan Hale"].role == ContactRole.athletic_director
    assert by_name["Riley Chen"].role == ContactRole.compliance_officer
    assert by_name["Morgan Diaz"].role == ContactRole.head_coach
    assert by_name["Sam Ortiz"].role == ContactRole.unknown
    assert by_name["Riley Chen"].email == "rchen@example.edu"


def test_cards_pattern_fixture_returns_records(monkeypatch: MonkeyPatch) -> None:
    organizations, contacts = _parse_records("staff_directory_cards.html", "cards", monkeypatch)
    assert len(organizations) == 1
    assert organizations[0].org_type == OrgType.college
    assert len(contacts) == 4
    by_name = {contact.full_name: contact for contact in contacts}
    assert by_name["Jordan Hale"].role == ContactRole.athletic_director
    assert by_name["Riley Chen"].role == ContactRole.compliance_officer
    assert by_name["Morgan Diaz"].role == ContactRole.head_coach
    assert by_name["Sam Ortiz"].role == ContactRole.unknown


def test_unstructured_page_uses_claude_fallback(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        "backend.collectors.staff_directory.extract_directory_staff",
        lambda _text: [
            StaffPerson(
                name="Jordan Hale",
                title="Athletic Director",
                email="jhale@example.edu",
                phone=None,
            )
        ],
    )
    collector = StaffDirectoryCollector()
    try:
        parsed = collector.parse({"pages": [_page("staff_directory_unstructured.html", pattern="table")]})
        assert len(parsed) > 0
        assert parsed[0].people == []
        records = collector.to_records(parsed)
    finally:
        collector.close()
    contacts = [record for record in records if isinstance(record, Contact)]
    assert len(contacts) == 1
    assert contacts[0].confidence == 0.5
    assert contacts[0].role == ContactRole.athletic_director
