"""Search box, background jobs, entities/triage, phone & IP lookups, case report."""
import re
from collections import Counter, defaultdict
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from services.entities import detect, make_entity, norm_phone, phone_suggestions, type_label
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

def _browser_regions(request: Request) -> list[str]:
    """Countries of the browser's languages ("en-US,ru-RU;q=0.9" -> US, RU), likeliest first."""
    regions = []
    for part in (request.headers.get("accept-language") or "").split(","):
        tag = part.split(";")[0].strip()
        if "-" in tag:
            region = tag.rsplit("-", 1)[1].upper()
            if len(region) == 2 and region.isalpha() and region not in regions:
                regions.append(region)
    return regions[:5]


@router.get("/api/lookup/detect")
async def detect_query(request: Request, q: str = Query(..., min_length=1, max_length=500)):
    """What the query could be, and which modules can look each reading up.

    Earlier lookups of the same identifier in the current investigation are
    included so paid modules aren't run twice by accident. A phone number typed
    without its country code comes back in ``suggestions`` (the full numbers it
    could be) instead of being guessed.
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
    return {"query": q, "investigation_id": str(current) if current else None, "candidates": candidates,
            "suggestions": phone_suggestions(q, _browser_regions(request))}


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
    entity = make_entity(body.type, body.value, typed=True)
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
    in_notes = investigation_service.notes_mentioning(investigation_id, page)
    for entity in page:
        entity["notes"] = in_notes.get(entity["key"], [])
    return {"total": total, "types": [{"type": t, "label": type_label(t), "count": c} for t, c in type_counts.most_common()],
            "shared_count": len(shared_keys), "entities": page}


@router.post("/api/entities/elsewhere")
def entities_elsewhere(body: ElsewhereRequest):
    """Which of these identifiers other investigations have, keyed "type:value" as sent."""
    sent: dict[str, str] = {}
    for item in body.items:
        entity = make_entity(item.type, item.value, typed=True)
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
    entity = make_entity(type, value, typed=True)
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
async def phone_lookup(request: Request, phone: str = Query(..., min_length=1, max_length=40)) -> dict:
    """Free offline analysis: validity, country, original carrier, line type, messenger links.

    A number without its country code is refused rather than guessed (its first digits
    would be taken for a country: 415 555 2671 became a Swiss number). The answer names
    the numbers it could be; the page offers them (/api/lookup/detect ``suggestions``)."""
    digits = re.sub(r"[^\d+]", "", phone)
    if re.search(r"\d{6}", re.sub(r"\D", "", digits)) and not digits.startswith(("+", "00")) \
            and not norm_phone(digits, assume_international=True):
        options = phone_suggestions(phone, _browser_regions(request))
        could_be = "; ".join(f"{o['display']} ({o['country']})" for o in options)
        raise HTTPException(status_code=400, detail="This number has no country code" + (
            f" - it could be {could_be}. Enter it with the code." if options
            else ". Enter it with the code, e.g. +380 50 123 4567"))
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
REPORT_MAX_EVENTS = 500
NOTE_REFERENCE = re.compile(r"!?\[\[([a-z_]+):([^\]|\n]+)(?:\|([^\]\n]*))?\]\]")


def _event_when(date: Optional[str], precision: Optional[str]) -> str:
    """An event date as precise as it is known: "2019", "Mar 2019", "5 Mar 2019", "2019-03-05 10:00 UTC"."""
    if not date:
        return ""
    try:
        if precision == "year":
            return date[:4]
        if precision == "month":
            return datetime.strptime(date[:7], "%Y-%m").strftime("%b %Y")
        if precision == "time":
            return datetime.fromisoformat(date).strftime("%Y-%m-%d %H:%M UTC")
        day = datetime.strptime(date[:10], "%Y-%m-%d")
        return f"{day.day} {day:%b %Y}"
    except ValueError:
        return date


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
    # services several lookups save under (a plain WHOIS lookup isn't "WHOIS history")
    module_names.update({"whois": "WHOIS", "manual": "Added manually"})
    # references in notes ([[email:a@b.c|label]], [[result:<id>|label]]) read as their label or value
    for note in notes:
        note["content"] = NOTE_REFERENCE.sub(lambda m: m.group(3) or m.group(2), note.get("content") or "")

    # dates inside the results, oldest first; a series (all messages of a chat) is one row
    events = sorted(investigation_service.get_events(investigation_id), key=lambda e: e["date"])
    for event in events:
        event["when"] = _event_when(event["date"], event.get("precision"))
        if event.get("count"):
            event["when"] += f" – {_event_when(event.get('end'), event.get('end_precision'))}"
    # Nothing from other investigations goes in: a report is shared with people outside
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
        "events": events[:REPORT_MAX_EVENTS],
        "events_total": len(events),
        "manual_items": investigation_service.manual_items(investigation_id),
        "tracking_ids": investigation_service.tracking_ids(investigation_id),
        "counts": {"results": len(results), "entities": len(entities), "notes": len(notes),
                   "modules": len({r["service_name"] for r in results})},
    })
