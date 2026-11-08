"""A pool of outbound proxies for the scraping modules.

Proxies come from two places: a list the operator pastes in Settings
(``assets/proxies.txt``) and, when that is empty or thin, free proxies fetched
from public lists. Public proxies are slow and mostly dead, so the pool only
ever hands out ones that passed a recent, fast health check. All fetching and
checking happens in the background (primed in the app lifespan, then refreshed
on a timer) so it never runs inside a user's lookup.

``utils.proxy_transport`` turns the pool into an httpx transport (and CLI env)
that rotates across the healthy proxies and falls back to a direct connection
whenever the pool is empty or a proxy fails - which keeps a lookup's runtime
from regressing when proxies are poor.
"""
import asyncio
import logging
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx

from utils.config import get_setting

logger = logging.getLogger(__name__)

PROXY_FILE = Path("assets/proxies.txt")

VALID_SCHEMES = ("http", "https", "socks4", "socks5", "socks5h")
CLI_SCHEMES = ("http", "https", "socks5", "socks5h")

# (url, default scheme for bare ip:port lines). monosans/proxy-list is re-checked
# and updated often; all.txt (~40 KB) has every proxy with its scheme
# (http://, socks4://, socks5://) - the JSON version is ~25x bigger and only adds
# geolocation. Overridable with the PROXY_SOURCES setting (comma-separated URLs).
DEFAULT_SOURCES = [
    ("https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/all.txt", "http"),
]

# Off unless the operator turns it on: free proxies make lookups slower and some
# sites block them, so fewer accounts are found than with a direct connection.
ENABLED_BY_DEFAULT = False


def _flag(key: str, default: bool) -> bool:
    value = (get_setting(key) or ("true" if default else "false")).strip().lower()
    return value in ("1", "true", "yes", "on")


def parse_proxy(raw: str, default_scheme: str = "http") -> Optional[str]:
    """Normalise one line to ``scheme://[user:pass@]host:port`` or return None."""
    raw = raw.strip()
    if not raw or raw.startswith("#"):
        return None
    if "://" not in raw:
        raw = f"{default_scheme}://{raw}"
    try:
        parsed = urlparse(raw)
    except ValueError:
        return None
    if parsed.scheme not in VALID_SCHEMES or not parsed.hostname or not parsed.port:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


@dataclass
class Proxy:
    url: str
    latency: float = 0.0
    fails: int = 0
    last_ok: float = 0.0


