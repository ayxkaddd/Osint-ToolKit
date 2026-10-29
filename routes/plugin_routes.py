"""Plugins (services/plugin_loader.py): list, run, review/enable, pages."""
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from plugins.sdk import PluginError
from services import plugin_builder, plugin_loader
from services.entities import ENTITY_TYPES
from services.plugin_builder import DraftError
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


async def _stream(plugin_id: str, value: str, type: Optional[str], actions: Optional[List[str]] = None):
    try:
        run = await plugin_loader.prepare(plugin_id, value, type, actions)
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


# ---------------------------------------------------------------------------
# Builder (no-code plugins from the UI) - before the /{plugin_id}/... routes
# ---------------------------------------------------------------------------

class CurlRequest(BaseModel):
    command: str
    example: str = ""


class DraftRequest(BaseModel):
    id: str
    manifest: Dict[str, Any]
    value: str = ""
    type: Optional[str] = None
    settings: Dict[str, Optional[str]] = {}   # API keys typed in the builder (not saved by test)
    detect: bool = False


class PreviewRequest(BaseModel):
    id: str
    manifest: Dict[str, Any]
    raw: Any = None
    value: str = ""
    type: str = ""


class SaveRequest(BaseModel):
    id: str
    manifest: Optional[Dict[str, Any]] = None
    yaml: Optional[str] = None
    settings: Dict[str, Optional[str]] = {}
    editing: bool = False


def _draft_error(e: DraftError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(e))


@router.post("/builder/curl")
async def builder_curl(body: CurlRequest):
    try:
        return plugin_builder.parse_curl(body.command, body.example)
    except DraftError as e:
        raise _draft_error(e) from None


@router.post("/builder/test")
async def builder_test(body: DraftRequest):
    """Send a draft plugin's request: the answer, its cards and a suggested mapping. Not saved."""
    try:
        return await plugin_builder.test_draft(body.id, body.manifest, body.value, body.type, body.settings, body.detect)
    except DraftError as e:
        raise _draft_error(e) from None


@router.post("/builder/preview")
async def builder_preview(body: PreviewRequest):
    try:
        return {"items": plugin_builder.preview(body.id, body.manifest, body.raw, body.value, body.type)}
    except DraftError as e:
        raise _draft_error(e) from None


class DetectRequest(BaseModel):
    raw: Any = None
    format: Literal["json", "text"] = "json"


@router.post("/builder/detect")
async def builder_detect(body: DetectRequest):
    """A results mapping for an answer already fetched (no request)."""
    return {"suggestion": plugin_builder.suggest_mapping(body.raw, body.format)}


@router.post("/builder/yaml")
async def builder_yaml(body: PreviewRequest):
    """plugin.yaml for the form's manifest, and whether it is valid."""
    error = None
    try:
        plugin_builder.draft_plugin(body.id, body.manifest)
    except DraftError as e:
        error = str(e)
    return {"yaml": plugin_builder.to_yaml(body.manifest), "error": error}


@router.post("/builder/save")
async def builder_save(body: SaveRequest):
    try:
        plugin = plugin_builder.save_draft(body.id, body.manifest, body.yaml, body.settings, body.editing)
    except DraftError as e:
        raise _draft_error(e) from None
    return plugin.public()


@router.get("/{plugin_id}/manifest")
async def plugin_manifest(plugin_id: str):
    """plugin.yaml of a plugin, for editing or duplicating it in the builder."""
    try:
        return plugin_builder.load_for_builder(_plugin(plugin_id))
    except DraftError as e:
        raise _draft_error(e) from None


@router.delete("/{plugin_id}")
async def delete_plugin(plugin_id: str):
    try:
        plugin_builder.delete_plugin(_plugin(plugin_id))
    except DraftError as e:
        raise _draft_error(e) from None
    return {"deleted": plugin_id}


@router.post("/{plugin_id}/run")
@save_investigation(service_name=lambda kwargs: kwargs["plugin_id"], method_name="run",
                    stream_reducer=reduce_plugin_stream)
async def run_plugin(plugin_id: str, value: str = Body(..., max_length=2000), type: Optional[str] = Body(None),
                     actions: Optional[List[str]] = Body(None)):
    """Run a plugin (only the lookups in actions, if given); NDJSON events, saved to the investigation."""
    return await _stream(plugin_id, value, type, actions)


@router.post("/{plugin_id}/test")
async def test_plugin(plugin_id: str, value: str = Body(..., max_length=2000), type: Optional[str] = Body(None),
                      actions: Optional[List[str]] = Body(None)):
    """Same as run, but not saved (trying a plugin out)."""
    return await _stream(plugin_id, value, type, actions)


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


@page_router.get("/plugins/builder")
def plugin_builder_page(request: Request):
    return templates.TemplateResponse(request=request, name="plugin_builder.html",
                                      context={"entity_types": ENTITY_TYPES})


@page_router.get("/plugins/{plugin_id}")
def plugin_page(request: Request, plugin_id: str):
    plugin = plugin_loader.get(plugin_id)
    if not plugin:
        raise HTTPException(status_code=404, detail=f"No plugin '{plugin_id}'")
    return templates.TemplateResponse(request=request, name="plugin.html", context={"plugin": plugin.public()})
