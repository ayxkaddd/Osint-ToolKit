"""Saved results: the index, triage, moving between cases, and what changed since the last run."""
import shutil
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from services.entities import extract_entities
from .constants import CHANGES_MAX_PATHS, CHANGES_MAX_VALUES, INDEX_VERSION, MANUAL_SERVICE, SERVICE_RENAMES, TRIAGE_STATUSES
from .storage import _STORE_LOCK, _new_result_id, _read_gz, _valid_id, _write_gz_atomic
from .summaries import _leaf_values, _path_label, find_target, summarize


class ResultsMixin:
    def save_investigation_result(
        self,
        investigation_id: UUID,
        service_name: str,
        method_name: str,
        parameters: dict[str, Any],
        result: Any,
        result_id: Optional[str] = None,
        parent_result_id: Optional[str] = None,
        partial: bool = False
    ) -> str:
        """Save a result and return its result id.

        With ``parent_result_id`` the result is attached as a child of that
        result (a follow-up lookup on the same target). Repeating the same
        follow-up (same method + parameters) replaces the earlier child instead
        of piling up duplicates. Returns the id of the top-level result.
        """
        if not self.get_investigation_info(investigation_id):
            raise ValueError(f"Investigation with ID {investigation_id} does not exist. Create it first.")

        service_name = SERVICE_RENAMES.get(service_name, service_name)
        now = datetime.now()

        with _STORE_LOCK:
            if parent_result_id and _valid_id(parent_result_id):
                parent = self.get_result(investigation_id, parent_result_id)
                if parent is not None:
                    child = {
                        "child_id": result_id or _new_result_id(),
                        "service_name": service_name,
                        "method_name": method_name,
                        "parameters": parameters,
                        "result": result,
                        "summary": summarize(result),
                        "partial": partial,
                        "timestamp": now.isoformat(),
                    }
                    # Several things added by hand under one result are all kept
                    children = [
                        c for c in parent.get("children", [])
                        if service_name == MANUAL_SERVICE
                        or not (c.get("method_name") == method_name and c.get("parameters") == parameters)
                    ]
                    children.append(child)
                    parent["children"] = children
                    self._write_result(investigation_id, parent)
                    return parent["result_id"]

            record = {
                "result_id": result_id or _new_result_id(),
                "investigation_id": str(investigation_id),
                "service_name": service_name,
                "method_name": method_name,
                "parameters": parameters,
                "result": result,
                "partial": partial,
                "children": [],
                "timestamp": now.isoformat(),
                "created_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            }
            self._write_result(investigation_id, record)
            self._touch(investigation_id)
            return record["result_id"]

    @staticmethod
    def _index_entry(record: dict[str, Any], size: int) -> dict[str, Any]:
        return {
            "result_id": record["result_id"],
            "service_name": record["service_name"],
            "method_name": record["method_name"],
            "parameters": record.get("parameters"),
            "target": find_target(record.get("parameters") or {}),
            "summary": summarize(record.get("result")),
            "partial": record.get("partial", False),
            "children": [
                {
                    "child_id": c.get("child_id"),
                    "service_name": c.get("service_name"),
                    "method_name": c.get("method_name"),
                    "target": find_target(c.get("parameters") or {}),
                    "summary": summarize(c.get("result")),
                    "timestamp": c.get("timestamp"),
                }
                for c in record.get("children", [])
            ],
            "timestamp": record["timestamp"],
            "size": size,
            "triage": record.get("triage"),
        }

    def _write_result(self, investigation_id, record: dict[str, Any]) -> None:
        """Write a full record and refresh its index entry and entities."""
        with _STORE_LOCK:
            size = _write_gz_atomic(self._result_file(investigation_id, record["result_id"]), record)
            index = self._load_index(investigation_id)
            index[record["result_id"]] = self._index_entry(record, size)
            self._save_index(investigation_id, index)
            entities = self._load_entities(investigation_id)
            self._apply_record_entities(entities, record)
            self._save_entities(investigation_id, entities)
            self._update_cards(investigation_id, [record])

    def _rebuild_indexes_if_needed(self) -> None:
        """Rebuild every index.json from the result files when the summary
        format changes (INDEX_VERSION), so listings never show stale summaries."""
        version_file = self.results_dir / ".index_version"
        if version_file.exists() and version_file.read_text().strip() == str(INDEX_VERSION):
            return
        investigations = self._load_investigations()
        for inv_id in investigations:
            results_dir = self._inv_dir(inv_id) / "results"
            index, records = {}, []
            old_entities = self._load_entities(inv_id)
            entities = {k: {**e, "sources": []} for k, e in old_entities.items() if e.get("status") or e.get("note")}
            for path in results_dir.glob("*.json.gz") if results_dir.exists() else []:
                record = _read_gz(path)
                if isinstance(record, dict) and record.get("result_id"):
                    index[record["result_id"]] = self._index_entry(record, path.stat().st_size)
                    self._apply_record_entities(entities, record)
                    records.append(record)
            for key, entity in entities.items():
                previous = old_entities.get(key)
                if previous:
                    entity.update({k: previous[k] for k in ("status", "note", "updated_at") if previous.get(k)})
            self._save_index(inv_id, index)
            self._save_entities(inv_id, entities)
            self._save_cards(inv_id, {})
            self._update_cards(inv_id, records)
            self._touch(inv_id, investigations)
        version_file.write_text(str(INDEX_VERSION))

    def get_investigation_results(self, investigation_id: UUID) -> list[dict[str, Any]]:
        """Result summaries for an investigation, newest first (no result payloads)."""
        results = list(self._load_index(investigation_id).values())
        results.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return results

    def get_result(self, investigation_id: UUID, result_id: str) -> Optional[dict[str, Any]]:
        """Full record for one result, including its children."""
        try:
            return _read_gz(self._result_file(investigation_id, result_id))
        except (ValueError, TypeError):
            return None

    def get_full_results(self, investigation_id: UUID) -> list[dict[str, Any]]:
        """Every full result record (used for export)."""
        records = []
        for summary in self.get_investigation_results(investigation_id):
            record = self.get_result(investigation_id, summary["result_id"])
            if record is not None:
                records.append(record)
        return records

    def delete_result(self, investigation_id: UUID, result_id: str) -> bool:
        with _STORE_LOCK:
            index = self._load_index(investigation_id)
            if result_id not in index:
                return False
            files = self._result_files(investigation_id, index[result_id])
            del index[result_id]
            self._save_index(investigation_id, index)
            self._result_file(investigation_id, result_id).unlink(missing_ok=True)
            self._delete_files(investigation_id, result_id, files)
            entities = self._load_entities(investigation_id)
            self._apply_record_entities(entities, {"result_id": result_id}, remove_only=True)
            self._save_entities(investigation_id, entities)
            self._update_cards(investigation_id, removed=[result_id])
            self._touch(investigation_id)
            return True

    def delete_results(self, investigation_id: UUID, result_ids: list[str]) -> list[str]:
        """Delete several results; returns the ids that were deleted."""
        with _STORE_LOCK:
            index = self._load_index(investigation_id)
            deleted = list(dict.fromkeys(r for r in result_ids if r in index))
            if deleted:
                self._remove_from_store(investigation_id, index, deleted)
            return deleted

    def _remove_from_store(self, investigation_id, index: dict[str, Any], result_ids: list[str]) -> None:
        """Take results out of an investigation, writing its index and entities once."""
        files = {result_id: self._result_files(investigation_id, index[result_id]) for result_id in result_ids}
        for result_id in result_ids:
            del index[result_id]
        self._save_index(investigation_id, index)
        for result_id in result_ids:
            self._result_file(investigation_id, result_id).unlink(missing_ok=True)
            self._delete_files(investigation_id, result_id, files[result_id])
        entities = self._load_entities(investigation_id)
        self._drop_entity_sources(entities, set(result_ids))
        self._save_entities(investigation_id, entities)
        self._update_cards(investigation_id, removed=result_ids)
        self._touch(investigation_id)

    def move_results(self, investigation_id: UUID, target_id: UUID, result_ids: list[str]) -> list[str]:
        """Move results (with their follow-ups) to another investigation; returns the
        ids that were moved. The copy is written first, so a crash can't lose a result.
        Snapshots stay with the notes that hold them."""
        moved, records = [], []
        with _STORE_LOCK:
            source_index = self._load_index(investigation_id)
            target_index = self._load_index(target_id)
            target_entities = self._load_entities(target_id)
            for result_id in dict.fromkeys(result_ids):
                record = self.get_result(investigation_id, result_id)
                if record is None or result_id in target_index:
                    continue
                record["investigation_id"] = str(target_id)
                for name in self._record_files(record):
                    source = self._files_dir(investigation_id) / name
                    if source.is_file():
                        self._files_dir(target_id).mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, self._files_dir(target_id) / name)
                size = _write_gz_atomic(self._result_file(target_id, result_id), record)
                target_index[result_id] = self._index_entry(record, size)
                self._apply_record_entities(target_entities, record)
                records.append(record)
                moved.append(result_id)
            if moved:
                # The copies are complete before anything is removed from the source
                self._save_index(target_id, target_index)
                self._save_entities(target_id, target_entities)
                self._update_cards(target_id, records)
                self._touch(target_id)
                self._remove_from_store(investigation_id, source_index, [r for r in moved if r in source_index])
        return moved

    def set_result_triage(self, investigation_id: UUID, result_id: str,
                          status: Optional[str], note: Optional[str]) -> Optional[dict[str, Any]]:
        """Mark a result confirmed / important / false positive, with a note."""
        if status not in TRIAGE_STATUSES:
            raise ValueError(f"status must be one of {sorted(s for s in TRIAGE_STATUSES if s)}")
        with _STORE_LOCK:
            record = self.get_result(investigation_id, result_id)
            if record is None:
                return None
            triage = {"status": status, "note": (note or "").strip() or None,
                      "updated_at": datetime.now().isoformat()}
            record["triage"] = triage if (triage["status"] or triage["note"]) else None
            self._write_result(investigation_id, record)
            return record["triage"]

    def set_results_triage(self, investigation_id: UUID, result_ids: list[str],
                           status: Optional[str]) -> dict[str, Any]:
        """Set the same assessment on several results, keeping each one's own note.
        Returns {result_id: triage} for the results that exist."""
        if status not in TRIAGE_STATUSES:
            raise ValueError(f"status must be one of {sorted(s for s in TRIAGE_STATUSES if s)}")
        updated = {}
        with _STORE_LOCK:
            index = self._load_index(investigation_id)
            for result_id in dict.fromkeys(result_ids):
                record = self.get_result(investigation_id, result_id)
                if record is None:
                    continue
                note = (record.get("triage") or {}).get("note")
                triage = {"status": status, "note": note, "updated_at": datetime.now().isoformat()}
                record["triage"] = triage if (status or note) else None
                size = _write_gz_atomic(self._result_file(investigation_id, result_id), record)
                index[result_id] = self._index_entry(record, size)
                updated[result_id] = record["triage"]
            if updated:
                self._save_index(investigation_id, index)
        return updated

    def previous_run(self, investigation_id: UUID, result_id: str) -> Optional[dict[str, Any]]:
        """The latest earlier result of the same lookup (module, method and query)."""
        index = self._load_index(investigation_id)
        current = index.get(result_id)
        if not current:
            return None
        earlier = [r for r in index.values()
                   if r["result_id"] != result_id and r.get("service_name") == current.get("service_name")
                   and r.get("method_name") == current.get("method_name")
                   and r.get("parameters") == current.get("parameters")
                   and r.get("timestamp", "") < current.get("timestamp", "")]
        return max(earlier, key=lambda r: r.get("timestamp", "")) if earlier else None

    def result_changes(self, investigation_id: UUID, result_id: str) -> Optional[dict[str, Any]]:
        """What a re-run found that the previous run of the same lookup didn't, and what
        is gone: identifiers, fields whose single value changed, and other values.
        None when there is no earlier run."""
        previous = self.previous_run(investigation_id, result_id)
        record = self.get_result(investigation_id, result_id)
        before = self.get_result(investigation_id, previous["result_id"]) if previous else None
        if not record or not before:
            return None
        service = record.get("service_name", "")
        new_values, old_values = _leaf_values(record.get("result")), _leaf_values(before.get("result"))
        added, removed = new_values - old_values, old_values - new_values

        by_path: dict[str, dict[str, list[str]]] = {}
        for path, value in added:
            by_path.setdefault(path, {"added": [], "removed": []})["added"].append(value)
        for path, value in removed:
            by_path.setdefault(path, {"added": [], "removed": []})["removed"].append(value)
        changed, lists = [], []
        for path in sorted(by_path):
            entry = {"path": path, "label": _path_label(path)}
            values = by_path[path]
            if len(values["added"]) == 1 and len(values["removed"]) == 1:
                changed.append({**entry, "before": values["removed"][0], "after": values["added"][0]})
            else:
                lists.append({**entry, "added": sorted(values["added"])[:CHANGES_MAX_VALUES],
                              "removed": sorted(values["removed"])[:CHANGES_MAX_VALUES],
                              "more": max(0, len(values["added"]) + len(values["removed"]) - 2 * CHANGES_MAX_VALUES)})

        def found(rec):
            return {entity.key: {"type": entity.type, "value": entity.value, "display": entity.display or entity.value}
                    for entity, _ in extract_entities(rec.get("result"), service)}
        now, then = found(record), found(before)
        return {
            "previous": {"result_id": before["result_id"], "timestamp": before.get("timestamp")},
            "identifiers_added": [now[k] for k in sorted(now.keys() - then.keys())][:200],
            "identifiers_removed": [then[k] for k in sorted(then.keys() - now.keys())][:200],
            "changed": changed[:CHANGES_MAX_PATHS],
            "lists": lists[:CHANGES_MAX_PATHS],
            "same": not (added or removed),
        }