class ProxyPool:
    MAX_FAILS = 3               # drop a proxy after this many consecutive failures
    HEALTHY_FLOOR = 10          # fetch public proxies to top the pool up to here
    MAX_PUBLIC_CANDIDATES = 800  # cap how many public proxies we health-check per refresh
    VALIDATE_CONCURRENCY = 100
    VALIDATE_URL = "http://www.gstatic.com/generate_204"
    VALIDATE_TIMEOUT = httpx.Timeout(5.0, connect=3.0)
    MAX_LATENCY = 2.5           # only keep proxies that answered the probe this fast
    REFRESH_INTERVAL = 15 * 60

    def __init__(self):
        self._healthy: list[Proxy] = []
        self._by_url: dict[str, Proxy] = {}
        self._cursor = 0
        self._user_urls: list[str] = []
        self._user_mtime: Optional[float] = None
        self._refreshing = asyncio.Lock()
        self._last_refresh = 0.0
        self._counts = {"user": 0, "public": 0, "healthy": 0}

    # -- read side (sync, called per request) -------------------------------

    def enabled(self) -> bool:
        """Whether a lookup should route through a proxy right now."""
        return _flag("PROXY_ENABLED", ENABLED_BY_DEFAULT) and bool(self._healthy)

    def pick(self) -> Optional[str]:
        """Next healthy proxy, round-robin (spreads load across the pool)."""
        healthy = self._healthy
        if not healthy:
            return None
        proxy = healthy[self._cursor % len(healthy)]
        self._cursor += 1
        return proxy.url

    def pick_for_cli(self) -> Optional[str]:
        """A healthy proxy an external tool can use (http/socks5 only)."""
        healthy = self._healthy
        for _ in range(len(healthy)):
            url = self.pick()
            if url and url.split("://", 1)[0] in CLI_SCHEMES:
                return url
        return None

    def sample(self, n: int, exclude=()) -> list[str]:
        """Up to n random healthy proxies, for failover alternatives."""
        pool = [p.url for p in self._healthy if p.url not in exclude]
        random.shuffle(pool)
        return pool[:max(0, n)]

    def report(self, url: str, ok: bool, latency: float = 0.0) -> None:
        proxy = self._by_url.get(url)
        if not proxy:
            return
        if ok:
            proxy.fails = 0
            proxy.last_ok = time.monotonic()
            if latency:
                proxy.latency = latency
        else:
            proxy.fails += 1
            if proxy.fails >= self.MAX_FAILS:
                self._by_url.pop(url, None)
                self._healthy = [p for p in self._healthy if p.url != url]

    def status(self) -> dict:
        return {
            "enabled": _flag("PROXY_ENABLED", ENABLED_BY_DEFAULT),
            "fetch_public": _flag("PROXY_FETCH_PUBLIC", True),
            "user_count": len(self._user_urls),
            "healthy": len(self._healthy),
            "public": self._counts.get("public", 0),
            "last_refresh": self._last_refresh or None,
        }

    # -- write side (background) --------------------------------------------

    def _load_user(self) -> None:
        """Reload the operator's list from disk when the file changed."""
        try:
            mtime = PROXY_FILE.stat().st_mtime
        except FileNotFoundError:
            self._user_urls = []
            self._user_mtime = None
            return
        if mtime == self._user_mtime:
            return
        seen: set[str] = set()
        urls: list[str] = []
        for line in PROXY_FILE.read_text().splitlines():
            url = parse_proxy(line, "http")
            if url and url not in seen:
                seen.add(url)
                urls.append(url)
        self._user_urls = urls
        self._user_mtime = mtime

    def _sources(self) -> list[tuple[str, str]]:
        raw = get_setting("PROXY_SOURCES")
        if raw:
            return [(u.strip(), "http") for u in raw.split(",") if u.strip()]
        return DEFAULT_SOURCES

    async def _fetch_one(self, client: httpx.AsyncClient, url: str, scheme: str) -> list[str]:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001 - any network/HTTP error means skip this source
            logger.info("proxy source failed (%s): %s", url, exc)
            return []
        out = []
        for line in resp.text.splitlines():
            parsed = parse_proxy(line, scheme)
            if parsed:
                out.append(parsed)
        return out

    async def _fetch_public(self) -> list[str]:
        sources = self._sources()
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            results = await asyncio.gather(
                *[self._fetch_one(client, url, scheme) for url, scheme in sources],
                return_exceptions=True,
            )
        seen: set[str] = set()
        out: list[str] = []
        for result in results:
            if isinstance(result, list):
                for url in result:
                    if url not in seen:
                        seen.add(url)
                        out.append(url)
        return out

    async def _validate(self, urls: list[str]) -> list[Proxy]:
        """Keep only proxies that answer the probe quickly (concurrent, background)."""
        semaphore = asyncio.Semaphore(self.VALIDATE_CONCURRENCY)

        async def check(url: str) -> Optional[Proxy]:
            async with semaphore:
                start = time.monotonic()
                try:
                    async with httpx.AsyncClient(proxy=url, timeout=self.VALIDATE_TIMEOUT,
                                                 verify=False) as client:
                        resp = await client.get(self.VALIDATE_URL)
                except Exception:  # noqa: BLE001 - a dead/slow proxy just doesn't make the cut
                    return None
                latency = time.monotonic() - start
                if resp.status_code < 500 and latency <= self.MAX_LATENCY:
                    return Proxy(url=url, latency=latency, last_ok=time.monotonic())
                return None

        results = await asyncio.gather(*[check(url) for url in urls], return_exceptions=True)
        good = [r for r in results if isinstance(r, Proxy)]
        good.sort(key=lambda p: p.latency)
        return good

    async def refresh(self, force: bool = False) -> None:
        """Rebuild the healthy set. Safe to call often; skips if already running."""
        if self._refreshing.locked():
            return
        async with self._refreshing:
            if not force and not _flag("PROXY_ENABLED", ENABLED_BY_DEFAULT):
                self._healthy = []
                self._by_url = {}
                self._counts = {"user": len(self._user_urls), "public": 0, "healthy": 0}
                return

            self._load_user()
            user = await self._validate(self._user_urls) if self._user_urls else []

            need_public = _flag("PROXY_FETCH_PUBLIC", True) and len(user) < self.HEALTHY_FLOOR
            public: list[Proxy] = []
            if need_public:
                have = {p.url for p in user}
                candidates = [u for u in await self._fetch_public() if u not in have]
                random.shuffle(candidates)
                public = await self._validate(candidates[: self.MAX_PUBLIC_CANDIDATES])

            healthy = user + public
            self._healthy = healthy
            self._by_url = {p.url: p for p in healthy}
            self._cursor = 0
            self._counts = {"user": len(self._user_urls), "public": len(public), "healthy": len(healthy)}
            self._last_refresh = time.time()
            logger.info("proxy pool: %d healthy (%d user, %d public)",
                        len(healthy), len(user), len(public))

    def trigger_refresh(self) -> None:
        """Schedule a refresh on the running loop (for the Settings 'refresh now')."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self.refresh(force=True))

    async def run_forever(self) -> None:
        """Prime once, then refresh on the timer or when the pool runs thin."""
        if _flag("PROXY_ENABLED", ENABLED_BY_DEFAULT):
            try:
                await self.refresh()
            except Exception:  # noqa: BLE001
                logger.exception("initial proxy refresh failed")
        while True:
            await asyncio.sleep(60)
            if not _flag("PROXY_ENABLED", ENABLED_BY_DEFAULT):
                continue
            due = time.time() - self._last_refresh >= self.REFRESH_INTERVAL
            thin = len(self._healthy) < self.HEALTHY_FLOOR
            if due or thin:
                try:
                    await self.refresh()
                except Exception:  # noqa: BLE001
                    logger.exception("proxy refresh failed")


pool = ProxyPool()
