import asyncio
import json
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from services.ns_service import NsLookupError, NsService
from services.whois_service import WhoisService
from utils.investigation_decorator import save_investigation
from services.fingerprint_service import FingerprintError, fingerprint_domains
from utils.stream_reducers import reduce_fingerprints, reduce_whois_analysis

router = APIRouter(prefix="/api/ns")
ns_service = NsService()
whois_service = WhoisService()

WHOIS_CONCURRENCY = 8


class WhoisAnalysisRequest(BaseModel):
    domains: List[str] = Field(..., min_length=1, max_length=1000)


@router.get("/search")
@save_investigation(service_name="ns", method_name="lookup_ns")
async def get_domains(ns1: str, ns2: str, investigation_id: Optional[str] = None) -> List[str]:
    try:
        return await asyncio.to_thread(ns_service.get_shared_domains, ns1.strip(), ns2.strip())
    except HTTPException:
        raise
    except NsLookupError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/fingerprint")
@save_investigation(service_name="ns", method_name="fingerprint", stream_reducer=reduce_fingerprints)
async def fingerprint(body: WhoisAnalysisRequest, parent_result_id: Optional[str] = None):
    """httpx fingerprint of every domain of an NS lookup (NDJSON, one line per
    answering domain), saved as a ``fingerprint`` result under the NS lookup."""
    async def generate():
        try:
            async for event in fingerprint_domains(body.domains):
                yield json.dumps(event, default=str) + "\n"
        except FingerprintError as e:
            yield json.dumps({"type": "error", "error": str(e)}) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/whois-analysis")
@save_investigation(service_name="ns", method_name="whois_analysis", stream_reducer=reduce_whois_analysis)
async def whois_analysis(body: WhoisAnalysisRequest, parent_result_id: Optional[str] = None):
    """WHOIS every domain of an NS lookup, streaming one NDJSON line per domain.

    Saved as a single ``whois_analysis`` result, attached to the NS lookup given
    by ``parent_result_id`` (or the X-Parent-Result-ID header).
    """
    domains = list(dict.fromkeys(d.strip().lower() for d in body.domains if d.strip()))

    async def lookup(domain: str, semaphore: asyncio.Semaphore) -> dict:
        async with semaphore:
            try:
                data = await whois_service.lookup_whois(domain)
                return {"type": "domain", "domain": domain, "ok": True, "whois": data}
            except HTTPException as e:
                return {"type": "domain", "domain": domain, "ok": False, "error": str(e.detail)}
            except Exception as e:
                return {"type": "domain", "domain": domain, "ok": False, "error": str(e) or type(e).__name__}

    async def generate():
        semaphore = asyncio.Semaphore(WHOIS_CONCURRENCY)
        tasks = [asyncio.create_task(lookup(d, semaphore)) for d in domains]
        try:
            for done, finished in enumerate(asyncio.as_completed(tasks), start=1):
                event = await finished
                event.update(done=done, total=len(tasks))
                yield json.dumps(event, default=str) + "\n"
            yield json.dumps({"type": "complete", "total": len(tasks)}) + "\n"
        finally:
            for task in tasks:
                task.cancel()

    return StreamingResponse(generate(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
