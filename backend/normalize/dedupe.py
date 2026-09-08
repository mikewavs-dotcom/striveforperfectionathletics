from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.models import Contact, Organization, PolicyEvent, Score, Sponsor
from backend.normalize.addresses import standardize_organization_address
from backend.normalize.entities import canonical_name


def apply_entity_and_address_normalization(session: Session) -> None:
    organizations = list(session.scalars(select(Organization)))
    for org in organizations:
        org.canonical_name = canonical_name(org.name) if org.name.strip() != "" else None
        street, city, state, postal_code = standardize_organization_address(
            org.street,
            org.city,
            org.state,
            org.postal_code,
        )
        org.street = street
        org.city = city
        org.state = state
        org.postal_code = postal_code
    session.flush()


def _ein_key(ein: str | None) -> str | None:
    if ein is None:
        return None
    digits = "".join(character for character in ein if character.isdigit())
    if digits == "":
        return None
    return digits


def _name_key(org: Organization) -> tuple[str, str, str] | None:
    name = org.canonical_name or canonical_name(org.name)
    city = org.city
    state = org.state
    if name == "" or city is None or city.strip() == "" or state is None or state.strip() == "":
        return None
    return (name, city.strip().lower(), state.strip().upper())


def _prefer(winner: Organization, loser: Organization) -> tuple[Organization, Organization]:
    winner_filled = sum(
        1
        for value in (
            winner.annual_revenue,
            winner.program_expenses,
            winner.ein,
            winner.street,
        )
        if value is not None
    )
    loser_filled = sum(
        1
        for value in (
            loser.annual_revenue,
            loser.program_expenses,
            loser.ein,
            loser.street,
        )
        if value is not None
    )
    if loser_filled > winner_filled:
        return loser, winner
    return winner, loser


def _merge_fields(keeper: Organization, duplicate: Organization) -> None:
    if keeper.ein is None:
        keeper.ein = duplicate.ein
    if keeper.annual_revenue is None:
        keeper.annual_revenue = duplicate.annual_revenue
    if keeper.program_expenses is None:
        keeper.program_expenses = duplicate.program_expenses
    if keeper.fiscal_year is None:
        keeper.fiscal_year = duplicate.fiscal_year
    if keeper.street is None:
        keeper.street = duplicate.street
    if keeper.city is None:
        keeper.city = duplicate.city
    if keeper.state is None:
        keeper.state = duplicate.state
    if keeper.postal_code is None:
        keeper.postal_code = duplicate.postal_code
    if keeper.canonical_name is None:
        keeper.canonical_name = duplicate.canonical_name
    urls = list(keeper.source_urls or [])
    for url in duplicate.source_urls or []:
        if url not in urls:
            urls.append(url)
    keeper.source_urls = urls or None


def _repoint(session: Session, keeper_id: UUID, duplicate_id: UUID) -> None:
    session.execute(
        update(Contact).where(Contact.organization_id == duplicate_id).values(organization_id=keeper_id)
    )
    session.execute(
        update(Score).where(Score.organization_id == duplicate_id).values(organization_id=keeper_id)
    )
    session.execute(
        update(PolicyEvent)
        .where(PolicyEvent.linked_organization_id == duplicate_id)
        .values(linked_organization_id=keeper_id)
    )
    session.execute(
        update(Sponsor)
        .where(Sponsor.detected_on_organization_id == duplicate_id)
        .values(detected_on_organization_id=keeper_id)
    )
    session.execute(
        update(Sponsor)
        .where(Sponsor.matched_organization_id == duplicate_id)
        .values(matched_organization_id=keeper_id)
    )


def _merge_pair(session: Session, first: Organization, second: Organization) -> Organization:
    keeper, duplicate = _prefer(first, second)
    _merge_fields(keeper, duplicate)
    _repoint(session, keeper.id, duplicate.id)
    session.delete(duplicate)
    session.flush()
    return keeper


def _merge_group(session: Session, group: Sequence[Organization]) -> None:
    if len(group) < 2:
        return
    keeper = group[0]
    for duplicate in group[1:]:
        keeper = _merge_pair(session, keeper, duplicate)


def dedupe_organizations(session: Session) -> int:
    apply_entity_and_address_normalization(session)
    organizations = list(session.scalars(select(Organization)))
    before = len(organizations)
    by_ein: dict[str, list[Organization]] = {}
    for org in organizations:
        ein_key = _ein_key(org.ein)
        if ein_key is None:
            continue
        by_ein.setdefault(ein_key, []).append(org)
    for group in by_ein.values():
        if len(group) > 1:
            _merge_group(session, group)
    session.flush()
    remaining = list(session.scalars(select(Organization)))
    by_name: dict[tuple[str, str, str], list[Organization]] = {}
    for org in remaining:
        name_key = _name_key(org)
        if name_key is None:
            continue
        by_name.setdefault(name_key, []).append(org)
    for group in by_name.values():
        if len(group) > 1:
            eins = {_ein_key(org.ein) for org in group if _ein_key(org.ein) is not None}
            if len(eins) > 1:
                continue
            _merge_group(session, group)
    session.flush()
    after = len(list(session.scalars(select(Organization))))
    return before - after
