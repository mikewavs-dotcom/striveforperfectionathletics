import logging
import time
from typing import Any

import httpx

from backend.compliance.audit import log_fetch

logger = logging.getLogger(__name__)

_MIN_INTERVAL_SECONDS = 0.2
_PLACEHOLDER_PREFIX = "replace-with-"
_LEAD_CORE_VARIABLES = ["firstName", "lastName", "company", "organizationId"]
_CAMPAIGN_KEYS = ("id", "name", "status")
_ACCOUNT_KEYS = ("id", "email", "isActive")


class ReachInboxError(Exception):
    """Raised when a ReachInbox HTTP call fails after being logged."""


def is_configured(api_key: str) -> bool:
    stripped = api_key.strip()
    if stripped == "":
        return False
    return not stripped.lower().startswith(_PLACEHOLDER_PREFIX)


def map_campaigns(payload: object) -> list[dict[str, object]]:
    mapped: list[dict[str, object]] = []
    for item in _list_from_payload(payload):
        row = _pick_keys(item, _CAMPAIGN_KEYS)
        if row:
            mapped.append(row)
    return mapped


def map_accounts(payload: object) -> list[dict[str, object]]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    emails: object
    if isinstance(data, dict):
        emails = data.get("emailsConnected")
    else:
        emails = data
    if not isinstance(emails, list):
        return []
    mapped: list[dict[str, object]] = []
    for item in emails:
        row = _pick_keys(item, _ACCOUNT_KEYS)
        if row:
            mapped.append(row)
    return mapped


def _list_from_payload(payload: object) -> list[object]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return data
    return []


def _pick_keys(item: object, keys: tuple[str, ...]) -> dict[str, object]:
    if not isinstance(item, dict):
        return {}
    return {key: item[key] for key in keys if key in item}


class ReachInboxClient:
    def __init__(self, *, api_key: str, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._last_request_at = 0.0
        self._client = httpx.Client(
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ReachInboxClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def list_campaigns(self) -> object:
        return self._request(
            "GET",
            "/api/v1/campaigns/all",
            params={"sort": "newest", "offset": "0", "limit": "50", "filter": "All"},
        )

    def campaign_status(self, campaign_id: int) -> object:
        return self._request(
            "GET",
            "/api/v1/campaigns/status",
            params={"campaignId": str(campaign_id)},
        )

    def create_campaign(self, name: str) -> object:
        return self._request("POST", "/api/v1/campaigns/create", json_body={"name": name})

    def start_campaign(self, campaign_id: int) -> object:
        return self._request(
            "POST",
            "/api/v1/campaigns/start",
            json_body={"campaignId": campaign_id},
        )

    def pause_campaign(self, campaign_id: int) -> object:
        return self._request(
            "POST",
            "/api/v1/campaigns/pause",
            json_body={"campaignId": campaign_id},
        )

    def add_leads(self, campaign_id: int, leads: list[dict[str, str]]) -> object:
        return self._request(
            "POST",
            "/api/v1/leads/add",
            json_body={
                "campaignId": str(campaign_id),
                "leads": leads,
                "newCoreVariables": list(_LEAD_CORE_VARIABLES),
                "duplicates": [],
            },
        )

    def list_accounts(self) -> object:
        return self._request(
            "GET",
            "/api/v1/account/all",
            params={
                "contains": "",
                "status": "all",
                "limit": "100",
                "offset": "0",
            },
        )

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
        params: dict[str, str] | None = None,
    ) -> object:
        url = f"{self._base_url}{path}"
        action = f"{method.lower()} {path}"
        self._throttle()
        response: httpx.Response | None = None
        try:
            response = self._client.request(method, url, json=json_body, params=params)
            log_fetch(
                actor="reachinbox",
                action=action,
                target_url=str(response.url),
                robots_allowed=None,
                response_code=response.status_code,
            )
            response.raise_for_status()
            try:
                return response.json()
            except ValueError as exc:
                raise ReachInboxError("ReachInbox returned non-JSON") from exc
        except httpx.HTTPStatusError as exc:
            logger.exception("ReachInbox HTTP status error for %s %s", method, url)
            raise ReachInboxError(str(exc)) from exc
        except httpx.HTTPError as exc:
            logger.exception("ReachInbox HTTP error for %s %s", method, url)
            if response is None:
                log_fetch(
                    actor="reachinbox",
                    action=action,
                    target_url=url,
                    robots_allowed=None,
                    notes=str(exc),
                )
            raise ReachInboxError(str(exc)) from exc
