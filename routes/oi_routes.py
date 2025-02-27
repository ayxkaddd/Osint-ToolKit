from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from services.oi_service import OiService

router = APIRouter(prefix="/api/oi")
oi_service = OiService()

@router.get("/query")
async def get_oi(type: str, query: str) -> JSONResponse:
    try:
        return await oi_service.query_oi_api(type, query)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/credits")
async def query_credits() -> JSONResponse:
    try:
        return await oi_service.get_credits()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
