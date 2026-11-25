"""Following background lookups until they finish.

What a streaming lookup finds is printed as it arrives: the server keeps the stream's
result so far (``running: true`` on the result, what the web page shows while it runs),
and each poll prints the items not printed yet. Other lookups print their whole answer
when they finish.
"""
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from . import render
from .client import ApiError, Client

POLL_SECONDS = 1.0
FINISHED = {"done", "failed", "cancelled"}


def item_key(item: Any) -> str:
    """The same find on every poll (the server re-sorts the lists, and fills in more of an
    item later, like a profile's details), so not its place or its whole content."""
    if isinstance(item, dict):
        for key in ("url", "link", "profile_url", "id"):
            if item.get(key) not in (None, ""):
                return f"{key}:{item[key]}"
    return json.dumps(item, sort_keys=True, default=str)


def new_items(result: Any, seen: set) -> list[tuple[str, Optional[str], Any]]:
    """(section, key, item) for each find of a result not in ``seen``, which keeps them.
    Finds are the items of its lists and the entries of its maps of records
    ({"domains": {"a.test": {...}}}); the rest (counts, flags) is not a find."""
    out = []
    if not isinstance(result, dict):
        return out
    for section, value in result.items():
        if isinstance(value, list):
            entries = [(None, item) for item in value]
        elif isinstance(value, dict) and value and all(isinstance(v, dict) for v in value.values()):
            entries = list(value.items())
        else:
            continue
        for key, item in entries:
            mark = (section, key if key is not None else item_key(item))
            if mark not in seen:
                seen.add(mark)
                out.append((section, key, item))
    return out


@dataclass
class Followed:
    job: dict
    investigation_id: str
    streamed: bool = False
    seen: set = field(default_factory=set)
    record: Optional[dict] = None

    @property
    def name(self) -> str:
        return self.job.get("module_name") or self.job.get("module_id") or self.job.get("id", "")


def follow(api: Client, investigation_id: Optional[str], jobs: list[dict], quiet: bool = False,
           sleep: Callable[[float], None] = time.sleep) -> list[Followed]:
    """Polls the jobs until each one has finished, printing as they go (nothing when
    ``quiet``). Returns them with their saved results."""
    pending = {job["id"]: Followed(job, job.get("investigation_id") or investigation_id or "") for job in jobs}
    finished: list[Followed] = []
    status = None if quiet else render.out.status("Waiting for the lookups...")
    if status:
        status.start()
    try:
        while pending:
            listed = {j.get("id"): j for j in api.jobs(investigation_id, limit=300).get("jobs", [])}
            for job_id, followed in list(pending.items()):
                followed.job = listed.get(job_id, followed.job)
                state = followed.job.get("status")
                if state == "running" and followed.job.get("result_id"):
                    _read_stream(api, followed, quiet)
                if state in FINISHED:
                    _finish(api, followed, quiet)
                    finished.append(pending.pop(job_id))
            if status and pending:
                status.update(render.jobs_waiting([f.job for f in pending.values()]))
            if pending:
                sleep(POLL_SECONDS)
    finally:
        if status:
            status.stop()
    return finished


def _record(api: Client, followed: Followed) -> Optional[dict]:
    try:
        return api.result(followed.investigation_id, followed.job["result_id"])
    except ApiError as e:
        if e.status == 404:   # the stream hasn't started yet, or nothing was saved
            return None
        raise


def _read_stream(api: Client, followed: Followed, quiet: bool) -> None:
    record = _record(api, followed)
    if not record or not record.get("running"):
        return
    followed.streamed = True
    for section, key, item in new_items(record.get("result"), followed.seen):
        if not quiet:
            render.out.print(render.stream_item(followed.name, section, key, item))


def _finish(api: Client, followed: Followed, quiet: bool) -> None:
    job = followed.job
    if job.get("status") == "done" and job.get("result_id"):
        followed.record = _record(api, followed)
    if quiet:
        return
    result = (followed.record or {}).get("result")
    if followed.streamed:
        for section, key, item in new_items(result, followed.seen):
            render.out.print(render.stream_item(followed.name, section, key, item))
    elif followed.record:
        render.out.print(render.answer(followed.name, job.get("value"), result))
    render.out.print(render.job_finished(job))
