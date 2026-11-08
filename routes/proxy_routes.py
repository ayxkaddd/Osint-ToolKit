"""Settings endpoints for the outbound proxy pool.

The operator's proxy list is a multi-line file (`assets/proxies.txt`), which
`.env` can't hold, so it lives here rather than in the generic settings page.
The toggles are ordinary `.env` keys written through `update_env`.
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.proxy_pool import pool, parse_proxy, PROXY_FILE
from utils.config import get_setting, update_env

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/proxies")


class ProxySettings(BaseModel):
    proxies: str = ""              # the textarea, one proxy per line
    enabled: bool = True
    fetch_public: bool = True
    sources: Optional[str] = None  # comma-separated source URLs; omitted = leave as-is


@router.get("")
async def get_proxies() -> dict:
    """Current toggles, the operator's list, and live pool health."""
    try:
        text = PROXY_FILE.read_text()
    except FileNotFoundError:
        text = ""
    status = pool.status()
    status["proxies"] = text
    status["sources"] = get_setting("PROXY_SOURCES") or ""
    return status


@router.post("")
async def save_proxies(settings: ProxySettings) -> dict:
    valid, invalid = [], []
    for line in settings.proxies.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        (valid if parse_proxy(stripped) else invalid).append(stripped)
    if invalid:
        shown = ", ".join(invalid[:5]) + (" ..." if len(invalid) > 5 else "")
        raise HTTPException(status_code=400, detail=f"Not valid proxies (use host:port or scheme://host:port): {shown}")

    PROXY_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROXY_FILE.write_text("\n".join(valid) + ("\n" if valid else ""))

    env: dict[str, Optional[str]] = {
        "PROXY_ENABLED": "true" if settings.enabled else "false",
        "PROXY_FETCH_PUBLIC": "true" if settings.fetch_public else "false",
    }
    if settings.sources is not None:
        env["PROXY_SOURCES"] = settings.sources.strip() or None  # None removes the key -> defaults
    update_env(env)
    pool.trigger_refresh()
    return {"success": True, "saved": len(valid)}


@router.post("/refresh")
async def refresh_proxies() -> dict:
    """Re-fetch and re-validate the pool in the background."""
    pool.trigger_refresh()
    return {"success": True}
