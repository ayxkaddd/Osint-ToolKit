"""Background lookups.

A job calls a module's own API endpoint over loopback HTTP, exactly like the
module page would, so results are saved/grouped by the same decorator and
streamed endpoints report progress as they go. Each job is pinned to the
investigation that was active when it started (X-Investigation-ID), so
switching investigations mid-job can't misfile results.
"""
import asyncio
import json
import logging
import uuid
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from services.investigation_service import summarize
from services.module_registry import MODULES_BY_ID, Module

logger = logging.getLogger(__name__)

MAX_JOBS_KEPT = 300
MAX_RUNNING = 4
RESULT_ID_HEADER = "x-investigation-result-id"


@dataclass
class Job:
    id: str
    module_id: str
    module_name: str
    entity_type: str
    value: str
    investigation_id: str
    parent_result_id: Optional[str] = None
    status: str = "queued"          # queued / running / done / failed / cancelled
    progress: Dict[str, Any] = field(default_factory=dict)
    summary: Optional[str] = None
    result_id: Optional[str] = None
    error: Optional[str] = None
    module_page: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: Optional[str] = None
    finished_at: Optional[str] = None

    def public(self) -> Dict[str, Any]:
        return asdict(self)


class JobManager:
    def __init__(self):
        self.jobs: "OrderedDict[str, Job]" = OrderedDict()
        self._tasks: Dict[str, asyncio.Task] = {}
        self._global: Optional[asyncio.Semaphore] = None
        self._per_module: Dict[str, asyncio.Semaphore] = {}

    def _sem(self, module: Module) -> asyncio.Semaphore:
        if module.id not in self._per_module:
            self._per_module[module.id] = asyncio.Semaphore(module.concurrency)
        return self._per_module[module.id]

    def submit(self, module_id: str, entity_type: str, value: str, investigation_id: str,
               base_url: str, auth_cookie: str, parent_result_id: Optional[str] = None) -> Job:
        module = MODULES_BY_ID.get(module_id)
        if module is None:
            raise ValueError(f"Unknown module {module_id}")
        if entity_type not in module.accepts:
            raise ValueError(f"{module.name} can't look up a {entity_type}")
        if self._global is None:
            self._global = asyncio.Semaphore(MAX_RUNNING)

        job = Job(id=uuid.uuid4().hex[:12], module_id=module.id, module_name=module.name,
                  entity_type=entity_type, value=value, investigation_id=investigation_id,
                  parent_result_id=parent_result_id, module_page=module.page)
        self.jobs[job.id] = job
        while len(self.jobs) > MAX_JOBS_KEPT:
            oldest_id, oldest = next(iter(self.jobs.items()))
            if oldest.status in ("queued", "running"):
                break
            self.jobs.pop(oldest_id)
        self._tasks[job.id] = asyncio.create_task(self._run(job, module, base_url, auth_cookie))
        return job

    def list(self, investigation_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        jobs = [j for j in reversed(self.jobs.values()) if not investigation_id or j.investigation_id == investigation_id]
        return [j.public() for j in jobs[:limit]]

    def get(self, job_id: str) -> Optional[Job]:
        return self.jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        task = self._tasks.get(job_id)
        job = self.jobs.get(job_id)
        if not task or not job or job.status not in ("queued", "running"):
            return False
        task.cancel()
        return True

    async def _run(self, job: Job, module: Module, base_url: str, auth_cookie: str) -> None:
        spec = module.accepts[job.entity_type]
        request_args = spec.build(job.value)
        headers = {"X-Investigation-ID": job.investigation_id}
        if job.parent_result_id:
            headers["X-Parent-Result-ID"] = job.parent_result_id
        global_sem = self._global or asyncio.Semaphore(MAX_RUNNING)  # created in submit()
        try:
            async with global_sem, self._sem(module):
                job.status = "running"
                job.started_at = datetime.now().isoformat()
                async with httpx.AsyncClient(base_url=base_url, cookies={"access_token": auth_cookie},
                                             timeout=httpx.Timeout(30, read=None)) as client:
                    if spec.stream:
                        await self._run_stream(client, job, spec.method, spec.path, headers, request_args)
                    else:
                        response = await client.request(spec.method, spec.path, headers=headers, **request_args)
                        self._finish(job, response, self._json(response))
        except asyncio.CancelledError:
            job.status = "cancelled"
            job.error = "Cancelled - partial results (if any) were saved"
        except httpx.HTTPError as e:
            job.status = "failed"
            job.error = f"Request failed: {e}"
        except Exception as e:  # never let a job crash silently
            logger.exception("Job %s failed", job.id)
            job.status = "failed"
            job.error = str(e) or type(e).__name__
        finally:
            job.finished_at = datetime.now().isoformat()
            self._tasks.pop(job.id, None)

    @staticmethod
    def _json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return None

    def _finish(self, job: Job, response: httpx.Response, payload: Any) -> None:
        job.result_id = response.headers.get(RESULT_ID_HEADER) or job.result_id
        if response.status_code >= 400:
            detail = payload.get("detail") or payload.get("message") if isinstance(payload, dict) else None
            if isinstance(detail, list):
                detail = ", ".join(str(d.get("msg", d)) for d in detail)
            job.status = "failed"
            job.error = str(detail or f"HTTP {response.status_code}")
            return
        job.status = "done"
        job.summary = summarize(payload)

    async def _run_stream(self, client, job: Job, method, path, headers, request_args) -> None:
        found = checked = 0
        last_event: Any = None
        async with client.stream(method, path, headers=headers, **request_args) as response:
            job.result_id = response.headers.get(RESULT_ID_HEADER)
            if response.status_code >= 400:
                await response.aread()
                self._finish(job, response, self._json(response))
                return
            async for line in response.aiter_lines():
                line = line.strip()
                if line.startswith("data:"):
                    line = line[5:].strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                last_event = event
                kind = event.get("event_type") or event.get("type")
                data = event.get("data") if isinstance(event.get("data"), dict) else event
                if kind == "search_started":
                    job.progress["total"] = data.get("total_sites")
                elif kind == "site_result":
                    checked += 1
                    found += data.get("status") == "found"
                    job.progress.update(done=checked, found=found)
                elif kind == "domain":
                    job.progress.update(done=data.get("done"), total=data.get("total"))
                elif kind == "search_completed":
                    job.progress.update(done=data.get("total_checked", checked))
        job.status = "done"
        if found or checked:
            job.summary = f"{found} found / {checked} checked"
        else:
            job.summary = summarize(last_event)


job_manager = JobManager()
