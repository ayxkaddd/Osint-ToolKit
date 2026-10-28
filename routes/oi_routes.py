from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from services.oi_service import OiService
from utils.investigation_decorator import save_investigation

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

@router.get("/credits")
async def query_credits() -> JSONResponse:
    try:
        return await oi_service.get_credits()
        # return {"credits": 223}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
