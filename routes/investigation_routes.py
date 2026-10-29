# routes/investigation_routes.py
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, HTTPException, Query, Form, File, UploadFile, Request
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from services.investigation_service import InvestigationService

router = APIRouter(prefix="/api/investigations")
investigation_service = InvestigationService()
templates = Jinja2Templates(directory="templates")

VALID_STATUSES = {"active", "completed", "archived"}


class NoteCreate(BaseModel):
    title: str
    content: str
    note_type: str = "manual"
    related_result_id: Optional[str] = None
    tags: Optional[List[str]] = None


class SnapshotCreate(BaseModel):
    result_id: str


class NoteUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[List[str]] = None


def _require_investigation(investigation_id: UUID) -> dict:
    info = investigation_service.get_investigation_info(investigation_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Investigation with ID {investigation_id} not found")
    return info


async def _read_picture(picture: Optional[UploadFile]) -> Optional[bytes]:
    if picture is None or not picture.filename:
        return None
    data = await picture.read()
    return data or None


# ==================== INVESTIGATION ENDPOINTS ====================

@router.post("/create")
async def create_investigation(
    name: str = Form(...),
    description: str = Form(""),
    investigation_id: Optional[str] = Form(None),
    picture: Optional[UploadFile] = File(None)
) -> JSONResponse:
    """Create a new investigation"""
    if not name.strip():
        raise HTTPException(status_code=400, detail="Name is required")
    inv_id = None
    if investigation_id:
        try:
            inv_id = UUID(investigation_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid investigation_id format") from None

    try:
        created_id = investigation_service.create_investigation(
            name=name.strip(),
            description=description.strip(),
            picture=await _read_picture(picture),
            investigation_id=inv_id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return JSONResponse(content={
        "status": "success",
        "message": "Investigation created successfully",
        "investigation_id": str(created_id),
        "investigation": investigation_service.get_investigation_info(created_id)
    })


@router.post("/set")
async def set_current_investigation(investigation_id: UUID = Form(...)) -> JSONResponse:
    """Set the current active investigation"""
    if not investigation_service.set_current_investigation(investigation_id):
        raise HTTPException(status_code=404, detail=f"Investigation with ID {investigation_id} not found")
    return JSONResponse(content={
        "status": "success",
        "message": f"Current investigation set to {investigation_id}",
        "investigation": investigation_service.get_investigation_info(investigation_id)
    })


@router.get("/current")
async def get_current_investigation() -> JSONResponse:
    """Get the current active investigation with details"""
    current_id = investigation_service.get_current_investigation()
    return JSONResponse(content={
        "status": "success",
        "investigation_id": str(current_id) if current_id else None,
        "investigation": investigation_service.get_investigation_info(current_id) if current_id else None
    })


@router.delete("/clear")
async def clear_investigation() -> JSONResponse:
    """Clear the current investigation"""
    if not investigation_service.clear_investigation():
        raise HTTPException(status_code=500, detail="Failed to clear investigation")
    return JSONResponse(content={"status": "success"})


@router.get("/")
async def list_all_investigations() -> JSONResponse:
    """List all investigations"""
    investigations = investigation_service.list_all_investigations()
    return JSONResponse(content={
        "status": "success",
        "count": len(investigations),
        "investigations": investigations
    })


@router.get("/results/legacy")
async def list_module_history(
    service_name: Optional[str] = Query(None, description="Filter by service name"),
    method_name: Optional[str] = Query(None, description="Filter by method name"),
    limit: int = Query(50, ge=1, le=500)
) -> JSONResponse:
    """Result summaries of the current investigation for one module (module history panel).

    Payloads are not included; fetch one with GET /{investigation_id}/results/{result_id}.
    """
    results = investigation_service.list_investigations(
        service_name=service_name,
        method_name=method_name,
        limit=limit
    )
    return JSONResponse(content={
        "status": "success",
        "count": len(results),
        "results": results
    })


@router.get("/{investigation_id}")
async def get_investigation(investigation_id: UUID) -> JSONResponse:
    """Investigation info + result summaries"""
    result = investigation_service.get_investigation_result(investigation_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Investigation with ID {investigation_id} not found")
    return JSONResponse(content={"status": "success", **result})


@router.get("/{investigation_id}/info")
async def get_investigation_info(investigation_id: UUID) -> JSONResponse:
    """Get investigation metadata only"""
    return JSONResponse(content={
        "status": "success",
        "investigation": _require_investigation(investigation_id)
    })


@router.get("/{investigation_id}/picture")
async def get_investigation_picture(investigation_id: UUID):
    """Case picture (resized WebP). The URL carries a version, so it can be cached."""
    path = investigation_service.get_picture_path(investigation_id)
    if path is None:
        raise HTTPException(status_code=404, detail="No picture")
    return FileResponse(path, media_type="image/webp",
                        headers={"Cache-Control": "private, max-age=31536000, immutable"})


@router.get("/{investigation_id}/results")
async def get_investigation_results(investigation_id: UUID) -> JSONResponse:
    """Summaries of every result (newest first). Fetch payloads per result."""
    _require_investigation(investigation_id)
    results = investigation_service.get_investigation_results(investigation_id)
    return JSONResponse(content={
        "status": "success",
        "investigation_id": str(investigation_id),
        "results_count": len(results),
        "results": results
    })


@router.get("/{investigation_id}/results/{result_id}")
async def get_investigation_result_detail(investigation_id: UUID, result_id: str) -> JSONResponse:
    """Full record for one result, including grouped follow-up lookups (children)."""
    _require_investigation(investigation_id)
    record = investigation_service.get_result(investigation_id, result_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Result not found")
    return JSONResponse(content={"status": "success", "result": record})


@router.get("/{investigation_id}/results/{result_id}/references")
async def get_result_references(investigation_id: UUID, result_id: str) -> JSONResponse:
    """Notes that link to this result or hold a snapshot of it (asked before deleting it)."""
    _require_investigation(investigation_id)
    return JSONResponse(content={"status": "success",
                                 "notes": investigation_service.result_references(investigation_id, result_id)})


@router.delete("/{investigation_id}/results/{result_id}")
async def delete_investigation_result(investigation_id: UUID, result_id: str) -> JSONResponse:
    _require_investigation(investigation_id)
    if not investigation_service.delete_result(investigation_id, result_id):
        raise HTTPException(status_code=404, detail="Result not found")
    return JSONResponse(content={"status": "success"})


@router.get("/{investigation_id}/view", response_class=HTMLResponse)
async def view_investigation_results(request: Request, investigation_id: UUID):
    """Render investigation results page"""
    _require_investigation(investigation_id)
    return templates.TemplateResponse(
        request,
        "investigation_results.html",
        {"investigation_id": str(investigation_id)}
    )


@router.get("/{investigation_id}/export")
async def export_investigation(investigation_id: UUID) -> JSONResponse:
    """Export complete investigation data and results as JSON"""
    info = _require_investigation(investigation_id)
    results = investigation_service.get_full_results(investigation_id)
    notes = investigation_service.get_investigation_notes(investigation_id)
    export_data = {
        "investigation": info,
        "results_count": len(results),
        "results": results,
        "notes_count": len(notes),
        "notes": notes,
        "note_snapshots": investigation_service.get_snapshots(investigation_id),
    }
    clean_name = "".join(c for c in info.get("name", "investigation") if c.isalnum() or c in (" ", "-", "_")).strip().replace(" ", "_")
    filename = f"{clean_name or 'investigation'}_{investigation_id}.json"
    return JSONResponse(
        content=export_data,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.put("/{investigation_id}")
async def update_investigation(investigation_id: UUID, request: Request) -> JSONResponse:
    """Update investigation metadata. Accepts multipart/form data (with optional
    ``picture`` file and ``remove_picture``) or a JSON body."""
    content_type = request.headers.get("content-type", "")
    picture = None
    if content_type.startswith("application/json"):
        try:
            data = await request.json()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid JSON body") from None
    else:
        form = await request.form()
        data = {k: v for k, v in form.items() if not isinstance(v, UploadFile)}
        upload = form.get("picture")
        if isinstance(upload, UploadFile):
            picture = await _read_picture(upload)

    status = data.get("status")
    if status is not None and status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"Status must be one of {sorted(VALID_STATUSES)}")
    name = data.get("name")
    if name is not None and not str(name).strip():
        raise HTTPException(status_code=400, detail="Name cannot be empty")

    try:
        success = investigation_service.update_investigation(
            investigation_id=investigation_id,
            name=str(name).strip() if name is not None else None,
            description=data.get("description"),
            picture=picture,
            status=status,
            remove_picture=str(data.get("remove_picture", "")).lower() in ("1", "true", "yes", "on")
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if not success:
        raise HTTPException(status_code=404, detail=f"Investigation with ID {investigation_id} not found")
    return JSONResponse(content={
        "status": "success",
        "message": "Investigation updated successfully",
        "investigation": investigation_service.get_investigation_info(investigation_id)
    })


@router.delete("/{investigation_id}")
async def delete_investigation(investigation_id: UUID) -> JSONResponse:
    """Delete investigation and all its results"""
    if not investigation_service.delete_investigation(investigation_id):
        raise HTTPException(status_code=404, detail=f"Investigation with ID {investigation_id} not found")
    return JSONResponse(content={
        "status": "success",
        "message": f"Investigation {investigation_id} deleted successfully"
    })


# ==================== NOTES ENDPOINTS ====================

@router.post("/{investigation_id}/notes")
async def create_note(investigation_id: UUID, note: NoteCreate) -> JSONResponse:
    """Create a new note for an investigation"""
    try:
        note_id = investigation_service.create_note(
            investigation_id=investigation_id,
            title=note.title,
            content=note.content,
            note_type=note.note_type,
            related_result_id=note.related_result_id,
            tags=note.tags
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return JSONResponse(content={
        "status": "success",
        "message": "Note created successfully",
        "note_id": str(note_id)
    }, status_code=201)


@router.get("/{investigation_id}/notes")
async def get_investigation_notes(
    investigation_id: UUID,
    note_type: Optional[str] = Query(None, description="Filter by note type"),
    tags: Optional[str] = Query(None, description="Comma-separated list of tags to filter by")
) -> JSONResponse:
    """Get all notes for an investigation with optional filtering"""
    _require_investigation(investigation_id)
    tags_list = [tag.strip() for tag in tags.split(",")] if tags else None
    notes = investigation_service.get_investigation_notes(
        investigation_id=investigation_id,
        note_type=note_type,
        tags=tags_list
    )
    return JSONResponse(content={
        "status": "success",
        "investigation_id": str(investigation_id),
        "notes_count": len(notes),
        "notes": notes
    })


@router.get("/{investigation_id}/notes/view", response_class=HTMLResponse)
async def view_investigation_notes(request: Request, investigation_id: UUID):
    """Render investigation notes page (registered before /{note_id} so "view"
    is not captured as a note id)."""
    _require_investigation(investigation_id)
    return templates.TemplateResponse(
        request,
        "notes.html",
        {"investigation_id": str(investigation_id)}
    )


@router.post("/{investigation_id}/snapshots")
async def create_snapshot(investigation_id: UUID, body: SnapshotCreate) -> JSONResponse:
    """Copy a result for a note, so the note keeps it even if the result is deleted."""
    _require_investigation(investigation_id)
    snapshot = investigation_service.create_snapshot(investigation_id, body.result_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Result not found")
    return JSONResponse(content={"status": "success", "snapshot": snapshot}, status_code=201)


@router.get("/{investigation_id}/snapshots/{snapshot_id}")
async def get_snapshot(investigation_id: UUID, snapshot_id: str) -> JSONResponse:
    _require_investigation(investigation_id)
    snapshot = investigation_service.get_snapshot(investigation_id, snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return JSONResponse(content={"status": "success", "snapshot": snapshot})


@router.get("/{investigation_id}/notes/{note_id}")
async def get_note(investigation_id: UUID, note_id: UUID) -> JSONResponse:
    note = investigation_service.get_note(investigation_id, note_id)
    if note is None:
        raise HTTPException(status_code=404, detail=f"Note with ID {note_id} not found")
    return JSONResponse(content={"status": "success", "note": note})


@router.put("/{investigation_id}/notes/{note_id}")
async def update_note(investigation_id: UUID, note_id: UUID, note: NoteUpdate) -> JSONResponse:
    success = investigation_service.update_note(
        investigation_id=investigation_id,
        note_id=note_id,
        title=note.title,
        content=note.content,
        tags=note.tags
    )
    if not success:
        raise HTTPException(status_code=404, detail=f"Note with ID {note_id} not found")
    return JSONResponse(content={"status": "success", "message": "Note updated successfully"})


@router.delete("/{investigation_id}/notes/{note_id}")
async def delete_note(investigation_id: UUID, note_id: UUID) -> JSONResponse:
    if not investigation_service.delete_note(investigation_id, note_id):
        raise HTTPException(status_code=404, detail=f"Note with ID {note_id} not found")
    return JSONResponse(content={"status": "success", "message": f"Note {note_id} deleted successfully"})
