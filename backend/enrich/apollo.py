import logging
import time
from typing import Any

import httpx

from backend.compliance.audit import log_fetch
from backend.enrich.keys import is_configured

logger = logging.getLogger(__name__)

_MIN_INTERVAL_SECONDS = 0.2
_PERSON_KEYS = (
    "id",
    "first_name",
    "last_name",
    "name",
    "title",
    "email",
    "has_email",
)
PERSON_TITLES: tuple[str, ...] = (
    "Athletic Director",
    "Director of Athletics",
    "Executive Director",
    "Head Coach",
    "Compliance Officer",
    "Assistant Athletic Director",
    "Owner",
)


class ApolloError(Exception):
    """Raised when an Apollo HTTP call fails after being logged."""


def map_people(payload: object) -> list[dict[str, object]]:
    mapped: list[dict[str, object]] = []
    for item in _people_from_payload(payload):
        row = _person_row(item)
        if row:
            mapped.append(row)
    return mapped


def email_from_match(payload: object) -> str | None:
    person = _match_person(payload)
    if person is None:
        return None
    return _clean_email(person.get("email"))


def first_name_from_match(payload: object) -> str | None:
    person = _match_person(payload)
    if person is None:
        return None
    value = person.get("first_name")
    if isinstance(value, str) and value.strip() != "":
        return value.strip()
    return None


def last_name_from_match(payload: object) -> str | None:
    person = _match_person(payload)
    if person is None:
        return None
    return _clean_last_name(person.get("last_name"))


def title_from_match(payload: object) -> str | None:
    person = _match_person(payload)
    if person is None:
        return None
    value = person.get("title")
    if isinstance(value, str) and value.strip() != "":
        return value.strip()
    return None


def _match_person(payload: object) -> dict[str, object] | None:
    if not isinstance(payload, dict):
        return None
    person = payload.get("person")
    if isinstance(person, dict):
        return person
    return payload


def _people_from_payload(payload: object) -> list[object]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("people", "contacts"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    data = payload.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("people", "contacts"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


def _person_row(item: object) -> dict[str, object]:
    if not isinstance(item, dict):
        return {}
    row: dict[str, object] = {}
    for key in _PERSON_KEYS:
        if key not in item:
            continue
        value = item[key]
        if key == "last_name":
            cleaned = _clean_last_name(value)
            if cleaned is not None:
                row[key] = cleaned
            continue
        if key == "email":
            cleaned_email = _clean_email(value)
            if cleaned_email is not None:
                row[key] = cleaned_email
            continue
        row[key] = value
    return row


def _clean_last_name(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if stripped == "" or "*" in stripped:
        return None
    return stripped


def _clean_email(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if stripped == "" or "@" not in stripped:
        return None
    return stripped


class ApolloClient:
    def __init__(self, *, api_key: str, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._last_request_at = 0.0
        self._client = httpx.Client(
            headers={
                "x-api-key": api_key,
                "Content-Type": "application/json",
                "Cache-Control": "no-cache",
            },
            timeout=30.0,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ApolloClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def search_people(
        self,
        *,
        organization_name: str,
        domain: str | None = None,
        location: str | None = None,
        per_page: int = 10,
    ) -> object:
        body: dict[str, object] = {
            "q_organization_name": organization_name,
            "person_titles": list(PERSON_TITLES),
            "include_similar_titles": False,
            "per_page": per_page,
            "page": 1,
        }
        if domain is not None and domain != "":
            body["q_organization_domains_list"] = [domain]
        if location is not None and location != "":
            body["organization_locations"] = [location]
        return self._request("POST", "/api/v1/mixed_people/api_search", json_body=body)

    def match_person(
        self,
        *,
        person_id: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        name: str | None = None,
        organization_name: str | None = None,
        domain: str | None = None,
    ) -> object:
        body: dict[str, object] = {}
        if person_id:
            body["id"] = person_id
        if first_name:
            body["first_name"] = first_name
        if last_name:
            body["last_name"] = last_name
        if name:
            body["name"] = name
        if organization_name:
            body["organization_name"] = organization_name
        if domain:
            body["domain"] = domain
        return self._request("POST", "/api/v1/people/match", json_body=body)

    def _throttle(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_request_at
        if self._last_request_at > 0.0 and elapsed < _MIN_INTERVAL_SECONDS:
            time.sleep(_MIN_INTERVAL_SECONDS - elapsed)
        self._last_request_at = time.monotonic()

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> object:
        url = f"{self._base_url}{path}"
        action = f"{method.lower()} {path}"
        self._throttle()
        response: httpx.Response | None = None
        try:
            response = self._client.request(method, url, json=json_body)
            log_fetch(
                actor="apollo",
                action=action,
                target_url=str(response.url),
                robots_allowed=None,
                response_code=response.status_code,
            )
            response.raise_for_status()
            try:
                return response.json()
            except ValueError as exc:
                raise ApolloError("Apollo returned non-JSON") from exc
        except httpx.HTTPStatusError as exc:
            logger.exception("Apollo HTTP status error for %s %s", method, url)
            raise ApolloError(str(exc)) from exc
        except httpx.HTTPError as exc:
            logger.exception("Apollo HTTP error for %s %s", method, url)
            if response is None:
                log_fetch(
                    actor="apollo",
                    action=action,
                    target_url=url,
                    robots_allowed=None,
                    notes=str(exc),
                )
            raise ApolloError(str(exc)) from exc


__all__ = [
    "ApolloClient",
    "ApolloError",
    "PERSON_TITLES",
    "email_from_match",
    "first_name_from_match",
    "is_configured",
    "last_name_from_match",
    "map_people",
    "title_from_match",
]
