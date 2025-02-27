from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from services.whois_service import WhoisService

router = APIRouter(prefix="/api/domain")
whois_service = WhoisService()

@router.get("/whois")
async def get_whois(domain: str) -> JSONResponse:
    try:
        return await whois_service.lookup_whois(domain)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/history")
async def get_whois_history(domain: str) -> JSONResponse:
    try:
        return await whois_service.lookup_whois_history(domain)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
