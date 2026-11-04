import json

from fastapi import APIRouter, HTTPException, Query, Request
from auth.auth_handler import TelegramAuthHandler
from fastapi.responses import JSONResponse, StreamingResponse
from services.vk_history_service import VkHistoryService
from utils import telegram_client
from utils.investigation_decorator import save_investigation
from utils.stream_reducers import reduce_vk_history

auth_router = APIRouter(prefix="/auth/tg")
bot_router = APIRouter(prefix="/api/telegram")
auth_handler = TelegramAuthHandler()

@auth_router.post("/request-code")
async def request_code(request: Request):
    data = await request.json()
    phone_number = data.get("phone_number")

    if not phone_number:
        raise HTTPException(status_code=400, detail="Phone number required")

    result = await auth_handler.send_verification_code(phone_number)
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])

    return JSONResponse(content=result)

@auth_router.post("/verify-code")
async def verify_code(request: Request):
    data = await request.json()
    phone_number = data.get("phone_number")
    code = data.get("code")

    if not all([phone_number, code]):
        raise HTTPException(status_code=400, detail="Missing required data")

    result = await auth_handler.verify_code(phone_number, code)
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])

    return JSONResponse(content=result)

@auth_router.post("/verify-password")
async def verify_password(request: Request):
    data = await request.json()
    password = data.get("password")
    if not password:
        raise HTTPException(status_code=400, detail="Password required")

    result = await auth_handler.verify_password(password)
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    return JSONResponse(content=result)

@auth_router.get("/status")
async def auth_status():
    if not telegram_client.is_configured():
        return {"authorized": False, "configured": False}
    status = await auth_handler.connect()
    return {"authorized": status, "configured": True}

vk_history_service = VkHistoryService()


def _nothing_to_keep(result: dict) -> bool:
    """A lookup that failed or was stopped before the bot said anything."""
    said = result["entries"] or result["photos"] or result["notices"] or result["empty_periods"]
    return not result.get("complete") and not said


@bot_router.get("/search/stream")
@save_investigation(service_name="vk_profile", method_name="lookup_vk_profile",
                    stream_reducer=reduce_vk_history, skip_if=_nothing_to_keep)
async def stream_vk_profile(user_id: str = Query(..., min_length=1, max_length=200)):
    """Server-Sent Events: each snapshot of the profile as soon as the bot sends it
    (events in VkHistoryService.stream_request). Saved when the bot finishes, or as
    a partial result if the search is stopped."""
    if not vk_history_service.normalize_target(user_id):
        raise HTTPException(status_code=400, detail="Enter a VK id, screen name or profile link")
    try:
        await vk_history_service.ensure_client()
    except (telegram_client.TelegramNotConfigured, telegram_client.TelegramNotAuthorized) as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except (OSError, ConnectionError) as e:
        raise HTTPException(status_code=503, detail=f"Could not connect to Telegram: {e}") from e

    async def generate():
        async for event in vk_history_service.stream_request(user_id):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
