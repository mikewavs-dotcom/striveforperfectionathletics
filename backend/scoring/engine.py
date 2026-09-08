import time
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

import anthropic
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.models import Contact, Offer, Organization, OrgType, PolicyEvent, Score, Sponsor
from backend.scoring import rubrics

CLAUDE_MODEL = "claude-sonnet-4-6"


def score_organization(org: Organization, session: Session) -> list[Score]:
    """Return exactly three Score rows for camps, panels, and media.

    Numeric scores are computed in Python from rubric weights. A missing
    input (for example annual_revenue is null) does not score that component
    as zero: the component is dropped and the remaining weights are
    renormalized to sum to 1 before scaling to 0-100. Boolean observations
    such as "has a coach" are never null; they are 0 or 1.

    The Claude API writes the one-sentence rationale only. It never
    produces the number.
    """
    signals_by_offer = collect_signals(org, session)
    now = datetime.now(timezone.utc)
    scores: list[Score] = []
    for offer in (Offer.camps, Offer.panels, Offer.media):
        signals = signals_by_offer[offer]
        value = numeric_score(offer, signals)
        rationale = write_rationale(value, offer, signals)
        if rationale.strip() == "":
            raise ValueError("Score rationale is empty")
        row = _upsert_score(
            session,
            org_id=org.id,
            offer=offer,
            value=value,
            rationale=rationale,
            signals=signals,
            scored_at=now,
        )
        scores.append(row)
    return scores


def collect_signals(org: Organization, session: Session) -> dict[Offer, dict[str, object]]:
    contacts = list(session.scalars(select(Contact).where(Contact.organization_id == org.id)))
    policy_events = list(
        session.scalars(
            select(PolicyEvent).where(
                or_(
                    PolicyEvent.linked_organization_id == org.id,
                    PolicyEvent.jurisdiction == (org.state or ""),
                )
            )
        )
    )
    sponsors = list(
        session.scalars(
            select(Sponsor).where(
                or_(
                    Sponsor.detected_on_organization_id == org.id,
                    Sponsor.matched_organization_id == org.id,
                )
            )
        )
    )
    matched_ids = [
        sponsor.matched_organization_id
        for sponsor in sponsors
        if sponsor.matched_organization_id is not None
    ]
    matched_orgs = list(
        session.scalars(select(Organization).where(Organization.id.in_(matched_ids)))
    ) if matched_ids else []
    target_states = [
        part.strip().upper()
        for part in get_settings().target_states.split(",")
        if part.strip()
    ]
    now = datetime.now(timezone.utc)
    return {
        Offer.camps: _camps_signals(org, contacts, target_states),
        Offer.panels: _panels_signals(org, contacts, policy_events, now),
        Offer.media: _media_signals(org, contacts, sponsors, matched_orgs),
    }


def numeric_score(offer: Offer, signals: Mapping[str, object]) -> int:
    """Compute a 0-100 score from rubric weights.

    Null numeric inputs are excluded, not treated as zero. Remaining
    component weights are renormalized so they still sum to the full scale.
    """
    rubric = rubrics.RUBRICS[offer]
    contributions: list[tuple[int, float]] = []
    excluded = signals.get("excluded_components")
    excluded_set = set(excluded) if isinstance(excluded, list) else set()
    for component, weight in rubric.items():
        if component in excluded_set:
            continue
        raw = signals.get(f"{component}_value")
        if not isinstance(raw, (int, float)):
            continue
        contributions.append((weight, float(raw)))
    if len(contributions) == 0:
        return 0
    total_weight = sum(weight for weight, _value in contributions)
    if total_weight <= 0:
        return 0
    weighted = sum(weight * value for weight, value in contributions)
    return int(round(rubrics.SCORE_SCALE * weighted / total_weight))


def write_rationale(score: int, offer: Offer, signals: Mapping[str, object]) -> str:
    client = anthropic.Anthropic(api_key=get_settings().anthropic_api_key)
    facts = _facts_for_prompt(signals)
    prompt = (
        f"Write one sentence a salesperson can paste into an email explaining why "
        f"this organization scores {score} out of 100 for {offer.value} deals. "
        f"Use only these facts: {facts}. Do not invent facts. Do not mention null "
        f"or missing fields. One sentence, 12 to 24 words, no quotes."
    )
    message: anthropic.types.Message | None = None
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            message = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=80,
                messages=[{"role": "user", "content": prompt}],
            )
            break
        except (anthropic.RateLimitError, anthropic.APIConnectionError) as exc:
            last_error = exc
            time.sleep(2**attempt)
    if message is None:
        if last_error is not None:
            raise last_error
        raise RuntimeError("Claude rationale request failed")
    text = _message_text(message.content)
    words = text.split()
    if len(words) > 29:
        text = " ".join(words[:29])
    return text.strip()


