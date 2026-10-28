import json
from pathlib import Path
from typing import Dict, Set

from fastapi import APIRouter, HTTPException

from utils.config import get_setting, update_env

router = APIRouter(prefix="/api/settings")

RESOURCES_PATH = Path("resources.json")


def allowed_setting_keys() -> Set[str]:
    """Only keys that a module declares in resources.json can be edited here
    (never ROOT_PASSWORD, JWT_SECRET, ...)."""
    try:
        modules = json.loads(RESOURCES_PATH.read_text()).get("modules", [])
    except (OSError, json.JSONDecodeError):
        return set()
    return {key.upper() for module in modules for key in (module.get("settings") or {})}


@router.post("/update")
async def update_settings(settings: Dict[str, str]):
    allowed = allowed_setting_keys()
    rejected = sorted(key for key in settings if key.upper() not in allowed)
    if rejected:
        raise HTTPException(status_code=400, detail=f"Not an editable setting: {', '.join(rejected)}")

    # A blank field means "keep the current value", not "erase the key"
    updates = {key.upper(): value.strip() for key, value in settings.items() if value and value.strip()}
    if updates:
        update_env(updates)
    return {"success": True, "updated": sorted(updates)}


def _mask(value: str) -> str:
    """Never send stored secrets back: just enough to recognise which key it is."""
    if not value:
        return ""
    return "••••" + value[-4:] if len(value) > 8 else "••••"


@router.get("")
async def list_settings():
    """Editable settings per module with whether each is configured (values masked)."""
    try:
        modules = json.loads(RESOURCES_PATH.read_text()).get("modules", [])
    except (OSError, json.JSONDecodeError):
        modules = []
    out = []
    for module in modules:
        fields = []
        for key, config in (module.get("settings") or {}).items():
            value = get_setting(key.upper()) or ""
            secret = config.get("type") == "password"
            fields.append({
                "key": key.upper(),
                "label": config.get("label", key),
                "type": config.get("type", "text"),
                "configured": bool(value),
                "display": _mask(value) if secret else value,
            })
        if fields:
            out.append({"module": module.get("name"), "endpoint": module.get("endpoint"), "fields": fields})
    return {"modules": out}
