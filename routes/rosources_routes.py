from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
import json
from models.resources_models import Resourses

router = APIRouter(prefix="/api/resources")

@router.get("/")
async def get_resources() -> JSONResponse:
    try:
        with open("resources.json", "r") as f:
            return Resourses.model_validate(json.load(f))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
