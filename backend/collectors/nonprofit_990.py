import logging
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from backend.app.config import get_settings
from backend.collectors.base import BaseCollector
from backend.compliance.minor_guard import is_minor_related
from backend.compliance.robots import hostname_of
from backend.models import Contact, ContactRole, Organization, OrgType

logger = logging.getLogger(__name__)

NTEE_MAJOR_GROUP = "N"
C_CODE = "3"
OFFICER_CONFIDENCE = 0.7


class Nonprofit990Collector(BaseCollector):
    def __init__(self) -> None:
        super().__init__(requests_per_second=2.0)

    @property
    def name(self) -> str:
        return "nonprofit_990"

    @property
    def allowed_domains(self) -> Sequence[str]:
        settings = get_settings()
        hosts = {
            hostname_of(settings.propublica_search_url),
            hostname_of(settings.propublica_organization_url.replace("{ein}", "1")),
        }
        return tuple(hosts)

    def fetch(self) -> dict[str, Any]:
        settings = get_settings()
        details: list[dict[str, Any]] = []
        search_pages: list[dict[str, Any]] = []
        for state in _target_states():
            page = 1
            while True:
                payload = self.fetch_json(
                    settings.propublica_search_url,
                    {
                        "state[id]": state,
                        "c_code[id]": C_CODE,
                        "page": page,
                    },
                )
                if payload is None:
                    break
                search_pages.append(payload)
                logger.info("nonprofit_990 search state=%s page=%s", state, page)
                organizations = payload.get("organizations")
                if not isinstance(organizations, list) or len(organizations) == 0:
                    break
                for item in organizations:
                    if not isinstance(item, dict):
                        continue
                    if not _is_ntee_major_group_n(item.get("ntee_code")):
                        continue
                    ein = item.get("ein")
                    if ein is None:
                        continue
                    detail_url = settings.propublica_organization_url.format(ein=ein)
                    detail = self.fetch_json(detail_url)
                    if detail is not None:
                        details.append(detail)
                num_pages = payload.get("num_pages")
                if isinstance(num_pages, int) and page >= num_pages:
                    break
                page += 1
        return {"search_pages": search_pages, "organizations": details}

    def parse(self, raw: object) -> list[dict[str, Any]]:
        if not isinstance(raw, dict):
            return []
        organizations = raw.get("organizations")
        if not isinstance(organizations, list):
            return []
        parsed: list[dict[str, Any]] = []
        for detail in organizations:
            if not isinstance(detail, dict):
                continue
            record = _parse_detail(detail)
            if record is not None:
                parsed.append(record)
        return parsed

    def to_records(self, parsed: object) -> Sequence[Organization | Contact]:
        if not isinstance(parsed, list):
            return []
        records: list[Organization | Contact] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            org = _organization_from_parsed(item)
            records.append(org)
            officers = item.get("officers")
            if isinstance(officers, list):
                source_url = item.get("source_url")
                source = source_url if isinstance(source_url, str) else ""
                for officer in officers:
                    if not isinstance(officer, dict):
                        continue
                    contact = _contact_from_officer(officer, source)
                    if contact is not None:
                        records.append(contact)
        return records


def _target_states() -> list[str]:
    return [part.strip().upper() for part in get_settings().target_states.split(",") if part.strip()]


def _is_ntee_major_group_n(ntee_code: object) -> bool:
    if not isinstance(ntee_code, str) or ntee_code == "":
        return False
    return ntee_code[0].upper() == NTEE_MAJOR_GROUP


def _parse_detail(detail: Mapping[str, Any]) -> dict[str, Any] | None:
    organization = detail.get("organization")
    if not isinstance(organization, dict):
        return None
    name = organization.get("name")
    if not isinstance(name, str) or name.strip() == "":
        return None
    ein = _ein_string(organization)
    if ein is None:
        return None
    ntee_code = organization.get("ntee_code")
    if not _is_ntee_major_group_n(ntee_code):
        return None
    filing = _most_recent_filing(detail)
    settings = get_settings()
    source_url = settings.propublica_organization_url.format(ein=organization.get("ein"))
    city = organization.get("city")
    state = organization.get("state")
    return {
        "name": name.strip(),
        "ein": ein,
        "city": city if isinstance(city, str) else None,
        "state": state if isinstance(state, str) else None,
        "ntee_code": ntee_code,
        "annual_revenue": _optional_decimal(filing.get("totrevenue") if filing else None),
        "program_expenses": _optional_decimal(filing.get("totfuncexpns") if filing else None),
        "fiscal_year": _optional_int(filing.get("tax_prd_yr") if filing else None),
        "org_type": _infer_org_type(name),
        "source_url": source_url,
        "officers": _officers_from(organization, filing),
    }


