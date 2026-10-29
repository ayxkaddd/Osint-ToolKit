from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
import json
from models.resources_models import Module, Resources
from services import plugin_loader

router = APIRouter(prefix="/api/resources")

@router.get("/")
async def get_resources() -> JSONResponse:
    try:
        with open("resources.json", "r") as f:
            resources = Resources.model_validate(json.load(f))
        resources.modules += [Module.model_validate(card) for card in _plugin_cards()]
        return resources
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _plugin_cards() -> list:
    """Dashboard cards for plugins (plugins/)."""
    cards = []
    for plugin in plugin_loader.refresh().values():
        info = plugin.public()
        settings = {f["key"]: {"type": "password" if f["secret"] else "text", "label": f["label"]}
                    for f in info["settings"] if f["own"]}
        cards.append({
            "name": info["name"],
            "description": info["description"] or info["error"] or "",
            "endpoint": info["page"],
            "icon": "puzzle-piece",
            "icon_color": "purple" if info["enabled"] else "gray",
            "icon_type": "fas",
            "tags": ["Plugin"] + [a["label"] for a in info["accepts"]],
            "settings": settings or None,
        })
    return cards
