import logging
import time

import httpx

from backend.compliance.audit import log_fetch
from backend.enrich.keys import is_configured

logger = logging.getLogger(__name__)

_MIN_INTERVAL_SECONDS = 0.2
_VALID_STATUS = "valid"
_MAX_ACCEPTED_RETRIES = 3


class HunterError(Exception):
    """Raised when a Hunter HTTP call fails after being logged."""


def verification_status(payload: object) -> str | None:
    data = _data(payload)
    if data is None:
        return None
    status = data.get("status")
    if isinstance(status, str) and status.strip() != "":
        return status.strip()
    return None


def verification_score(payload: object) -> int | None:
    data = _data(payload)
    if data is None:
        return None
    score = data.get("score")
    if isinstance(score, int) and 0 <= score <= 100:
        return score
    if isinstance(score, float) and 0 <= score <= 100:
        return int(score)
    return None


def verified_email(payload: object) -> str | None:
    if verification_status(payload) != _VALID_STATUS:
        return None
    data = _data(payload)
    if data is None:
        return None
    email = data.get("email")
    if isinstance(email, str) and "@" in email and email.strip() != "":
        return email.strip()
    return None


def _data(payload: object) -> dict[str, object] | None:
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if isinstance(data, dict):
        return data
    return payload


class HunterClient:
    def __init__(self, *, api_key: str, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._last_request_at = 0.0
        self._client = httpx.Client(
            headers={
                "X-API-KEY": api_key,
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "HunterClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def verify_email(self, email: str) -> object:
        last_payload: object | None = None
        for attempt in range(_MAX_ACCEPTED_RETRIES):
            payload, status_code = self._request(
                "GET",
                "/v2/email-verifier",
                params={"email": email},
            )
            if status_code != 202:
                return payload
            last_payload = payload
            if attempt + 1 < _MAX_ACCEPTED_RETRIES:
                time.sleep(_MIN_INTERVAL_SECONDS)
        if last_payload is not None:
            return last_payload
        raise HunterError("Hunter email verification did not complete")

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
        params: dict[str, str] | None = None,
    ) -> tuple[object, int]:
        url = f"{self._base_url}{path}"
        action = f"{method.lower()} {path}"
        self._throttle()
        response: httpx.Response | None = None
        try:
            response = self._client.request(method, url, params=params)
            log_fetch(
                actor="hunter",
                action=action,
                target_url=str(response.url),
                robots_allowed=None,
                response_code=response.status_code,
            )
            if response.status_code == 202:
                try:
                    return response.json(), 202
                except ValueError:
                    return {}, 202
            response.raise_for_status()
            try:
                return response.json(), response.status_code
            except ValueError as exc:
                raise HunterError("Hunter returned non-JSON") from exc
        except httpx.HTTPStatusError as exc:
            logger.exception("Hunter HTTP status error for %s %s", method, url)
            raise HunterError(str(exc)) from exc
        except httpx.HTTPError as exc:
            logger.exception("Hunter HTTP error for %s %s", method, url)
            if response is None:
                log_fetch(
                    actor="hunter",
                    action=action,
                    target_url=url,
                    robots_allowed=None,
                    notes=str(exc),
                )
            raise HunterError(str(exc)) from exc


__all__ = [
    "HunterClient",
    "HunterError",
    "is_configured",
    "verification_score",
    "verification_status",
    "verified_email",
]
