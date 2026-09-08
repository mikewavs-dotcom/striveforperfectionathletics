from backend.models import Offer, OrgType
from backend.scoring.engine import numeric_score
from backend.scoring.rubrics import CAMPS_RUBRIC, SCORE_SCALE


def _camps_signals(
    *,
    revenue_value: float | None,
    excluded: list[str],
) -> dict[str, object]:
    return {
        "annual_revenue": 250000 if revenue_value is not None else None,
        "revenue_above_threshold": True if revenue_value == 1.0 else False if revenue_value == 0.0 else None,
        "revenue_value": revenue_value,
        "roster_size_estimate": 80,
        "large_roster": True,
        "roster_value": 1.0,
        "events_per_year": 2,
        "low_events": True,
        "low_events_value": 1.0,
        "org_type": OrgType.youth_sports_org.value,
        "org_type_value": 1.0,
        "has_coach_or_executive_director": False,
        "coach_or_ed_value": 0.0,
        "state": "VA",
        "target_states": ["VA"],
        "proximity": True,
        "proximity_value": 1.0,
        "excluded_components": excluded,
    }


def test_same_input_produces_same_numeric_score_twice() -> None:
    signals = _camps_signals(revenue_value=1.0, excluded=[])
    first = numeric_score(Offer.camps, signals)
    second = numeric_score(Offer.camps, signals)
    assert first == second
    assert 0 <= first <= SCORE_SCALE


def test_missing_revenue_is_excluded_and_weights_renormalized() -> None:
    scored_zero_revenue = numeric_score(
        Offer.camps,
        _camps_signals(revenue_value=0.0, excluded=[]),
    )
    missing_revenue = numeric_score(
        Offer.camps,
        _camps_signals(revenue_value=None, excluded=["revenue"]),
    )
    assert missing_revenue > scored_zero_revenue
    included_weight = sum(weight for name, weight in CAMPS_RUBRIC.items() if name != "revenue")
    expected = int(
        round(
            SCORE_SCALE
            * (
                CAMPS_RUBRIC["roster"] * 1.0
                + CAMPS_RUBRIC["low_events"] * 1.0
                + CAMPS_RUBRIC["org_type"] * 1.0
                + CAMPS_RUBRIC["coach_or_ed"] * 0.0
                + CAMPS_RUBRIC["proximity"] * 1.0
            )
            / included_weight
        )
    )
    assert missing_revenue == expected
