from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

from backend.compliance.audit import log_fetch

DENYLIST_DOMAINS: frozenset[str] = frozenset(
    {"linkedin.com", "instagram.com", "facebook.com", "x.com"}
)
_CACHE_TTL = timedelta(hours=24)


class DenylistError(PermissionError):
    def __init__(self, url: str) -> None:
        super().__init__(f"Denylisted domain: {url}")
        self.url = url


class AllowlistError(PermissionError):
    def __init__(self, url: str) -> None:
        super().__init__(f"Domain is not in collector allowlist: {url}")
        self.url = url


def hostname_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host == "":
        raise ValueError(f"URL has no hostname: {url}")
    return host


def is_denylisted(url: str) -> bool:
    host = hostname_of(url)
    return any(host == domain or host.endswith("." + domain) for domain in DENYLIST_DOMAINS)


def raise_if_denylisted(url: str) -> None:
    if is_denylisted(url):
        raise DenylistError(url)


def ensure_allowed_domain(url: str, allowed_domains: Sequence[str]) -> None:
    raise_if_denylisted(url)
    host = hostname_of(url)
    allowed = {domain.lower().removeprefix("www.") for domain in allowed_domains}
    if not any(host == domain or host.endswith("." + domain) for domain in allowed):
        raise AllowlistError(url)


def _user_agent() -> str:
    from backend.compliance.ratelimit import user_agent

    return user_agent()


class RobotsGate:
    _cache: dict[str, tuple[datetime, RobotFileParser]] = {}

    def allowed(self, url: str) -> bool:
        raise_if_denylisted(url)
        parser = self._parser_for(url)
        allowed = parser.can_fetch(_user_agent(), url)
        if not allowed:
            log_fetch(
                actor="robots_gate",
                action="robots_disallow",
                target_url=url,
                robots_allowed=False,
            )
        return allowed

    def _parser_for(self, url: str) -> RobotFileParser:
        domain = hostname_of(url)
        now = datetime.now(timezone.utc)
        cached = self._cache.get(domain)
        if cached is not None:
            stored_at, parser = cached
            if now - stored_at < _CACHE_TTL:
                return parser
        parser = self._fetch_parser(url)
        self._cache[domain] = (now, parser)
        return parser

    def _fetch_parser(self, url: str) -> RobotFileParser:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        parser = RobotFileParser()
        parser.set_url(robots_url)
        request = Request(robots_url, headers={"User-Agent": _user_agent()}, method="GET")
        try:
            with urlopen(request, timeout=10) as response:
                final_url = str(getattr(response, "url", robots_url))
                raise_if_denylisted(final_url)
                raw = response.read()
        except HTTPError as exc:
            if exc.code in (401, 403):
                parser.parse(["User-agent: *", "Disallow: /"])
                return parser
            if exc.code == 404:
                parser.parse([])
                return parser
            parser.parse(["User-agent: *", "Disallow: /"])
            return parser
        except URLError:
            parser.parse(["User-agent: *", "Disallow: /"])
            return parser
        parser.parse(raw.decode("utf-8", errors="replace").splitlines())
        return parser
