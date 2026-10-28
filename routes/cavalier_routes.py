import logging
import re

import httpx
from fastapi import APIRouter, HTTPException, Query

from utils.investigation_decorator import save_investigation

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cavalier")

CAVALIER_BASE = "https://cavalier.hudsonrock.com/api/json/v2"
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


@router.get("/search")
@save_investigation(service_name="cavalier", method_name="search_infostealers")
async def search_cavalier(query: str = Query(..., min_length=1, max_length=256)) -> dict:
    """Hudson Rock Cavalier infostealer lookup by email or username.

    Called server-side (previously the browser went through a public CORS
    proxy, which leaked every query to a third party).
    """
    query = query.strip()
    is_email = bool(EMAIL_RE.match(query))
    if is_email:
        url, params = f"{CAVALIER_BASE}/preview/search-by-login/osint-tools", {"email": query}
    else:
        url, params = f"{CAVALIER_BASE}/osint-tools/search-by-username", {"username": query}

    try:
        async with httpx.AsyncClient(timeout=30, headers={"Accept": "application/json"}) as client:
            response = await client.get(url, params=params)
    except httpx.HTTPError as e:
        logger.warning("Cavalier request failed: %s", e)
        raise HTTPException(status_code=502, detail="Could not reach Hudson Rock Cavalier") from e

    try:
        data = response.json()
    except ValueError:
        data = None

    if response.status_code >= 400:
        # Cavalier answers unknown targets with an error status
        if response.status_code in (404, 500) or (isinstance(data, dict) and data.get("error")):
            return {"query": query, "search_type": "email" if is_email else "username", "error": "not found"}
        raise HTTPException(status_code=502, detail=f"Cavalier returned HTTP {response.status_code}")

    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="Unexpected response from Cavalier")
    return {"query": query, "search_type": "email" if is_email else "username", **data}
