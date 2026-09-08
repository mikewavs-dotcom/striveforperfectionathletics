from types import SimpleNamespace
from typing import Any

import pytest

from backend.compliance import audit, robots
from backend.compliance.minor_guard import is_minor_related
from backend.compliance.ratelimit import RateLimiter, user_agent
from backend.compliance.robots import (
    AllowlistError,
    DenylistError,
    RobotsGate,
    ensure_allowed_domain,
)

ROBOTS_TXT_FIXTURE = """\
User-agent: *
Disallow: /private
Allow: /public
"""


class FakeResponse:
    def __init__(self, body: str, url: str) -> None:
        self._body = body.encode("utf-8")
        self.url = url

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


@pytest.fixture(autouse=True)
def isolate_compliance(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*args: object, **kwargs: object) -> None:
        raise AssertionError("live network request attempted")

    monkeypatch.setattr(robots, "urlopen", blocked)
    monkeypatch.setattr("urllib.request.urlopen", blocked)
    monkeypatch.setattr(
        "backend.compliance.ratelimit.get_settings",
        lambda: SimpleNamespace(contact_email="compliance@example.com"),
    )
    def discard_audit(**kwargs: object) -> None:
        return None

    monkeypatch.setattr(robots, "log_fetch", discard_audit)
    RobotsGate._cache.clear()


def _install_robots_fixture(
    monkeypatch: pytest.MonkeyPatch, body: str = ROBOTS_TXT_FIXTURE
) -> list[str]:
    calls: list[str] = []

    def fake_urlopen(request: object, timeout: float = 0) -> FakeResponse:
        url = str(getattr(request, "full_url", request))
        calls.append(url)
        return FakeResponse(body, url)

    monkeypatch.setattr(robots, "urlopen", fake_urlopen)
    return calls


def test_robots_gate_blocks_disallowed_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_robots_fixture(monkeypatch)
    gate = RobotsGate()
    assert gate.allowed("https://example.com/private/data") is False


def test_robots_gate_allows_allowed_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_robots_fixture(monkeypatch)
    gate = RobotsGate()
    assert gate.allowed("https://example.com/public/staff") is True


def test_robots_gate_caches_parser_for_24h(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_robots_fixture(monkeypatch)
    gate = RobotsGate()
    assert gate.allowed("https://example.com/public/a") is True
    assert gate.allowed("https://example.com/public/b") is True
    assert len(calls) == 1


def test_denylist_raises_before_network(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_urlopen(*args: object, **kwargs: object) -> FakeResponse:
        calls.append("network")
        raise AssertionError("live network request attempted")

    monkeypatch.setattr(robots, "urlopen", fake_urlopen)
    gate = RobotsGate()
    with pytest.raises(DenylistError):
        gate.allowed("https://linkedin.com/in/someone")
    assert calls == []


def test_denylist_checked_before_allowlist() -> None:
    with pytest.raises(DenylistError):
        ensure_allowed_domain("https://www.facebook.com/page", ["example.com"])


def test_allowlist_raises_for_unknown_domain() -> None:
    with pytest.raises(AllowlistError):
        ensure_allowed_domain("https://other.example/path", ["example.com"])


def test_rate_limiter_enforces_configured_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    now = {"t": 0.0}
    sleeps: list[float] = []
    monkeypatch.setattr("backend.compliance.ratelimit.time.monotonic", lambda: now["t"])

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now["t"] += seconds

    monkeypatch.setattr("backend.compliance.ratelimit.time.sleep", fake_sleep)
    limiter = RateLimiter(requests_per_second=1.0)
    limiter.acquire("https://example.com/a")
    limiter.acquire("https://example.com/b")
    assert sleeps == pytest.approx([1.0])


def test_rate_limiter_backoff_on_429(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("backend.compliance.ratelimit.time.sleep", sleeps.append)
    limiter = RateLimiter()
    limiter.wait_if_throttled("https://example.com/a", 429)
    limiter.wait_if_throttled("https://example.com/a", 429)
    assert sleeps == [1.0, 2.0]


def test_user_agent_includes_contact_email() -> None:
    assert "compliance@example.com" in user_agent()


def test_is_minor_related_roster_page() -> None:
    assert (
        is_minor_related(
            "https://example.edu/athletics/mens-soccer/roster",
            "2026 Men's Soccer Roster",
            "The 2026 roster is listed below.",
        )
        is True
    )


def test_is_minor_related_athletic_director_staff_page() -> None:
    assert (
        is_minor_related(
            "https://example.edu/athletics/staff/athletic-director",
            "Athletic Director",
            "Jane Doe is the Athletic Director. Contact the athletics office.",
        )
        is False
    )


def test_is_minor_related_class_of_and_student_athlete() -> None:
    assert (
        is_minor_related(
            "https://example.edu/news/commit",
            "Student athlete profile",
            "Class of 2029 forward.",
        )
        is True
    )


def test_is_minor_related_u16_person_not_team() -> None:
    assert (
        is_minor_related(
            "https://example.edu/news/player",
            "Player note",
            "Jordan Smith U16 scored twice.",
        )
        is True
    )
    assert (
        is_minor_related(
            "https://example.edu/camps/schedule",
            "Camp schedule",
            "The U16 team plays on Saturday.",
        )
        is False
    )


def test_audit_log_appends_fetch_record(monkeypatch: pytest.MonkeyPatch) -> None:
    added: list[Any] = []

    class FakeSession:
        def add(self, obj: object) -> None:
            added.append(obj)

        def commit(self) -> None:
            return None

        def __enter__(self) -> "FakeSession":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    session = FakeSession()
    monkeypatch.setattr(audit, "get_session_factory", lambda: lambda: session)
    audit.log_fetch(
        actor="test_collector",
        action="fetch",
        target_url="https://example.com/public",
        robots_allowed=True,
        response_code=200,
    )
    assert len(added) == 1
    record = added[0]
    assert record.actor == "test_collector"
    assert record.target_url == "https://example.com/public"
    assert record.robots_allowed is True
    assert record.notes == "response_code=200"
    assert not hasattr(record, "delete")
