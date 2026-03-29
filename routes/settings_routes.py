from fastapi import APIRouter, HTTPException
from config.token_manager import tokens
from models.token_models import TokenUpdate, TokensResponse, TokenUpdateResponse

router = APIRouter(prefix="/api/tokens", tags=["tokens"])


@router.get("/", response_model=TokensResponse)
async def get_tokens():
    """List all tokens (values are redacted)."""
    return TokensResponse(
        tokens=tokens.get_all(redact=True),
        missing_required=tokens.missing_required(),
    )


@router.patch("/", response_model=TokenUpdateResponse)
async def update_tokens(body: TokenUpdate):
    """Update one or more tokens and persist to .env."""
    try:
        changed = tokens.update(body.updates)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return TokenUpdateResponse(
        changed=changed,
        message=f"{len(changed)} token(s) updated." if changed else "No changes.",
    )


@router.post("/reload")
async def reload_tokens():
    """Force reload from .env (after a manual edit)."""
    tokens.reload()
    return {"message": "Token cache reloaded."}