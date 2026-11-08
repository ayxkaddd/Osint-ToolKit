from collections import defaultdict
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from services import mailbox_service as mailboxes
from services.username_service import StreamingUsernameSearchService
import asyncio
import logging
from typing import Optional

from utils.config import update_env
from utils.investigation_decorator import save_investigation
from utils.stream_reducers import reduce_username_search

router = APIRouter(prefix="/api/username")
search_service = StreamingUsernameSearchService()

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
    categories: Optional[list[str]] = Query(None, description="Filter by categories"),
    priority_sites: Optional[list[str]] = Query(None, description="Priority sites to check first"),
    only_sites: Optional[list[str]] = Query(None, description="Check only these sites (retry errors)"),
    check_mailboxes: bool = Query(False, description="Also check whether the username is a mailbox at email providers"),
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
            check_mailboxes=check_mailboxes,
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


class GooglePermission(BaseModel):
    allow: bool


@router.get("/mailboxes/status")
async def mailbox_status():
    """The email providers checked, and whether Gmail may use the GHunt session."""
    return {
        "providers": [{"id": p.id, "name": p.name, "domains": p.domains, "note": p.note}
                      for p in mailboxes.PROVIDERS],
        "gmail_permission": mailboxes.gmail_permission(),
        "ghunt_session": mailboxes.ghunt_creds_path().is_file(),
    }


@router.post("/mailboxes/google-permission")
async def set_google_permission(body: GooglePermission):
    """The operator allows (or stops) the Gmail check with their Google session."""
    update_env({mailboxes.GMAIL_PERMISSION_KEY: "true" if body.allow else None})
    return {"gmail_permission": mailboxes.gmail_permission()}


@router.get("/mailboxes/check")
async def check_mailbox_provider(
    username: str = Query(..., min_length=1, max_length=100),
    provider: str = Query(..., description="Provider id, e.g. gmail"),
):
    """One provider again (e.g. Gmail right after it was allowed)."""
    if provider not in mailboxes.PROVIDERS_BY_ID:
        raise HTTPException(status_code=404, detail="Unknown email provider")
    return {"results": [r.to_dict() async for r in mailboxes.check_mailboxes(username, [provider])]}


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