def _most_recent_filing(detail: Mapping[str, Any]) -> dict[str, Any] | None:
    filings = detail.get("filings_with_data")
    if not isinstance(filings, list) or len(filings) == 0:
        return None
    dated: list[dict[str, Any]] = []
    for filing in filings:
        if isinstance(filing, dict):
            dated.append(filing)
    if len(dated) == 0:
        return None
    return max(dated, key=lambda item: _optional_int(item.get("tax_prd_yr")) or -1)


def _officers_from(organization: Mapping[str, Any], filing: Mapping[str, Any] | None) -> list[dict[str, str | None]]:
    officers: list[dict[str, str | None]] = []
    sources: list[Mapping[str, Any]] = []
    if filing is not None:
        sources.append(filing)
    sources.append(organization)
    for source in sources:
        for key in ("officers", "people", "key_employees"):
            value = source.get(key)
            if isinstance(value, list):
                for item in value:
                    officer = _officer_from_mapping(item)
                    if officer is not None:
                        officers.append(officer)
        if filing is source:
            for index in range(1, 51):
                name = source.get(f"officer_name_{index}")
                title = source.get(f"officer_title_{index}")
                if isinstance(name, str) and name.strip() != "":
                    officers.append(
                        {
                            "full_name": name.strip(),
                            "title_raw": title.strip() if isinstance(title, str) else None,
                        }
                    )
    careof = _careof_person(organization.get("careofname"))
    if careof is not None:
        officers.append({"full_name": careof, "title_raw": None})
    unique: list[dict[str, str | None]] = []
    seen: set[str] = set()
    for officer in officers:
        name = officer["full_name"]
        if name is None or name in seen:
            continue
        seen.add(name)
        unique.append(officer)
    return unique


def _officer_from_mapping(item: object) -> dict[str, str | None] | None:
    if not isinstance(item, dict):
        return None
    name = item.get("name") or item.get("officer_name") or item.get("full_name")
    if not isinstance(name, str) or name.strip() == "":
        return None
    title = item.get("title") or item.get("officer_title") or item.get("title_raw")
    return {
        "full_name": name.strip(),
        "title_raw": title.strip() if isinstance(title, str) else None,
    }


def _careof_person(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lstrip("%").strip()
    if cleaned == "":
        return None
    parts = [part for part in cleaned.replace(".", " ").split() if part]
    if len(parts) < 2:
        return None
    letters = "".join(parts)
    if not letters.isalpha():
        return None
    return cleaned


def _ein_string(organization: Mapping[str, Any]) -> str | None:
    strein = organization.get("strein")
    if isinstance(strein, str) and strein.strip() != "":
        return strein.strip()
    ein = organization.get("ein")
    if isinstance(ein, int):
        return str(ein)
    if isinstance(ein, str) and ein.strip() != "":
        return ein.strip()
    return None


def _infer_org_type(name: str) -> OrgType:
    lowered = name.lower()
    if "booster" in lowered or "boosters" in lowered:
        return OrgType.booster_club
    if "collective" in lowered:
        return OrgType.nil_collective
    return OrgType.youth_sports_org


def _optional_decimal(value: object) -> Decimal | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str) and value.strip() != "":
        try:
            return Decimal(value)
        except (InvalidOperation, ValueError):
            return None
    return None


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _organization_from_parsed(item: Mapping[str, Any]) -> Organization:
    name = item["name"]
    assert isinstance(name, str)
    ein = item["ein"]
    assert isinstance(ein, str)
    org_type = item["org_type"]
    assert isinstance(org_type, OrgType)
    source_url = item.get("source_url")
    return Organization(
        name=name,
        org_type=org_type,
        city=item.get("city") if isinstance(item.get("city"), str) else None,
        state=item.get("state") if isinstance(item.get("state"), str) else None,
        ein=ein,
        annual_revenue=item.get("annual_revenue") if isinstance(item.get("annual_revenue"), Decimal) else None,
        program_expenses=(
            item.get("program_expenses") if isinstance(item.get("program_expenses"), Decimal) else None
        ),
        fiscal_year=item.get("fiscal_year") if isinstance(item.get("fiscal_year"), int) else None,
        source_urls=[source_url] if isinstance(source_url, str) else None,
        is_active=True,
    )


def _contact_from_officer(officer: Mapping[str, Any], source_url: str) -> Contact | None:
    full_name = officer.get("full_name")
    if not isinstance(full_name, str) or full_name.strip() == "":
        return None
    first_name, last_name = _split_name(full_name)
    title_raw = officer.get("title_raw")
    return Contact(
        full_name=full_name,
        first_name=first_name,
        last_name=last_name,
        title_raw=title_raw if isinstance(title_raw, str) else None,
        role=ContactRole.board_officer,
        source_url=source_url or None,
        confidence=OFFICER_CONFIDENCE,
        is_minor_related=is_minor_related(source_url, full_name, ""),
    )


def _split_name(full_name: str) -> tuple[str | None, str | None]:
    parts = full_name.split()
    if len(parts) == 0:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return parts[0], parts[-1]


def main() -> None:
    Nonprofit990Collector().run()


if __name__ == "__main__":
    main()
