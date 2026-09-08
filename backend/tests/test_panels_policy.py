from datetime import datetime, timezone
from uuid import uuid4

from backend.models import Offer, Organization, OrgType, PolicyEvent, PolicyEventType
from backend.scoring.engine import _panels_signals, numeric_score
from backend.scoring.rubrics import PANELS_WEIGHT_POLICY_EVENT


def test_panels_recent_linked_policy_event_is_the_timing_signal() -> None:
    now = datetime.now(timezone.utc)
    org = Organization(
        name="Example College",
        org_type=OrgType.college,
        roster_size_estimate=800,
        state="VA",
        is_active=True,
    )
    linked_event = PolicyEvent(
        jurisdiction="VA",
        source_url="https://www.example.com/nil-policy",
        event_type=PolicyEventType.policy_amended,
        detected_at=now,
        content_hash="abc123",
        linked_organization_id=uuid4(),
    )
    with_event = _panels_signals(org, [], [linked_event], now)
    without_event = _panels_signals(org, [], [], now)
    assert with_event["recent_policy_event"] is True
    assert with_event["policy_event_value"] == 1.0
    assert with_event["linked_policy_event_ids"] == [str(linked_event.id)]
    assert without_event["recent_policy_event"] is False
    assert without_event["policy_event_value"] == 0.0
    assert numeric_score(Offer.panels, with_event) > numeric_score(Offer.panels, without_event)
    assert PANELS_WEIGHT_POLICY_EVENT == 35
