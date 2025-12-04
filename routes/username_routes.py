import logging
from typing import List, Optional
from collections import defaultdict
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from services.username_service import StreamingUsernameSearchService

router = APIRouter(prefix="/api/username")

search_service = StreamingUsernameSearchService()

logger = logging.getLogger("username_routes")
logging.basicConfig(level=logging.INFO)

@router.get("/search/stream")
async def stream_search_sse(
    username: str = Query(..., description="Username to search"),
    include_duckduckgo: bool = Query(False, description="Include DuckDuckGo results"),
    extract_profile: bool = Query(False, description="Extract profile data"),
    categories: Optional[List[str]] = Query(None, description="Filter by categories"),
    priority_sites: Optional[List[str]] = Query(None, description="Priority sites to check first")
):
    async def generate():
        async for event in search_service.stream_search(
            username=username,
            include_duckduckgo=include_duckduckgo,
            extract_profile=extract_profile,
            categories=categories,
            priority_sites=priority_sites
        ):
            yield event.to_sse()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

@router.get("/metadata")
async def get_metadata():
    try:
        metadata = search_service.get_metadata()
        sites = metadata.get("sites", [])

        categories = defaultdict(int)
        for site in sites:
            categories[site.get("cat", "unknown")] += 1

        return {
            "total_sites": len(sites),
            "categories": dict(categories),
            "sites": [
                {
                    "name": site.get("name"),
                    "category": site.get("cat"),
                    "url": site.get("uri_check")
                }
                for site in sites[:10]
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
