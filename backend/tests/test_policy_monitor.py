from pathlib import Path

from backend.app.config import get_settings
from backend.collectors.policy_monitor import ParsedPage, PolicyMonitorCollector
from backend.models import PolicyEvent
from pytest import MonkeyPatch

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_parse_policy_fixture_returns_records() -> None:
    html = (FIXTURES / "policy_page.html").read_text()
    collector = PolicyMonitorCollector()
    try:
        parsed = collector.parse(
            {
                "pages": [
                    {
                        "jurisdiction": "VA",
                        "url": "https://www.example.com/nil-policy-placeholder",
                        "category": "nil_policy",
                        "html": html,
                    }
                ],
                "snapshots": {},
            }
        )
        assert len(parsed) > 0
        assert parsed[0].text != ""
        assert "NIL" in parsed[0].text or "likeness" in parsed[0].text.lower()
        assert parsed[0].content_hash != ""
        assert parsed[0].previous_hash is None
    finally:
        collector.close()


def test_to_records_first_run_writes_no_policy_events(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    hashes_path = tmp_path / "hashes.json"
    monkeypatch.setenv("WATCHLIST_HASHES_PATH", str(hashes_path))
    get_settings.cache_clear()
    collector = PolicyMonitorCollector()
    try:
        page = ParsedPage(
            jurisdiction="VA",
            url="https://www.example.com/nil-policy-placeholder",
            category="nil_policy",
            text="Student-athletes may earn compensation for NIL activity.",
            content_hash="abc",
            previous_hash=None,
            previous_text=None,
        )
        records = collector.to_records([page])
        assert records == []
        assert not any(isinstance(record, PolicyEvent) for record in records)
        assert hashes_path.is_file()
    finally:
        collector.close()
        get_settings.cache_clear()


def test_to_records_change_writes_one_policy_event(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    hashes_path = tmp_path / "hashes.json"
    monkeypatch.setenv("WATCHLIST_HASHES_PATH", str(hashes_path))
    monkeypatch.setattr(
        "backend.collectors.policy_monitor.compare_versions",
        lambda _previous, _new: "Athletes must now disclose every NIL deal to compliance within 7 days.",
    )
    get_settings.cache_clear()
    collector = PolicyMonitorCollector()
    try:
        page = ParsedPage(
            jurisdiction="TEST",
            url="http://127.0.0.1:8765/page.html",
            category="nil_policy",
            text="Athletes must disclose NIL deals. Effective date: September 1, 2026",
            content_hash="newhash",
            previous_hash="oldhash",
            previous_text="Athletes may earn NIL compensation with no disclosure.",
        )
        records = collector.to_records([page])
        assert len(records) == 1
        event = records[0]
        assert isinstance(event, PolicyEvent)
        assert event.jurisdiction == "TEST"
        assert event.summary is not None
        assert "disclose" in event.summary.lower()
        assert event.effective_date is not None
    finally:
        collector.close()
        get_settings.cache_clear()
