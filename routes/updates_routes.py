import logging
import subprocess

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from utils.config import get_setting

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/updates")

GITHUB_API = "https://api.github.com"


def _local_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning("Could not read local commit: %s", e)
    return None


@router.get("/check")
async def check_updates():
    """Compare the local HEAD with the latest commit on the configured GitHub repo.

    Returns the newest commit's details when the local checkout is behind,
    null when up to date, or {"configured": false} when UPDATE_REPO isn't set.
    """
    repo = get_setting("UPDATE_REPO")  # e.g. "owner/name"
    branch = get_setting("UPDATE_BRANCH", "main")
    if not repo:
        return JSONResponse({"configured": False})

    local = _local_commit()

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{GITHUB_API}/repos/{repo}/commits/{branch}",
                headers={"Accept": "application/vnd.github+json"},
            )
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("Update check failed: %s", e)
        return JSONResponse(None)

    remote_sha = data.get("sha")
    if not remote_sha or remote_sha == local:
        return JSONResponse(None)

    commit = data.get("commit", {})
    author = commit.get("author", {})
    stats = data.get("stats", {})
    return JSONResponse({
        "sha": remote_sha,
        "committer": author.get("name", "unknown"),
        "author_avatar": (data.get("author") or {}).get("avatar_url", "/static/avatar_placeholder.png"),
        "date": author.get("date"),
        "message": commit.get("message", ""),
        "commit_url": data.get("html_url", f"https://github.com/{repo}"),
        "stats": {
            "additions": stats.get("additions", 0),
            "deletions": stats.get("deletions", 0),
            "total": stats.get("total", 0),
        },
    })
