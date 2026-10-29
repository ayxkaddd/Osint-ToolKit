"""Site icons (favicons) for result cards, fetched once and cached under media/site_icons.

The browser loads them from /api/oi/icon/<domain>, so the icon services only see
which sites appear in results, never the query or the investigation.
"""
import asyncio
import logging
import os
import re
import time
from typing import Optional, Tuple
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

ICON_DIR = os.path.join("media", "site_icons")
MAX_ICON_BYTES = 200_000
MISSING_RETRY_SECONDS = 7 * 86400
DOMAIN_RE = re.compile(r"^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
ICON_TYPES = {".png": "image/png", ".ico": "image/x-icon", ".svg": "image/svg+xml", ".jpg": "image/jpeg", ".webp": "image/webp"}

# Sources tried in order; Google's has the sharpest icons and answers 404 for unknown sites
SOURCES = (
    "https://www.google.com/s2/favicons?domain={domain}&sz=64",
    "https://icons.duckduckgo.com/ip3/{domain}.ico",
)

_pending: dict = {}


def domain_from_url(url: Optional[str]) -> Optional[str]:
    host = (urlparse(url).hostname or "") if isinstance(url, str) and "://" in url else (url or "")
    host = host.lower().strip(".")
    for prefix in ("www.", "m.", "mobile."):
        if host.startswith(prefix):
            host = host[len(prefix):]
    return host if DOMAIN_RE.match(host) else None


def _cached(domain: str) -> Tuple[Optional[str], bool]:
    """(path of the cached icon, whether a recent lookup found nothing)."""
    for ext in ICON_TYPES:
        path = os.path.join(ICON_DIR, domain + ext)
        if os.path.isfile(path):
            return path, False
    missing = os.path.join(ICON_DIR, domain + ".missing")
    return None, os.path.isfile(missing) and time.time() - os.path.getmtime(missing) < MISSING_RETRY_SECONDS


def _extension(content_type: str) -> Optional[str]:
    content_type = content_type.split(";")[0].strip().lower()
    return next((ext for ext, kind in ICON_TYPES.items() if kind == content_type or
                 (ext == ".ico" and content_type == "image/vnd.microsoft.icon")), None)


async def _download(domain: str) -> Optional[str]:
    os.makedirs(ICON_DIR, exist_ok=True)
    async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
        for source in SOURCES:
            try:
                response = await client.get(source.format(domain=domain))
            except httpx.HTTPError:
                continue
            ext = _extension(response.headers.get("content-type", ""))
            if response.status_code != 200 or not ext or not 0 < len(response.content) <= MAX_ICON_BYTES:
                continue
            path = os.path.join(ICON_DIR, domain + ext)
            with open(path + ".part", "wb") as f:
                f.write(response.content)
            os.replace(path + ".part", path)
            return path
    with open(os.path.join(ICON_DIR, domain + ".missing"), "w"):
        pass
    return None


async def get_icon(domain: str) -> Optional[Tuple[str, str]]:
    """(path, media type) of the site's icon, or None if it has none."""
    found = domain_from_url(domain)
    if not found:
        return None
    domain = found
    path, missing = _cached(domain)
    if not path and not missing:
        task = _pending.get(domain)
        if task is None:
            task = _pending[domain] = asyncio.ensure_future(_download(domain))
            task.add_done_callback(lambda _: _pending.pop(domain, None))
        try:
            path = await asyncio.shield(task)
        except Exception:
            logger.exception("Icon download failed for %s", domain)
            return None
    if not path:
        return None
    return path, ICON_TYPES[os.path.splitext(path)[1]]
