import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from services.git_service import GitService

from models.gitfive_models import User

router = APIRouter(prefix="/api/gitfive")
git_service = GitService()

@router.get("/query")
async def gitfive_query(username: str) -> User:
    try:
        result_path = git_service.run_gitfive(username)
        with open(result_path, "r") as f:
            data = json.load(f)
            return User.model_validate(data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
