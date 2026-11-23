"""Identifiers found in results (entities.json), shared with other cases, mentioned in notes."""
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

from services.entities import Entity, entities_from_parameters, extract_entities, make_entity
from .constants import BUILTWITH_TAG, NOTE_ENTITY_REF, TRIAGE_STATUSES
from .storage import _ENTITY_CACHE, _SHARED_CACHE, _STORE_LOCK, _read_json, _write_json_atomic


class IdentifiersMixin:
    def _entities_file(self, investigation_id) -> Path:
        return self._inv_dir(investigation_id) / "entities.json"

    def _load_entities(self, investigation_id) -> dict[str, Any]:
        return _read_json(self._entities_file(investigation_id), {})

    def _save_entities(self, investigation_id, entities: dict[str, Any]) -> None:
        _write_json_atomic(self._entities_file(investigation_id), entities, compact=True)

    @staticmethod
    def _drop_entity_sources(entities: dict[str, Any], result_ids: set) -> None:
        for key in list(entities):
            entity = entities[key]
            entity["sources"] = [src for src in entity.get("sources", []) if src.get("result_id") not in result_ids]
            if not entity["sources"] and not entity.get("status") and not entity.get("note"):
                del entities[key]

    @staticmethod
    def _apply_record_entities(entities: dict[str, Any], record: dict[str, Any], remove_only: bool = False) -> None:
        """Replace the sources one result contributes (idempotent: results are
        rewritten when follow-ups are attached)."""
        result_id = record.get("result_id")
        IdentifiersMixin._drop_entity_sources(entities, {result_id})
        if remove_only:
            return

        def add(entity: Entity, role: str, service: str, method: str, timestamp: str,
                child_id: Optional[str] = None, path: Optional[str] = None):
            item = entities.setdefault(entity.key, {
                "key": entity.key, "type": entity.type, "value": entity.value,
                "display": entity.display or entity.value, "sources": [],
                "status": None, "note": None,
            })
            item["sources"].append({k: v for k, v in {
                "result_id": result_id, "child_id": child_id, "service": service, "method": method,
                "role": role, "path": path, "timestamp": timestamp,
            }.items() if v is not None})
            stamps = [src["timestamp"] for src in item["sources"] if src.get("timestamp")]
            item["first_seen"], item["last_seen"] = (min(stamps), max(stamps)) if stamps else (None, None)

        parts = [(None, record)] + [(c.get("child_id"), c) for c in record.get("children", [])]
        for child_id, part in parts:
            service = part.get("service_name", "")
            method = part.get("method_name", "")
            timestamp = part.get("timestamp") or record.get("timestamp")
            searched = set()
            for entity in entities_from_parameters(part.get("parameters") or {}, service):
                searched.add(entity.key)
                add(entity, "searched", service, method, timestamp, child_id)
            for entity, path in extract_entities(part.get("result"), service):
                if entity.key not in searched:
                    add(entity, "found", service, method, timestamp, child_id, path)

    @staticmethod
    def _decorate_entity(entity: dict[str, Any]) -> dict[str, Any]:
        """Counts shown in the identifier list (computed, not stored)."""
        sources = entity.get("sources", [])
        entity["found_count"] = len({src.get("result_id") for src in sources if src.get("role") == "found"})
        entity["searched"] = sorted({src.get("service") for src in sources if src.get("role") == "searched"})
        entity["services"] = sorted({src.get("service") for src in sources})
        return entity

    @staticmethod
    def _entity_order(entity: dict[str, Any]):
        rank = {"confirmed": 0, "important": 1, None: 2, "false_positive": 3}
        return (rank.get(entity.get("status"), 2), -entity["found_count"], entity["type"], entity["value"])

    def _entities_snapshot(self, investigation_id) -> dict[str, Any]:
        """Read-only view of entities.json, parsed once per version of the file.
        Large investigations have tens of thousands of identifiers (several MB)."""
        path = self._entities_file(investigation_id)
        try:
            stat = path.stat()
        except FileNotFoundError:
            return {"raw": {}, "sorted": [], "version": None}
        version = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
        cached = _ENTITY_CACHE.get(str(path))
        if cached is None or cached[0] != version:
            cached = _ENTITY_CACHE[str(path)] = (version, {"raw": self._load_entities(investigation_id),
                                                           "sorted": None, "version": version})
        return cached[1]

    def get_entities(self, investigation_id: UUID) -> list[dict[str, Any]]:
        """All identifiers in the investigation with where they were found.
        Callers get copies they may modify."""
        snapshot = self._entities_snapshot(investigation_id)
        if snapshot["sorted"] is None:
            entities = [self._decorate_entity(dict(e)) for e in snapshot["raw"].values()]
            entities.sort(key=self._entity_order)
            snapshot["sorted"] = entities
        return [dict(e) for e in snapshot["sorted"]]

    def set_entity_triage(self, investigation_id: UUID, key: str,
                          status: Optional[str], note: Optional[str]) -> Optional[dict[str, Any]]:
        if status not in TRIAGE_STATUSES:
            raise ValueError(f"status must be one of {sorted(s for s in TRIAGE_STATUSES if s)}")
        with _STORE_LOCK:
            entities = self._load_entities(investigation_id)
            entity = entities.get(key)
            if entity is None:
                return None
            entity["status"] = status
            entity["note"] = (note or "").strip() or None
            entity["updated_at"] = datetime.now().isoformat()
            self._save_entities(investigation_id, entities)
            return entity

    def entities_for_result(self, investigation_id: UUID, result_id: str) -> list[dict[str, Any]]:
        """Identifiers one result contributes, without building the whole list."""
        entities = [self._decorate_entity(dict(e)) for e in self._entities_snapshot(investigation_id)["raw"].values()
                    if any(src.get("result_id") == result_id for src in e.get("sources", []))]
        entities.sort(key=self._entity_order)
        return entities

    def previous_lookups(self, investigation_id: UUID, entity_key: str) -> list[dict[str, Any]]:
        """Earlier lookups run on this identifier (to avoid paying twice)."""
        entity = self._load_entities(investigation_id).get(entity_key)
        if not entity:
            return []
        return [src for src in entity.get("sources", []) if src.get("role") == "searched"]

    def _shared_index(self) -> dict[str, list[dict[str, Any]]]:
        """{entity key: [where it is]} for identifiers in more than one investigation.
        Identifiers marked false positive don't count."""
        investigations = self._load_investigations()
        snapshots = {inv_id: self._entities_snapshot(inv_id) for inv_id in investigations}
        versions = tuple(sorted((inv_id, str(snap["version"])) for inv_id, snap in snapshots.items()))
        if _SHARED_CACHE["versions"] == versions:
            return _SHARED_CACHE["index"]
        counts: dict[str, int] = {}
        for snap in snapshots.values():
            for key, entity in snap["raw"].items():
                if entity.get("status") != "false_positive":
                    counts[key] = counts.get(key, 0) + 1
        index: dict[str, list[dict[str, Any]]] = {}
        for inv_id, snap in snapshots.items():
            for key, entity in snap["raw"].items():
                if counts.get(key, 0) > 1 and entity.get("status") != "false_positive":
                    sources = entity.get("sources", [])
                    index.setdefault(key, []).append({
                        "investigation_id": inv_id,
                        "status": entity.get("status"),
                        "searched": any(src.get("role") == "searched" for src in sources),
                        "results": len({src.get("result_id") for src in sources if src.get("result_id")}),
                    })
        _SHARED_CACHE.update(versions=versions, index=index)
        return index

    def investigations_with(self, keys: list[str], exclude: Optional[UUID] = None) -> dict[str, list[dict[str, Any]]]:
        """For each entity key, the other investigations it appears in (only keys that do)."""
        index = self._shared_index()
        investigations = self._load_investigations()
        skip = str(exclude) if exclude else None
        found = {}
        for key in dict.fromkeys(keys):
            places = [{**place, "name": investigations.get(place["investigation_id"], {}).get("name") or "Untitled",
                       "investigation_status": investigations.get(place["investigation_id"], {}).get("status")}
                      for place in index.get(key, []) if place["investigation_id"] != skip]
            if places:
                places.sort(key=lambda p: investigations.get(p["investigation_id"], {}).get("updated_at", ""), reverse=True)
                found[key] = places
        return found

    def shared_entity_keys(self, investigation_id: UUID) -> set[str]:
        """Keys of this investigation's identifiers that other investigations have too."""
        here = str(investigation_id)
        return {key for key, places in self._shared_index().items()
                if any(p["investigation_id"] == here for p in places)
                and any(p["investigation_id"] != here for p in places)}

    def notes_mentioning(self, investigation_id: UUID, entities: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        """{entity key: [notes]} for the notes that reference an identifier ([[email:a@b.c]])
        or write it in their text. Only keys with at least one note."""
        notes = [n for n in self.get_investigation_notes(investigation_id) if n.get("content")]
        if not notes or not entities:
            return {}
        referenced: list[tuple[dict[str, Any], set]] = []
        for note in notes:
            keys = set()
            for entity_type, value in NOTE_ENTITY_REF.findall(note["content"]):
                entity = make_entity(entity_type, value.strip(), typed=True)
                if entity:
                    keys.add(entity.key)
            referenced.append((note, keys))
        found: dict[str, list[dict[str, Any]]] = {}
        for entity in entities:
            needles = {str(v).lower() for v in (entity.get("value"), entity.get("display")) if v and len(str(v)) >= 4}
            for note, keys in referenced:
                text = note["content"].lower()
                if entity["key"] in keys or any(needle in text for needle in needles):
                    found.setdefault(entity["key"], []).append(
                        {"note_id": note["note_id"], "title": note.get("title") or "Untitled note"})
        return found

    def tracking_ids(self, investigation_id: UUID) -> list[dict[str, Any]]:
        """Analytics / ads IDs found by DNS recon and the NS fingerprint, with the domains."""
        from services.fingerprint_service import ACCOUNT_TRACKERS, TRACKERS
        found: dict[tuple[str, str], set] = {}
        for summary in self.get_investigation_results(investigation_id):
            methods = {summary.get("method_name")} | {c.get("method_name") for c in summary.get("children", [])}
            if summary.get("service_name") not in ("dns_recon", "ns") or not methods & {"lookup_dns_recon", "fingerprint"}:
                continue
            record = self.get_result(investigation_id, summary["result_id"]) or {}
            for part in [record] + list(record.get("children", [])):
                result = part.get("result") if isinstance(part.get("result"), dict) else {}
                for item in (result.get("intel") or {}).get("tracking_ids") or []:
                    found.setdefault((item.get("kind"), item.get("id")), set()).update(item.get("names") or [])
                if part.get("method_name") == "fingerprint":
                    for domain, fingerprint in (result.get("domains") or {}).items():
                        for kind, ids in ((fingerprint or {}).get("trackers") or {}).items():
                            if kind in ACCOUNT_TRACKERS:
                                for tracker_id in ids:
                                    found.setdefault((kind, tracker_id), set()).add(domain)
        return sorted(({"kind": kind, "label": TRACKERS.get(kind, (kind,))[0], "id": tracker_id,
                        "domains": sorted(domains), "builtwith": BUILTWITH_TAG.fullmatch(tracker_id or "") is not None}
                       for (kind, tracker_id), domains in found.items()),
                      key=lambda t: (-len(t["domains"]), t["label"], t["id"]))
