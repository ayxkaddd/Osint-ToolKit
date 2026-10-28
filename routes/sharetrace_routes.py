from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

from services.sharetrace_service import ShareTraceService
from utils.investigation_decorator import save_investigation

router = APIRouter(prefix="/api/sharetrace")
searchtrace_service = ShareTraceService()

MAX_LINKS = 100


@router.get("/enrich_link")
@save_investigation(service_name="sharetrace", method_name="enrich_link")
async def enrich_link(link: str) -> Dict[str, Any]:
    return await searchtrace_service.run_sharetrace(link)


@router.post("/enrich_links")
@save_investigation(service_name="sharetrace", method_name="enrich_links")
async def enrich_links(links: List[str]) -> Dict[str, Any]:
    links = list(dict.fromkeys(link.strip() for link in links if link and link.strip()))
    if len(links) > MAX_LINKS:
        raise HTTPException(status_code=400, detail=f"At most {MAX_LINKS} links per request")
    return {
        "total_links": len(links),
        "results": await searchtrace_service.run_many(links),
    }
