import json
from pathlib import Path
from typing import Dict, Set

from fastapi import APIRouter, HTTPException

from services import plugin_loader
from utils.config import get_setting, update_env

router = APIRouter(prefix="/api/settings")

RESOURCES_PATH = Path("resources.json")


def allowed_setting_keys() -> Set[str]:
    """Only keys that a module declares in resources.json, or a plugin under its own
    name, can be edited here (never ROOT_PASSWORD, JWT_SECRET, ...)."""
    return plugin_loader.builtin_setting_keys() | plugin_loader.setting_keys()


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
    own_keys = plugin_loader.setting_keys()
    for plugin in plugin_loader.refresh().values():
        fields = []
        for field in plugin.public()["settings"]:
            if field["key"] not in own_keys:
                continue   # another module's key: edited with that module
            value = get_setting(field["key"]) or ""
            fields.append({
                "key": field["key"],
                "label": field["label"],
                "type": "password" if field["secret"] else "text",
                "configured": bool(value),
                "display": _mask(value) if field["secret"] else value,
                "help": field["help"],
            })
        if fields:
            out.append({"module": plugin.name, "endpoint": f"/plugins/{plugin.id}", "fields": fields, "plugin": True})
    return {"modules": out}
