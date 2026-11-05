"""Search box, background jobs, entities/triage, phone & IP lookups, case report."""
from collections import Counter, defaultdict
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from services.entities import detect, make_entity, type_label
from services.investigation_service import investigation_service
from services.ip_service import IPLookupError, IPService
from services.job_manager import job_manager
from services.module_registry import MODULES_BY_ID, all_module_status, balances, modules_for, module_status
from services.phone_service import PhoneLookupFailed, PhoneParseError, lookup_phone
from utils.investigation_decorator import save_investigation

router = APIRouter()
templates = Jinja2Templates(directory="templates")
ip_service = IPService()


class JobRequest(BaseModel):
    module: str
    type: str
    value: str
    parent_result_id: Optional[str] = None


class TriageRequest(BaseModel):
    status: Optional[str] = None
    note: Optional[str] = None


class EntityTriageRequest(TriageRequest):
    key: str


class Identifier(BaseModel):
    type: str
    value: str


class ElsewhereRequest(BaseModel):
    items: list[Identifier] = Field(max_length=2000)
    exclude: Optional[UUID] = None


def _require_investigation(investigation_id: UUID) -> dict:
    info = investigation_service.get_investigation_info(investigation_id)
    if info is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return info


# ==================== MODULES ====================

@router.get("/api/modules")
async def list_modules():
    """Every module with what it accepts, its cost/speed and readiness."""
    return {"modules": await all_module_status()}


@router.get("/api/modules/balances")
async def module_balances():
    return {"balances": await balances()}


# ==================== SEARCH BOX ====================

@router.get("/api/lookup/detect")
async def detect_query(q: str = Query(..., min_length=1, max_length=500)):
    """What the query could be, and which modules can look each reading up.

    Earlier lookups of the same identifier in the current investigation are
    included so paid modules aren't run twice by accident.
    """
    current = investigation_service.get_current_investigation()
    candidates = []
    for entity in detect(q):
        previous = investigation_service.previous_lookups(current, entity.key) if current else []
        modules = []
        for module in modules_for(entity.type):
            status = await module_status(module)
            earlier = [p for p in previous if p.get("service") == module.service]
            modules.append({**status, "previous": sorted(earlier, key=lambda p: p.get("timestamp", ""))[-3:]})
        candidates.append({"type": entity.type, "label": type_label(entity.type), "value": entity.value,
                           "display": entity.display, "key": entity.key, "modules": modules})
    return {"query": q, "investigation_id": str(current) if current else None, "candidates": candidates}


# ==================== JOBS ====================

@router.post("/api/jobs")
async def start_job(body: JobRequest, request: Request):
    """Run a module lookup in the background, saved to the current investigation."""
    current = investigation_service.get_current_investigation()
    if not current:
        raise HTTPException(status_code=409, detail="Select or create an investigation first - results are saved there")
    module = MODULES_BY_ID.get(body.module)
    if module is None:
        raise HTTPException(status_code=404, detail="Unknown module")
    entity = make_entity(body.type, body.value)
    if entity is None:
        raise HTTPException(status_code=400, detail=f"Not a valid {type_label(body.type).lower()}")
    status = await module_status(module)
    if not status["ready"]:
        raise HTTPException(status_code=409, detail=f"{module.name} isn't ready: " + "; ".join(status["problems"]))

    # Loopback to this same server: the socket uvicorn is bound to
    host, port = (request.scope.get("server") or ("127.0.0.1", 8000))
    host = "127.0.0.1" if host in ("0.0.0.0", "", None) else ("[::1]" if host == "::" else host)
    try:
        job = job_manager.submit(module.id, entity.type, entity.value, str(current),
                                 base_url=f"http://{host}:{port}",
                                 auth_cookie=request.cookies.get("access_token", ""),
                                 parent_result_id=body.parent_result_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"job": job.public()}


@router.get("/api/jobs")
async def list_jobs(investigation_id: Optional[str] = None, limit: int = Query(50, ge=1, le=300)):
    return {"jobs": job_manager.list(investigation_id, limit)}


@router.delete("/api/jobs/{job_id}")
async def cancel_job(job_id: str):
    if not job_manager.cancel(job_id):
        raise HTTPException(status_code=404, detail="No running job with that id")
    return {"status": "cancelling"}


# ==================== ENTITIES & TRIAGE ====================

@router.get("/api/investigations/{investigation_id}/entities")
def list_entities(investigation_id: UUID, type: Optional[str] = None, q: Optional[str] = None,
                        status: Optional[str] = None, shared: bool = False,
                        limit: int = Query(500, ge=1, le=5000), offset: int = 0):
    """Identifiers found in or searched for this investigation (most relevant first).
    ``shared=1``: only those that other investigations have too."""
    _require_investigation(investigation_id)
    entities = investigation_service.get_entities(investigation_id)
    type_counts = Counter(e["type"] for e in entities)
    shared_keys = investigation_service.shared_entity_keys(investigation_id)
    if shared:
        entities = [e for e in entities if e["key"] in shared_keys]
    if type:
        entities = [e for e in entities if e["type"] == type]
    if status == "untriaged":
        entities = [e for e in entities if not e.get("status")]
    elif status:
        entities = [e for e in entities if e.get("status") == status]
    if q:
        needle = q.lower()
        entities = [e for e in entities if needle in e["value"].lower() or needle in (e.get("note") or "").lower()]
    total = len(entities)
    page = entities[offset:offset + limit]
    elsewhere = investigation_service.investigations_with([e["key"] for e in page if e["key"] in shared_keys],
                                                          exclude=investigation_id)
    # what each source result looked up, so the list can say which result an identifier is in
    targets = {r["result_id"]: r.get("target") for r in investigation_service.get_investigation_results(investigation_id)}
    for entity in page:
        entity["label"] = type_label(entity["type"])
        entity["sources"] = [{**src, "target": targets.get(src.get("result_id"))} for src in entity.get("sources", [])[:20]]
        entity["elsewhere"] = elsewhere.get(entity["key"], [])
    return {"total": total, "types": [{"type": t, "label": type_label(t), "count": c} for t, c in type_counts.most_common()],
            "shared_count": len(shared_keys), "entities": page}


