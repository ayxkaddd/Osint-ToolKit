from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from services.whois_service import WhoisService
from utils.investigation_decorator import save_investigation

router = APIRouter(prefix="/api/domain")
whois_service = WhoisService()

@router.get("/whois")
@save_investigation(service_name="whois", method_name="lookup_whois")
async def get_whois(domain: str) -> JSONResponse:
    try:
        return await whois_service.lookup_whois(domain)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/history/preview")
async def preview_whois_history(domain: str):
    """Number of archived records - free, so the page can ask before spending credits."""
    try:
        return await whois_service.preview_whois_history(domain.strip().lower())
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"WhoisXML preview failed: {e}") from e


@router.get("/history")
@save_investigation(service_name="whois", method_name="lookup_whois_history")
async def get_whois_history(domain: str) -> JSONResponse:
    try:
        return await whois_service.lookup_whois_history(domain)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))