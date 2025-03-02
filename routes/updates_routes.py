from fastapi import APIRouter, HTTPException
from services.updates_service import UpdatesService
from models.update_models import Update

router = APIRouter(prefix="/api/updates")
updates_service = UpdatesService()

@router.get("/check")
async def check_updates() -> Update | None:
    try:
        return await updates_service.check_for_updates()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
