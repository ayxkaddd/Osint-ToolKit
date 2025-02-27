from typing import List
from fastapi import APIRouter, HTTPException
from models.doxbin_models import DoxBinUser
from services.doxbin_service import DoxbinService

router = APIRouter(prefix="/api/doxbin")
doxbin_service = DoxbinService()

@router.get("/query")
async def search_doxbin(query: str) -> List[DoxBinUser]:
    try:
        return doxbin_service.search_doxbin(query)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
