from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from services import site_icon_service
from services.oi_service import OiService
from utils.investigation_decorator import save_investigation
from utils.stream_reducers import reduce_oi_stream

router = APIRouter(prefix="/api/oi")
oi_service = OiService()

@router.get("/query")
@save_investigation(service_name="oi", method_name="lookup_oi")
async def get_oi(
    type: str,
    query: str,
    premium: bool = False,
    premium_modules_only: bool = False,
    format: str = Query("json", pattern="^(json|pdf)$"),
) -> JSONResponse:
    try:
        return await oi_service.query_oi_api(
            type,
            query,
            premium=premium,
            premium_modules_only=premium_modules_only,
            format=format,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

QUERY_TYPES = "^(email|phone|username|name|wallet)$"


def _event_stream(events) -> StreamingResponse:
    return StreamingResponse(events, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/stream")
@save_investigation(service_name="oi", method_name="lookup_oi", stream_reducer=reduce_oi_stream)
async def stream_oi(
    type: str = Query(..., pattern=QUERY_TYPES),
    query: str = Query(..., min_length=1, max_length=300),
    premium: bool = False,
    premium_modules_only: bool = False,
):
    """Results streamed module by module (SSE); saved to the investigation when done."""
    return _event_stream(oi_service.stream_oi(type, query, premium, premium_modules_only))


@router.get("/sandbox/stream")
async def stream_oi_sandbox(
    type: str = Query(..., pattern=QUERY_TYPES),
    query: str = Query(..., min_length=1, max_length=300),
):
    """OSINT Industries' sandbox: fake data, no credits used, not saved."""
    return _event_stream(oi_service.stream_oi(type, query, sandbox=True))


@router.get("/icon/{domain}")
async def site_icon(domain: str):
    """A site's favicon for result cards (cached under media/site_icons)."""
    icon = await site_icon_service.get_icon(domain)
    if not icon:
        raise HTTPException(status_code=404, detail="No icon")
    path, media_type = icon
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "private, max-age=604800"})


@router.get("/credits")
async def query_credits() -> JSONResponse:
    try:
        return await oi_service.get_credits()
        # return {"credits": 223}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
