import time

from backend.app.config import get_settings
from backend.compliance.robots import hostname_of, raise_if_denylisted


def user_agent() -> str:
    return f"ProspectPlayground/0.1 ({get_settings().contact_email})"


class RateLimiter:
    def __init__(self, requests_per_second: float = 1.0) -> None:
        self._rate = requests_per_second
        self._capacity = 1.0
        self._tokens: dict[str, float] = {}
        self._updated_at: dict[str, float] = {}
        self._backoff_attempt: dict[str, int] = {}

    def acquire(self, url: str) -> None:
        raise_if_denylisted(url)
        domain = hostname_of(url)
        now = time.monotonic()
        tokens = self._refill(domain, now)
        if tokens < 1.0:
            wait = (1.0 - tokens) / self._rate
            time.sleep(wait)
            now = time.monotonic()
            tokens = self._refill(domain, now)
        self._tokens[domain] = tokens - 1.0
        self._updated_at[domain] = now

    def wait_if_throttled(self, url: str, status_code: int) -> None:
        domain = hostname_of(url)
        if status_code not in (429, 503):
            self._backoff_attempt[domain] = 0
            return
        attempt = self._backoff_attempt.get(domain, 0)
        delay = float(2**attempt)
        self._backoff_attempt[domain] = attempt + 1
        time.sleep(delay)

    def _refill(self, domain: str, now: float) -> float:
        tokens = self._tokens.get(domain, self._capacity)
        last = self._updated_at.get(domain, now)
        tokens = min(self._capacity, tokens + (now - last) * self._rate)
        self._tokens[domain] = tokens
        self._updated_at[domain] = now
        return tokens
