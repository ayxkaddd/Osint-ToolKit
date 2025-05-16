from fastapi import APIRouter, HTTPException, Request
from auth.auth_handler import TelegramAuthHandler
from fastapi.responses import JSONResponse
from models.telegram_models import VKProfileHistoryResponse
from services.telegram_service import TelegramService

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

@auth_router.get("/status")
async def auth_status():
    status = await auth_handler.connect()
    return {"authorized": status}

telegram_service = TelegramService()

@bot_router.get("/search")
async def search_vk_profile(user_id: str) -> VKProfileHistoryResponse:
    try:
        result = await telegram_service.send_request(user_id)
        return result
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)}
        )