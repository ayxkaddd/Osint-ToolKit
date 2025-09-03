from typing import List
from fastapi import APIRouter, HTTPException
from services.breach_service import BreachService

router = APIRouter(prefix="/api/breach")
breach_service = BreachService()

@router.post("/search")
async def search_breach(term: str, fields: List[str] = ["email"], wildcard: bool = False, case_sensitive: bool = False):
    try:
        return breach_service.search_breach(term, fields, wildcard, case_sensitive)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
