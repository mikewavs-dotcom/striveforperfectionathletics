import json
from pathlib import Path

from backend.collectors.nonprofit_990 import Nonprofit990Collector
from backend.models import Organization

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_parse_propublica_fixtures_returns_records() -> None:
    search = json.loads((FIXTURES / "propublica_search.json").read_text())
    org = json.loads((FIXTURES / "propublica_org.json").read_text())
    assert len(search["organizations"]) > 0
    collector = Nonprofit990Collector()
    try:
        parsed = collector.parse({"organizations": [org]})
        assert len(parsed) > 0
        records = collector.to_records(parsed)
        organizations = [record for record in records if isinstance(record, Organization)]
        assert len(organizations) > 0
        assert organizations[0].name == "Fairfax Soccer Club"
        assert organizations[0].ein is not None
        assert organizations[0].org_type is not None
    finally:
        collector.close()
