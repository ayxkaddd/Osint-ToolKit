from collections import defaultdict
from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from services.username_test_service import StreamingUsernameSearchService
import asyncio
from typing import List, Optional

from utils.investigation_decorator import save_investigation
from utils.stream_reducers import reduce_username_search

router = APIRouter(prefix="/api/username")
# service = StreamingUsernameSearchService(
#     max_concurrent_requests=30,
#     timeout_seconds=15,
#     max_retries=2
# )

search_service = StreamingUsernameSearchService()

import logging
logger = logging.getLogger("username_routes")

@router.get("/search/stream")
@save_investigation(
    service_name="username",
    method_name="lookup_username",
    stream_reducer=reduce_username_search,
)
async def stream_search_sse(
    username: str = Query(..., min_length=1, max_length=100, description="Username to search"),
    include_duckduckgo: bool = Query(False, description="Include DuckDuckGo results"),
    extract_profile: bool = Query(False, description="Extract profile data"),
    categories: Optional[List[str]] = Query(None, description="Filter by categories"),
    priority_sites: Optional[List[str]] = Query(None, description="Priority sites to check first"),
    only_sites: Optional[List[str]] = Query(None, description="Check only these sites (retry errors)"),
):
    """
    Server-Sent Events endpoint for streaming search results.

    Events reach the client as they happen; the investigation decorator keeps a
    copy and saves the found profiles when the search finishes (or a partial
    result if the client stops early).
    """
    async def generate():
        async for event in search_service.stream_search(
            username=username,
            include_duckduckgo=include_duckduckgo,
            extract_profile=extract_profile,
            categories=categories,
            priority_sites=priority_sites,
            only_sites=only_sites,
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


@router.websocket("/search/ws")
async def websocket_search(websocket: WebSocket):
    """
    WebSocket endpoint for streaming search results

    Example usage:
    ```javascript
    const ws = new WebSocket('ws://localhost:8000/api/search/ws');
    ws.onopen = () => {
        ws.send(JSON.stringify({
            username: 'johndoe',
            include_duckduckgo: false,
            extract_profile: false
        }));
    };
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        console.log(data);
    };
    ```
    """
    await websocket.accept()

    try:
        # Wait for search parameters
        data = await websocket.receive_json()

        username = data.get("username")
        if not username:
            await websocket.send_json({
                "error": "Username is required"
            })
            await websocket.close()
            return

        # Stream results
        async for event in search_service.stream_search(
            username=username,
            include_duckduckgo=data.get("include_duckduckgo", False),
            extract_profile=data.get("extract_profile", False),
            categories=data.get("categories"),
            priority_sites=data.get("priority_sites")
        ):
            await websocket.send_json(event.to_json())

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
        await websocket.send_json({
            "event_type": "error",
            "data": {"message": str(e)}
        })
        await websocket.close()


@router.get("/api/metadata")
async def get_metadata():
    """Get available sites metadata"""
    try:
        metadata = await asyncio.to_thread(search_service.get_metadata)
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
                for site in sites[:10]  # Return sample
            ]
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# @router.get("/search")
# async def search_username(
#     username: str = Query(..., min_length=1, max_length=50, description="Username to search for"),
#     include_duckduckgo: bool = Query(False, description="Include DuckDuckGo results"),
#     extract_profile: bool = Query(False, description="Extract profile data using socid-extractor"),
#     categories: Optional[List[str]] = Query(None, description="Filter by site categories"),
#     priority_sites: Optional[List[str]] = Query(None, description="Filter by specific site names")
# ) -> JSONResponse:
#     """
#     Search for a username across multiple websites and optionally DuckDuckGo.
#     Optionally extract rich profile data from matched pages.
#     """
#     try:
#         result = await service.search_username(
#             username=username,
#             include_duckduckgo=include_duckduckgo,
#             extract_profile=extract_profile,
#             categories=categories,
#             priority_sites=priority_sites
#         )

#         return JSONResponse({
#             "username": result.username,
#             "sites_found": [
#                 {
#                     "name": s.site_name,
#                     "url": s.url,
#                     "category": s.category,
#                     "profile_data": s.profile_data
#                 }
#                 for s in result.sites_found
#             ],
#             "duckduckgo_results": result.duckduckgo_results,
#             "stats": service.get_summary_stats(result)
#         })
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")

@router.post("/bulk-search")
async def bulk_search_usernames(
    usernames: list = Query(..., description="List of usernames to search"),
    include_duckduckgo: bool = Query(False, description="Include DuckDuckGo results"),
    extract_profile: bool = Query(False, description="Extract profile data using socid-extractor")
) -> JSONResponse:
    """
    Search multiple usernames concurrently.
    """
    if not isinstance(usernames, list) or len(usernames) == 0:
        raise HTTPException(status_code=400, detail="Usernames must be a non-empty list.")

    if len(usernames) > 50:
        raise HTTPException(status_code=400, detail="Max 50 usernames per request.")

    try:
        tasks = [
            search_service.search_username(username, include_duckduckgo, extract_profile)
            for username in usernames
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        formatted_results = []
        for i, res in enumerate(results):
            if isinstance(res, Exception):
                formatted_results.append({
                    "username": usernames[i],
                    "error": str(res)
                })
            else:
                formatted_results.append(res)

        return JSONResponse(content={
            "bulk_results": formatted_results,
            "total_usernames": len(usernames),
            "profile_extraction_enabled": extract_profile
        })

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bulk search failed: {str(e)}")