def _upsert_score(
    session: Session,
    *,
    org_id: UUID,
    offer: Offer,
    value: int,
    rationale: str,
    signals: Mapping[str, object],
    scored_at: datetime,
) -> Score:
    existing = session.scalar(
        select(Score).where(Score.organization_id == org_id, Score.offer == offer)
    )
    payload = _jsonable(dict(signals))
    if existing is None:
        row = Score(
            organization_id=org_id,
            offer=offer,
            score=value,
            rationale=rationale,
            signals=payload,
            model_version=rubrics.SCORING_MODEL_VERSION,
            scored_at=scored_at,
        )
        session.add(row)
        return row
    existing.score = value
    existing.rationale = rationale
    existing.signals = payload
    existing.model_version = rubrics.SCORING_MODEL_VERSION
    existing.scored_at = scored_at
    return existing


def _camps_signals(
    org: Organization,
    contacts: Sequence[Contact],
    target_states: Sequence[str],
) -> dict[str, object]:
    excluded: list[str] = []
    revenue = _decimal_number(org.annual_revenue)
    roster = org.roster_size_estimate
    events = org.events_per_year
    if revenue is None:
        excluded.append("revenue")
        revenue_value: float | None = None
        revenue_above: bool | None = None
    else:
        revenue_above = revenue >= rubrics.CAMPS_REVENUE_THRESHOLD
        revenue_value = 1.0 if revenue_above else 0.0
    if roster is None:
        excluded.append("roster")
        roster_value: float | None = None
        large_roster: bool | None = None
    else:
        large_roster = roster >= rubrics.CAMPS_LARGE_ROSTER_MIN
        roster_value = 1.0 if large_roster else 0.0
    if events is None:
        excluded.append("low_events")
        low_events_value: float | None = None
        low_events: bool | None = None
    else:
        low_events = events <= rubrics.CAMPS_LOW_EVENTS_MAX
        low_events_value = 1.0 if low_events else 0.0
    org_type = org.org_type.value
    org_type_match = org_type in rubrics.CAMPS_YOUTH_OR_TRAVEL_TYPES
    roles = {contact.role.value for contact in contacts if contact.role is not None}
    has_coach_or_ed = not roles.isdisjoint(rubrics.CAMPS_COACH_OR_ED_ROLES)
    state = org.state
    proximity = state is not None and state.upper() in {item.upper() for item in target_states}
    return {
        "annual_revenue": revenue,
        "revenue_above_threshold": revenue_above,
        "revenue_value": revenue_value,
        "roster_size_estimate": roster,
        "large_roster": large_roster,
        "roster_value": roster_value,
        "events_per_year": events,
        "low_events": low_events,
        "low_events_value": low_events_value,
        "org_type": org_type,
        "org_type_value": 1.0 if org_type_match else 0.0,
        "has_coach_or_executive_director": has_coach_or_ed,
        "coach_or_ed_value": 1.0 if has_coach_or_ed else 0.0,
        "state": state,
        "target_states": list(target_states),
        "proximity": proximity,
        "proximity_value": 1.0 if proximity else 0.0,
        "excluded_components": excluded,
    }


def _panels_signals(
    org: Organization,
    contacts: Sequence[Contact],
    policy_events: Sequence[PolicyEvent],
    now: datetime,
) -> dict[str, object]:
    excluded: list[str] = []
    cutoff = now - timedelta(days=rubrics.PANELS_POLICY_RECENT_DAYS)
    recent_events = [
        event
        for event in policy_events
        if event.detected_at >= cutoff
    ]
    has_recent_policy = len(recent_events) > 0
    linked_ids = [
        str(event.id)
        for event in recent_events
        if event.linked_organization_id is not None
    ]
    roles = {contact.role.value for contact in contacts if contact.role is not None}
    has_compliance = not roles.isdisjoint(rubrics.PANELS_COMPLIANCE_ROLES)
    org_type = org.org_type.value
    school_or_college = org_type in rubrics.PANELS_SCHOOL_OR_COLLEGE_TYPES
    size = org.roster_size_estimate
    if size is None:
        size = org.location_count
    if size is None:
        excluded.append("institution_size")
        size_value: float | None = None
        large_institution: bool | None = None
    else:
        large_institution = size >= rubrics.PANELS_INSTITUTION_SIZE_MIN
        size_value = 1.0 if large_institution else 0.0
    prior_contact = False
    return {
        "recent_policy_event": has_recent_policy,
        "policy_event_value": 1.0 if has_recent_policy else 0.0,
        "policy_event_count": len(recent_events),
        "linked_policy_event_ids": linked_ids,
        "has_compliance_officer": has_compliance,
        "compliance_officer_value": 1.0 if has_compliance else 0.0,
        "org_type": org_type,
        "school_or_college": school_or_college,
        "school_or_college_value": 1.0 if school_or_college else 0.0,
        "institution_size": size,
        "large_institution": large_institution,
        "institution_size_value": size_value,
        "prior_contact": prior_contact,
        "no_prior_contact": not prior_contact,
        "no_prior_contact_value": 1.0 if not prior_contact else 0.0,
        "excluded_components": excluded,
    }


