from typing import List
from fastapi import APIRouter, HTTPException
from services.ns_service import NsService

router = APIRouter(prefix="/api/ns")
ns_service = NsService()

@router.get("/search")
async def get_domains(ns1: str, ns2: str) -> List[str]:
    try:
        return ns_service.get_shared_domains(ns1, ns2)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
