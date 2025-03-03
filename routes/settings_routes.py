from fastapi import APIRouter, HTTPException
from typing import Dict
import os
from pathlib import Path
from dotenv import set_key, load_dotenv

router = APIRouter(prefix="/api/settings")

@router.post("/update")
async def update_settings(settings: Dict[str, str]):
    try:
        env_path = Path(".env")

        for key, value in settings.items():
            set_key(str(env_path), key, value)
            os.environ[key] = value

        # reload environment variables
        load_dotenv(override=True)

        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
