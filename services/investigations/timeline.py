"""Dated events found in results (the investigation's timeline)."""
from pathlib import Path
from typing import Any
from uuid import UUID

from services.events import extract_events
from .constants import EVENTS_VERSION, MANUAL_SERVICE
from .storage import _STORE_LOCK, _read_json, _write_json_atomic


class TimelineMixin:
    def _events_file(self, investigation_id) -> Path:
        return self._inv_dir(investigation_id) / "events.json"

    @staticmethod
    def _record_events(record: dict[str, Any]) -> list[dict[str, Any]]:
        events = []
        parts = [(None, record)] + [(c.get("child_id"), c) for c in record.get("children", [])]
        for child_id, part in parts:
            service = part.get("service_name", "")
            result = part.get("result")
            found = []
            if service == MANUAL_SERVICE and isinstance(result, dict):
                if result.get("date"):
                    found.append({"date": result["date"], "precision": result.get("date_precision") or "day",
                                  "label": result.get("title") or "Added manually", "section": "",
                                  "context": None, "path": "date", "manual": True})
                result = {k: v for k, v in result.items() if k != "date"}
            found += extract_events(result, service, part.get("timestamp") or record.get("timestamp"))
            for event in found:
                event.update({"result_id": record["result_id"], "service": service,
                              "method": part.get("method_name", "")})
                if child_id:
                    event["child_id"] = child_id
            events.extend(found)
        return events

    def get_events(self, investigation_id: UUID) -> list[dict[str, Any]]:
        """Dated events found in the investigation's results, newest first.
        Each result's events are cached in events.json until its file changes."""
        index = self._load_index(investigation_id)
        cache_file = self._events_file(investigation_id)
        cache = _read_json(cache_file, {})
        cached = cache.get("results", {}) if cache.get("version") == EVENTS_VERSION else {}
        fresh: dict[str, Any] = {}
        changed = False
        for result_id in index:
            try:
                stat = self._result_file(investigation_id, result_id).stat()
            except (FileNotFoundError, ValueError):
                continue
            stamp = f"{stat.st_mtime_ns}:{stat.st_size}"
            entry = cached.get(result_id)
            if not entry or entry.get("stamp") != stamp:
                record = self.get_result(investigation_id, result_id)
                entry = {"stamp": stamp, "events": self._record_events(record) if record else []}
                changed = True
            fresh[result_id] = entry
        if changed or fresh.keys() != cached.keys():
            with _STORE_LOCK:
                if self._inv_dir(investigation_id).is_dir():
                    _write_json_atomic(cache_file, {"version": EVENTS_VERSION, "results": fresh}, compact=True)
        events = []
        for result_id, entry in fresh.items():
            target = index[result_id].get("target")
            events.extend({**event, "target": target} for event in entry["events"])
        events.sort(key=lambda e: (e.get("end") or e["date"], e["date"]), reverse=True)
        return events