def _media_signals(
    org: Organization,
    contacts: Sequence[Contact],
    sponsors: Sequence[Sponsor],
    matched_orgs: Sequence[Organization],
) -> dict[str, object]:
    excluded: list[str] = []
    sponsor_count = len(sponsors)
    sponsor_names = [sponsor.brand_name for sponsor in sponsors]
    has_sponsors = sponsor_count > 0
    multi_location = any(
        matched.location_count is not None
        and matched.location_count >= rubrics.MEDIA_SPONSOR_MULTI_LOCATION_MIN
        for matched in matched_orgs
    )
    revenue = _decimal_number(org.annual_revenue)
    if revenue is None:
        excluded.append("revenue")
        revenue_value: float | None = None
        revenue_above: bool | None = None
    else:
        revenue_above = revenue >= rubrics.MEDIA_REVENUE_THRESHOLD
        revenue_value = 1.0 if revenue_above else 0.0
    audience = org.google_review_count
    if audience is None:
        audience = org.roster_size_estimate
    if audience is None:
        excluded.append("audience")
        audience_value: float | None = None
        large_audience: bool | None = None
    else:
        large_audience = audience >= rubrics.MEDIA_AUDIENCE_REVIEW_MIN
        audience_value = 1.0 if large_audience else 0.0
    roles = {contact.role.value for contact in contacts if contact.role is not None}
    has_marketing = not roles.isdisjoint(rubrics.MEDIA_MARKETING_ROLES)
    return {
        "sponsor_count": sponsor_count,
        "sponsor_names": sponsor_names,
        "sponsors_value": 1.0 if has_sponsors else 0.0,
        "sponsor_multi_location": multi_location,
        "sponsor_locations_value": 1.0 if multi_location else 0.0,
        "annual_revenue": revenue,
        "revenue_above_threshold": revenue_above,
        "revenue_value": revenue_value,
        "audience_size_proxy": audience,
        "large_audience": large_audience,
        "audience_value": audience_value,
        "has_marketing_contact": has_marketing,
        "marketing_contact_value": 1.0 if has_marketing else 0.0,
        "excluded_components": excluded,
    }


def _decimal_number(value: Decimal | int | float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bool):
        return None
    return float(value)


def _jsonable(value: object) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return str(value)


def _facts_for_prompt(signals: Mapping[str, object]) -> str:
    parts: list[str] = []
    for key, value in signals.items():
        if key.endswith("_value") or key == "excluded_components":
            continue
        if value is None:
            continue
        parts.append(f"{key}={value}")
    return "; ".join(parts)


def _message_text(content: Sequence[object]) -> str:
    parts: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
    return " ".join(parts).strip()


def score_all_organizations(session: Session) -> int:
    link_policy_events(session)
    organizations = list(session.scalars(select(Organization)))
    count = 0
    for org in organizations:
        score_organization(org, session)
        count += 1
    session.commit()
    return count


def link_policy_events(session: Session) -> int:
    """Attach unlinked policy events to an organization in that jurisdiction.

    A policy_events row has a single organization FK. When several schools
    share a jurisdiction, the FK stays null and collect_signals still treats
    jurisdiction == organization.state as a linked timing signal for panels.
    """
    events = list(
        session.scalars(select(PolicyEvent).where(PolicyEvent.linked_organization_id.is_(None)))
    )
    linked = 0
    panel_types = {OrgType.college, OrgType.school_district, OrgType.high_school}
    for event in events:
        jurisdiction = event.jurisdiction.strip()
        if jurisdiction == "":
            continue
        matches = list(
            session.scalars(
                select(Organization).where(
                    Organization.state == jurisdiction,
                    Organization.org_type.in_(panel_types),
                )
            )
        )
        if len(matches) != 1:
            continue
        event.linked_organization_id = matches[0].id
        linked += 1
    session.flush()
    return linked

