"""Plugins (services/plugin_loader.py): list, run, review/enable, pages."""
from typing import Literal, Optional

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from plugins.sdk import PluginError
from services import plugin_loader
from services.plugin_loader import RunRefused
from utils.investigation_decorator import save_investigation
from utils.stream_reducers import reduce_plugin_stream

router = APIRouter(prefix="/api/plugins")
page_router = APIRouter()
templates = Jinja2Templates(directory="templates")


def _plugin(plugin_id: str) -> plugin_loader.Plugin:
    plugin = plugin_loader.get(plugin_id)
    if not plugin:
        raise HTTPException(status_code=404, detail=f"No plugin '{plugin_id}'")
    return plugin


async def _stream(plugin_id: str, value: str, type: Optional[str]):
    try:
        run = await plugin_loader.prepare(plugin_id, value, type)
    except RunRefused as e:
        raise HTTPException(status_code=e.status, detail=e.detail) from None
    except PluginError as e:
        # The lookup failed before anything was found: an error, not a saved result
        raise HTTPException(status_code=502, detail=str(e)) from None
    return StreamingResponse(plugin_loader.events(run), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("")
async def list_plugins():
    plugins = plugin_loader.refresh()
    return {"plugins": [p.public() for p in plugins.values()]}


@router.post("/reload")
async def reload_plugins():
    plugins = plugin_loader.refresh(force=True)
    return {"plugins": [p.public() for p in plugins.values()]}


@router.get("/client.js")
async def client_script():
    return Response(plugin_loader.client_script(), media_type="text/javascript",
                    headers={"Cache-Control": "no-cache"})


@router.post("/{plugin_id}/run")
@save_investigation(service_name=lambda kwargs: kwargs["plugin_id"], method_name="run",
                    stream_reducer=reduce_plugin_stream)
async def run_plugin(plugin_id: str, value: str = Body(..., max_length=2000), type: Optional[str] = Body(None)):
    """Run a plugin; NDJSON events, saved to the investigation when done."""
    return await _stream(plugin_id, value, type)


@router.post("/{plugin_id}/test")
async def test_plugin(plugin_id: str, value: str = Body(..., max_length=2000), type: Optional[str] = Body(None)):
    """Same as run, but not saved (trying a plugin out)."""
    return await _stream(plugin_id, value, type)


class TrustRequest(BaseModel):
    mode: Literal["approved", "local"]


@router.get("/{plugin_id}/files")
async def plugin_files(plugin_id: str):
    plugin = _plugin(plugin_id)
    return {"plugin": plugin.public(), "files": plugin_loader.plugin_files(plugin)}


@router.post("/{plugin_id}/trust")
async def trust_plugin(plugin_id: str, body: TrustRequest):
    plugin = _plugin(plugin_id)
    plugin_loader.write_trust(plugin.id, body.mode, plugin.sha)
    return _plugin_after_change(plugin.id)


@router.delete("/{plugin_id}/trust")
async def untrust_plugin(plugin_id: str):
    plugin = _plugin(plugin_id)
    plugin_loader.write_trust(plugin.id, None)
    return _plugin_after_change(plugin.id)


def _plugin_after_change(plugin_id: str) -> JSONResponse:
    plugin = plugin_loader.refresh(force=True).get(plugin_id)
    if not plugin:
        raise HTTPException(status_code=404, detail=f"No plugin '{plugin_id}'")
    return JSONResponse(plugin.public())


@router.get("/{plugin_id}/icon")
async def plugin_icon(plugin_id: str):
    plugin = _plugin(plugin_id)
    if not plugin.icon_file:
        raise HTTPException(status_code=404, detail="No icon")
    return FileResponse(plugin.icon_file, headers={"Cache-Control": "private, max-age=3600"})


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@page_router.get("/plugins")
def plugins_page(request: Request):
    return templates.TemplateResponse(request=request, name="plugins.html")


@page_router.get("/plugins/{plugin_id}")
def plugin_page(request: Request, plugin_id: str):
    plugin = plugin_loader.get(plugin_id)
    if not plugin:
        raise HTTPException(status_code=404, detail=f"No plugin '{plugin_id}'")
    return templates.TemplateResponse(request=request, name="plugin.html", context={"plugin": plugin.public()})
