import json

from fastapi import APIRouter, HTTPException, Response
from pydantic import ValidationError

from models.gitfive_models import User
from services.git_service import GitFiveError, GitService
from utils.investigation_decorator import save_investigation

router = APIRouter(prefix="/api/gitfive")
git_service = GitService()


@router.get("/query")
@save_investigation(service_name="gitfive", method_name="lookup_gitfive")
async def gitfive_query(username: str, response: Response, refresh: bool = False) -> User:
    """GitFive profile. Results are cached per username; ``refresh=true`` re-runs it."""
    try:
        data, cached = await git_service.run_gitfive(username, refresh=refresh)
    except GitFiveError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=502, detail="GitFive produced unreadable output") from e

    response.headers["X-Result-Cached"] = "true" if cached else "false"
    try:
        return User.model_validate(data)
    except ValidationError as e:
        raise HTTPException(status_code=502, detail=f"Unexpected GitFive output: {e.errors()[0].get('msg')}") from e