@router.post("/api/entities/elsewhere")
def entities_elsewhere(body: ElsewhereRequest):
    """Which of these identifiers other investigations have, keyed "type:value" as sent."""
    sent: dict[str, str] = {}
    for item in body.items:
        entity = make_entity(item.type, item.value)
        if entity:
            sent[f"{item.type}:{item.value}"] = entity.key
    found = investigation_service.investigations_with(list(sent.values()), exclude=body.exclude)
    return {"matches": {name: found[key] for name, key in sent.items() if key in found}}


@router.get("/api/investigations/{investigation_id}/events")
def list_events(investigation_id: UUID):
    """Dates found inside the results (account created, domain registered, messages...)."""
    _require_investigation(investigation_id)
    return {"events": investigation_service.get_events(investigation_id)}


@router.get("/api/investigations/{investigation_id}/entities/lookups")
def entity_lookups(investigation_id: UUID, type: str, value: str):
    """Earlier lookups of one identifier in this investigation (the pivot menu shows
    them next to each module, so a paid lookup isn't run twice by accident)."""
    _require_investigation(investigation_id)
    entity = make_entity(type, value)
    if entity is None:
        return {"lookups": []}
    lookups = investigation_service.previous_lookups(investigation_id, entity.key)
    return {"lookups": sorted(lookups, key=lambda p: p.get("timestamp", ""), reverse=True)}


@router.patch("/api/investigations/{investigation_id}/entities")
def triage_entity(investigation_id: UUID, body: EntityTriageRequest):
    _require_investigation(investigation_id)
    try:
        entity = investigation_service.set_entity_triage(investigation_id, body.key, body.status, body.note)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return {"entity": entity}


@router.get("/api/investigations/{investigation_id}/results/{result_id}/entities")
def result_entities(investigation_id: UUID, result_id: str):
    _require_investigation(investigation_id)
    entities = investigation_service.entities_for_result(investigation_id, result_id)
    for entity in entities:
        entity["label"] = type_label(entity["type"])
        entity["sources"] = [s for s in entity.get("sources", []) if s.get("result_id") == result_id]
    return {"entities": entities}


@router.patch("/api/investigations/{investigation_id}/results/{result_id}/triage")
def triage_result(investigation_id: UUID, result_id: str, body: TriageRequest):
    _require_investigation(investigation_id)
    try:
        triage = investigation_service.set_result_triage(investigation_id, result_id, body.status, body.note)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if triage is None and investigation_service.get_result(investigation_id, result_id) is None:
        raise HTTPException(status_code=404, detail="Result not found")
    return {"triage": triage}


# ==================== PHONE & IP ====================

@router.get("/api/phone/info")
@save_investigation(service_name="phone", method_name="phone_info")
async def phone_lookup(phone: str = Query(..., min_length=1, max_length=40)) -> dict:
    """Free offline analysis: validity, country, original carrier, line type, messenger links."""
    try:
        return await lookup_phone(phone)
    except PhoneParseError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except PhoneLookupFailed as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/api/ip/lookup")
@save_investigation(service_name="ip", method_name="ip_lookup")
async def ip_lookup(ip: str = Query(..., min_length=3, max_length=60)) -> dict:
    try:
        return await ip_service.lookup_ip(ip)
    except IPLookupError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ==================== REPORT ====================

STATUS_LABELS = {"confirmed": "Confirmed", "important": "Important", "false_positive": "False positive"}


@router.get("/api/investigations/{investigation_id}/report", response_class=HTMLResponse)
def case_report(request: Request, investigation_id: UUID, include: str = Query("findings")):
    """Printable case report. ``include=all`` lists every result, otherwise
    results marked confirmed/important (falling back to all if none are)."""
    info = _require_investigation(investigation_id)
    results = investigation_service.get_investigation_results(investigation_id)
    results.sort(key=lambda r: r.get("timestamp", ""))
    entities = [e for e in investigation_service.get_entities(investigation_id) if e.get("status") != "false_positive"]
    notes = [n for n in investigation_service.get_investigation_notes(investigation_id) if n.get("note_type") != "auto"]

    triaged = [r for r in results if (r.get("triage") or {}).get("status") in ("confirmed", "important")]
    findings = results if include == "all" or not triaged else triaged

    key_entities = [e for e in entities if e.get("status") in ("confirmed", "important")]
    searched = [e for e in entities if e["searched"] and e not in key_entities]
    by_type = defaultdict(list)
    for entity in entities:
        if entity not in key_entities:
            by_type[type_label(entity["type"])].append(entity)

    module_names = {m.service: m.name for m in MODULES_BY_ID.values()}
    return templates.TemplateResponse(request, "report.html", {
        "investigation": info,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "results": results,
        "findings": findings,
        "showing_all": findings is results,
        "key_entities": key_entities,
        "searched": searched,
        "entities_by_type": sorted(by_type.items(), key=lambda kv: -len(kv[1])),
        "notes": notes,
        "module_names": module_names,
        "status_labels": STATUS_LABELS,
        "type_label": type_label,
        "counts": {"results": len(results), "entities": len(entities), "notes": len(notes),
                   "modules": len({r["service_name"] for r in results})},
    })
