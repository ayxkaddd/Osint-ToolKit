# services/investigation_service.py
"""Investigation storage.

Layout (all under ``investigation_results/``)::

    investigations.json             investigation metadata (no binary data)
    current_investigation.json      the active investigation id
    <investigation_id>/
        index.json                  {result_id: summary} - listing never opens result files
        results/<result_id>.json.gz full result records (gzip-compressed JSON)
        notes/<note_id>.json        analyst notes
        picture.webp                optional case picture (resized)

A result can carry ``children``: follow-up lookups attached to it (e.g. the WHOIS
analysis of the domains found by an NS lookup, or the stats/groups/messages
fetched for a Funstat user) so related data stays in one group.
"""
import base64
import gzip
import io
import json
import logging
import os
import re
import shutil
import tarfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from services.entities import Entity, entities_from_parameters, extract_entities
from utils.legacy_repr import parse_model_repr
from utils.stream_reducers import legacy_username_result

logger = logging.getLogger(__name__)

# Shared across every InvestigationService instance (routes, decorator and
# templates each construct their own) so concurrent lookups writing to the same
# JSON files cannot interleave and lose data.
_STORE_LOCK = threading.RLock()
_MIGRATED_DIRS: set = set()

# Bump when the index entry format / summary logic changes
INDEX_VERSION = 6

TRIAGE_STATUSES = {None, "confirmed", "important", "false_positive"}

PICTURE_MAX_SIDE = 512
PICTURE_MAX_UPLOAD = 10 * 1024 * 1024

# Old service names that were saved under a different key
SERVICE_RENAMES = {"username_search": "username"}
# Module pages ask for history by these names
SERVICE_ALIASES = {
    "username": {"username", "username_search"},
    "ns": {"ns", "ns_lookup"},
    "ns_lookup": {"ns", "ns_lookup"},
}

# Parameter names that identify what a lookup was about, in priority order
TARGET_KEYS = (
    "username", "domain", "email", "query", "phones", "phone", "ns1", "user_id",
    "gaia_id", "bssid", "drive_url", "url", "link", "links", "term", "input",
    "target", "group_id", "id", "domains", "filename", "image",
)


def _read_json(path: Path, default):
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write_json_atomic(path: Path, data, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, 'w') as f:
        if compact:
            json.dump(data, f, separators=(",", ":"), default=str)
        else:
            json.dump(data, f, indent=2, default=str)
    os.replace(tmp, path)


def _write_gz_atomic(path: Path, data) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(data, separators=(",", ":"), default=str, ensure_ascii=False).encode("utf-8")
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, 'wb', compresslevel=6) as f:
        f.write(raw)
    os.replace(tmp, path)
    return path.stat().st_size


def _read_gz(path: Path):
    try:
        with gzip.open(path, 'rb') as f:
            return json.loads(f.read().decode("utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None


def _new_result_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def _valid_id(value: str) -> bool:
    """Result/note ids become file names - reject anything path-like."""
    return bool(value) and all(c.isalnum() or c in "_-" for c in str(value))


def process_picture(data: bytes) -> bytes:
    """Validate an uploaded image and return a resized WebP version."""
    from PIL import Image, UnidentifiedImageError

    if len(data) > PICTURE_MAX_UPLOAD:
        raise ValueError("Picture is too large (max 10 MB)")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError) as e:
        raise ValueError("Picture is not a valid image") from e

    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
    img.thumbnail((PICTURE_MAX_SIDE, PICTURE_MAX_SIDE))
    out = io.BytesIO()
    img.save(out, format="WEBP", quality=82, method=4)
    return out.getvalue()


def find_target(parameters: Dict[str, Any]) -> Optional[str]:
    """Pick the human-meaningful target (username, domain, ...) out of call parameters."""
    if not isinstance(parameters, dict):
        return None
    kwargs = parameters.get("kwargs", parameters)
    candidates = dict(kwargs) if isinstance(kwargs, dict) else {}
    # Pydantic request bodies are stored as nested dicts - look one level down
    for value in list(candidates.values()):
        if isinstance(value, str):
            upload = re.match(r"UploadFile\(filename='([^']*)'", value)
            value = {"filename": upload.group(1)} if upload else (parse_model_repr(value) or value)
        if isinstance(value, dict):
            for k, v in value.items():
                candidates.setdefault(k, v)
    for key in TARGET_KEYS:
        value = candidates.get(key)
        if value not in (None, "", [], {}):
            if isinstance(value, list):
                value = ", ".join(str(v) for v in value[:5]) + ("…" if len(value) > 5 else "")
            text = str(value)
            if key == "ns1" and candidates.get("ns2"):
                text = f"{text} + {candidates['ns2']}"
            return text[:200]
    args = parameters.get("args") if isinstance(parameters, dict) else None
    if args:
        return str(args[0])[:200]
    return None


def summarize(result: Any) -> str:
    """One-line description of a result for listings."""
    if result is None:
        return "No data"
    if isinstance(result, list):
        return f"{len(result)} item{'s' if len(result) != 1 else ''}"
    if isinstance(result, dict):
        if result.get("error"):
            return f"Error: {str(result['error'])[:120]}"
        stats = result.get("stats")
        if isinstance(stats, dict) and "found" in stats:
            checked = stats.get("checked") if stats.get("checked") is not None else stats.get("total", "?")
            return f"{stats['found']} found / {checked} checked"
        for key in ("results", "domains", "matches", "entries", "subdomains", "data", "messages", "items"):
            value = result.get(key)
            if isinstance(value, (list, dict)):
                return f"{len(value)} {key}"
        for key in ("total_results", "total_matches", "count", "total"):
            if isinstance(result.get(key), int):
                return f"{result[key]} {key.replace('total_', '').replace('_', ' ')}"
        return f"{len(result)} fields"
    return str(result)[:160]


class InvestigationService:
    def __init__(self, results_dir: str = "investigation_results"):
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(exist_ok=True)
        self.investigations_file = self.results_dir / "investigations.json"
        self.current_file = self.results_dir / "current_investigation.json"
        if not self.investigations_file.exists():
            _write_json_atomic(self.investigations_file, {})
        self._migrate_legacy_layout()

    # ==================== PATH HELPERS ====================

    def _inv_dir(self, investigation_id) -> Path:
        return self.results_dir / str(UUID(str(investigation_id)))

    def _index_file(self, investigation_id) -> Path:
        return self._inv_dir(investigation_id) / "index.json"

    def _result_file(self, investigation_id, result_id: str) -> Path:
        if not _valid_id(result_id):
            raise ValueError("Invalid result id")
        return self._inv_dir(investigation_id) / "results" / f"{result_id}.json.gz"

    def _notes_dir(self, investigation_id) -> Path:
        return self._inv_dir(investigation_id) / "notes"

    def _picture_file(self, investigation_id) -> Path:
        return self._inv_dir(investigation_id) / "picture.webp"

    def _load_investigations(self) -> Dict[str, Any]:
        return _read_json(self.investigations_file, {})

    def _save_investigations(self, investigations: Dict[str, Any]) -> None:
        _write_json_atomic(self.investigations_file, investigations)

    def _load_index(self, investigation_id) -> Dict[str, Any]:
        return _read_json(self._index_file(investigation_id), {})

    def _save_index(self, investigation_id, index: Dict[str, Any]) -> None:
        _write_json_atomic(self._index_file(investigation_id), index, compact=True)

    def _public_info(self, info: Dict[str, Any]) -> Dict[str, Any]:
        info = dict(info)
        info.pop("picture", None)
        if info.get("has_picture"):
            version = info.get("picture_version") or info.get("updated_at", "")
            info["picture_url"] = f"/api/investigations/{info['investigation_id']}/picture?v={version}"
        else:
            info["picture_url"] = None
        return info

    def _touch(self, investigation_id, investigations: Optional[Dict[str, Any]] = None) -> None:
        """Refresh counts + updated_at for an investigation."""
        with _STORE_LOCK:
            investigations = investigations if investigations is not None else self._load_investigations()
            info = investigations.get(str(investigation_id))
            if not info:
                return
            info["results_count"] = len(self._load_index(investigation_id))
            notes_dir = self._notes_dir(investigation_id)
            info["notes_count"] = len(list(notes_dir.glob("*.json"))) if notes_dir.exists() else 0
            info["updated_at"] = datetime.now().isoformat()
            self._save_investigations(investigations)

    # ==================== INVESTIGATIONS ====================

    def create_investigation(
        self,
        name: str,
        description: str,
        picture: Optional[bytes] = None,
        investigation_id: Optional[UUID] = None
    ) -> UUID:
        """Create a new investigation. ``picture`` is raw image bytes (any format)."""
        if investigation_id is None:
            investigation_id = uuid4()
        picture_data = process_picture(picture) if picture else None

        with _STORE_LOCK:
            investigations = self._load_investigations()
            if str(investigation_id) in investigations:
                raise ValueError(f"Investigation with ID {investigation_id} already exists")

            now = datetime.now().isoformat()
            inv_dir = self._inv_dir(investigation_id)
            (inv_dir / "results").mkdir(parents=True, exist_ok=True)
            if picture_data:
                self._picture_file(investigation_id).write_bytes(picture_data)

            investigations[str(investigation_id)] = {
                "investigation_id": str(investigation_id),
                "name": name,
                "description": description,
                "has_picture": bool(picture_data),
                "picture_version": now if picture_data else None,
                "created_at": now,
                "updated_at": now,
                "results_count": 0,
                "notes_count": 0,
                "status": "active"
            }
            self._save_investigations(investigations)

        return investigation_id

    def get_investigation_info(self, investigation_id) -> Optional[Dict[str, Any]]:
        """Get investigation metadata"""
        try:
            info = self._load_investigations().get(str(UUID(str(investigation_id))))
        except (ValueError, TypeError):
            return None
        return self._public_info(info) if info else None

    def update_investigation(
        self,
        investigation_id: UUID,
        name: Optional[str] = None,
        description: Optional[str] = None,
        picture: Optional[bytes] = None,
        status: Optional[str] = None,
        remove_picture: bool = False
    ) -> bool:
        """Update investigation metadata"""
        picture_data = process_picture(picture) if picture else None

        with _STORE_LOCK:
            investigations = self._load_investigations()
            investigation = investigations.get(str(investigation_id))
            if not investigation:
                return False

            if name is not None:
                investigation["name"] = name
            if description is not None:
                investigation["description"] = description
            if status is not None:
                investigation["status"] = status

            now = datetime.now().isoformat()
            if picture_data:
                self._picture_file(investigation_id).parent.mkdir(parents=True, exist_ok=True)
                self._picture_file(investigation_id).write_bytes(picture_data)
                investigation["has_picture"] = True
                investigation["picture_version"] = now
            elif remove_picture:
                self._picture_file(investigation_id).unlink(missing_ok=True)
                investigation["has_picture"] = False
                investigation["picture_version"] = None

            investigation["updated_at"] = now
            self._save_investigations(investigations)
            return True

    def get_picture_path(self, investigation_id) -> Optional[Path]:
        try:
            path = self._picture_file(investigation_id)
        except (ValueError, TypeError):
            return None
        return path if path.exists() else None

    def list_all_investigations(self) -> List[Dict[str, Any]]:
        """List all created investigations, newest first"""
        investigations = [self._public_info(i) for i in self._load_investigations().values()]
        investigations.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return investigations

    def delete_investigation(self, investigation_id: UUID) -> bool:
        """Delete investigation and all its results and notes"""
        with _STORE_LOCK:
            investigations = self._load_investigations()
            existed = investigations.pop(str(investigation_id), None) is not None
            if existed:
                self._save_investigations(investigations)

            inv_dir = self._inv_dir(investigation_id)
            if inv_dir.exists():
                shutil.rmtree(inv_dir)
                existed = True

            if self.get_current_investigation() == UUID(str(investigation_id)):
                self.clear_investigation()

            return existed

    # ==================== RESULTS ====================

    def save_investigation_result(
        self,
        investigation_id: UUID,
        service_name: str,
        method_name: str,
        parameters: Dict[str, Any],
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
                    children = [
                        c for c in parent.get("children", [])
                        if not (c.get("method_name") == method_name and c.get("parameters") == parameters)
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
    def _index_entry(record: Dict[str, Any], size: int) -> Dict[str, Any]:
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

    def _write_result(self, investigation_id, record: Dict[str, Any]) -> None:
        """Write a full record and refresh its index entry and entities."""
        with _STORE_LOCK:
            size = _write_gz_atomic(self._result_file(investigation_id, record["result_id"]), record)
            index = self._load_index(investigation_id)
            index[record["result_id"]] = self._index_entry(record, size)
            self._save_index(investigation_id, index)
            entities = self._load_entities(investigation_id)
            self._apply_record_entities(entities, record)
            self._save_entities(investigation_id, entities)

    def _rebuild_indexes_if_needed(self) -> None:
        """Rebuild every index.json from the result files when the summary
        format changes (INDEX_VERSION), so listings never show stale summaries."""
        version_file = self.results_dir / ".index_version"
        if version_file.exists() and version_file.read_text().strip() == str(INDEX_VERSION):
            return
        investigations = self._load_investigations()
        for inv_id in investigations:
            results_dir = self._inv_dir(inv_id) / "results"
            index = {}
            old_entities = self._load_entities(inv_id)
            entities = {k: {**e, "sources": []} for k, e in old_entities.items() if e.get("status") or e.get("note")}
            for path in results_dir.glob("*.json.gz") if results_dir.exists() else []:
                record = _read_gz(path)
                if isinstance(record, dict) and record.get("result_id"):
                    index[record["result_id"]] = self._index_entry(record, path.stat().st_size)
                    self._apply_record_entities(entities, record)
            for key, entity in entities.items():
                previous = old_entities.get(key)
                if previous:
                    entity.update({k: previous[k] for k in ("status", "note", "updated_at") if previous.get(k)})
            self._save_index(inv_id, index)
            self._save_entities(inv_id, entities)
            self._touch(inv_id, investigations)
        version_file.write_text(str(INDEX_VERSION))

    def get_investigation_results(self, investigation_id: UUID) -> List[Dict[str, Any]]:
        """Result summaries for an investigation, newest first (no result payloads)."""
        results = list(self._load_index(investigation_id).values())
        results.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return results

    def get_result(self, investigation_id: UUID, result_id: str) -> Optional[Dict[str, Any]]:
        """Full record for one result, including its children."""
        try:
            return _read_gz(self._result_file(investigation_id, result_id))
        except (ValueError, TypeError):
            return None

    def get_full_results(self, investigation_id: UUID) -> List[Dict[str, Any]]:
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
            del index[result_id]
            self._save_index(investigation_id, index)
            self._result_file(investigation_id, result_id).unlink(missing_ok=True)
            entities = self._load_entities(investigation_id)
            self._apply_record_entities(entities, {"result_id": result_id}, remove_only=True)
            self._save_entities(investigation_id, entities)
            self._touch(investigation_id)
            return True

    # ==================== TRIAGE ====================

    def set_result_triage(self, investigation_id: UUID, result_id: str,
                          status: Optional[str], note: Optional[str]) -> Optional[Dict[str, Any]]:
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

    # ==================== ENTITIES ====================

    def _entities_file(self, investigation_id) -> Path:
        return self._inv_dir(investigation_id) / "entities.json"

    def _load_entities(self, investigation_id) -> Dict[str, Any]:
        return _read_json(self._entities_file(investigation_id), {})

    def _save_entities(self, investigation_id, entities: Dict[str, Any]) -> None:
        _write_json_atomic(self._entities_file(investigation_id), entities, compact=True)

    @staticmethod
    def _apply_record_entities(entities: Dict[str, Any], record: Dict[str, Any], remove_only: bool = False) -> None:
        """Replace the sources one result contributes (idempotent: results are
        rewritten when follow-ups are attached)."""
        result_id = record.get("result_id")
        for key in list(entities):
            entity = entities[key]
            entity["sources"] = [src for src in entity.get("sources", []) if src.get("result_id") != result_id]
            if not entity["sources"] and not entity.get("status") and not entity.get("note"):
                del entities[key]
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

    def get_entities(self, investigation_id: UUID) -> List[Dict[str, Any]]:
        """All identifiers in the investigation with where they were found."""
        entities = list(self._load_entities(investigation_id).values())
        for entity in entities:
            found_in = {src.get("result_id") for src in entity.get("sources", []) if src.get("role") == "found"}
            entity["found_count"] = len(found_in)
            entity["searched"] = sorted({src.get("service") for src in entity.get("sources", [])
                                         if src.get("role") == "searched"})
            entity["services"] = sorted({src.get("service") for src in entity.get("sources", [])})
        rank = {"confirmed": 0, "important": 1, None: 2, "false_positive": 3}
        entities.sort(key=lambda e: (rank.get(e.get("status"), 2), -e["found_count"], e["type"], e["value"]))
        return entities

    def set_entity_triage(self, investigation_id: UUID, key: str,
                          status: Optional[str], note: Optional[str]) -> Optional[Dict[str, Any]]:
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

    def entities_for_result(self, investigation_id: UUID, result_id: str) -> List[Dict[str, Any]]:
        return [e for e in self.get_entities(investigation_id)
                if any(src.get("result_id") == result_id for src in e.get("sources", []))]

    def previous_lookups(self, investigation_id: UUID, entity_key: str) -> List[Dict[str, Any]]:
        """Earlier lookups run on this identifier (to avoid paying twice)."""
        entity = self._load_entities(investigation_id).get(entity_key)
        if not entity:
            return []
        return [src for src in entity.get("sources", []) if src.get("role") == "searched"]

    def get_investigation_result(self, investigation_id: UUID) -> Optional[Dict[str, Any]]:
        """Investigation info + result summaries"""
        investigation_info = self.get_investigation_info(investigation_id)
        if not investigation_info:
            return None
        return {
            "investigation": investigation_info,
            "results": self.get_investigation_results(investigation_id)
        }

    def list_investigations(
        self,
        service_name: Optional[str] = None,
        method_name: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Result summaries of the *current* investigation, optionally filtered by module."""
        investigation_id = self.get_current_investigation()
        if not investigation_id:
            return []
        names = SERVICE_ALIASES.get(service_name, {service_name}) if service_name else None

        results = []
        for summary in self.get_investigation_results(investigation_id):
            if names and summary.get("service_name") not in names:
                continue
            if method_name and summary.get("method_name") != method_name:
                continue
            results.append({**summary, "investigation_id": str(investigation_id)})
        return results[:limit] if limit else results

    # ==================== CURRENT INVESTIGATION ====================

    def set_current_investigation(self, investigation_id: UUID) -> bool:
        """Set the current active investigation by ID. Returns False if it doesn't exist."""
        if self.get_investigation_info(investigation_id) is None:
            return False
        try:
            with _STORE_LOCK:
                _write_json_atomic(self.current_file, {"investigation_id": str(investigation_id)})
            return True
        except OSError as e:
            logger.error(f"Failed to set current investigation: {e}")
            return False

    def get_current_investigation(self) -> Optional[UUID]:
        """Get the current active investigation ID (None if unset or deleted)"""
        data = _read_json(self.current_file, {})
        inv_id = data.get("investigation_id") if isinstance(data, dict) else None
        if not inv_id:
            return None
        try:
            inv_uuid = UUID(inv_id)
        except (ValueError, TypeError):
            return None
        return inv_uuid if str(inv_uuid) in self._load_investigations() else None

    def get_current_investigation_details(self) -> Optional[Dict[str, Any]]:
        current_id = self.get_current_investigation()
        return self.get_investigation_info(current_id) if current_id else None

    def clear_investigation(self) -> bool:
        try:
            with _STORE_LOCK:
                _write_json_atomic(self.current_file, {"investigation_id": None})
            return True
        except OSError as e:
            logger.error(f"Failed to clear investigation: {e}")
            return False

    # ==================== NOTES ====================

    def _note_file(self, investigation_id, note_id) -> Path:
        return self._notes_dir(investigation_id) / f"{UUID(str(note_id))}.json"

    def create_note(
        self,
        investigation_id: UUID,
        title: str,
        content: str,
        note_type: str = "manual",
        related_result_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        note_id: Optional[UUID] = None
    ) -> UUID:
        if not self.get_investigation_info(investigation_id):
            raise ValueError(f"Investigation with ID {investigation_id} does not exist")

        note_id = note_id or uuid4()
        now = datetime.now().isoformat()
        note_data = {
            "note_id": str(note_id),
            "investigation_id": str(investigation_id),
            "title": title,
            "content": content,
            "note_type": note_type,
            "related_result_id": related_result_id,
            "tags": tags or [],
            "created_at": now,
            "updated_at": now
        }
        with _STORE_LOCK:
            _write_json_atomic(self._note_file(investigation_id, note_id), note_data)
            self._touch(investigation_id)
        return note_id

    def get_investigation_notes(
        self,
        investigation_id: UUID,
        note_type: Optional[str] = None,
        tags: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        notes_dir = self._notes_dir(investigation_id)
        if not notes_dir.exists():
            return []
        notes = []
        for file_path in notes_dir.glob("*.json"):
            note = _read_json(file_path, None)
            if not note:
                continue
            if note_type and note.get("note_type") != note_type:
                continue
            if tags and not any(tag in note.get("tags", []) for tag in tags):
                continue
            notes.append(note)
        notes.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return notes

    def get_note(self, investigation_id: UUID, note_id: UUID) -> Optional[Dict[str, Any]]:
        return _read_json(self._note_file(investigation_id, note_id), None)

    def update_note(
        self,
        investigation_id: UUID,
        note_id: UUID,
        title: Optional[str] = None,
        content: Optional[str] = None,
        tags: Optional[List[str]] = None
    ) -> bool:
        with _STORE_LOCK:
            note_file = self._note_file(investigation_id, note_id)
            note = _read_json(note_file, None)
            if note is None:
                return False
            if title is not None:
                note["title"] = title
            if content is not None:
                note["content"] = content
            if tags is not None:
                note["tags"] = tags
            note["updated_at"] = datetime.now().isoformat()
            _write_json_atomic(note_file, note)
            return True

    def delete_note(self, investigation_id: UUID, note_id: UUID) -> bool:
        with _STORE_LOCK:
            note_file = self._note_file(investigation_id, note_id)
            if not note_file.exists():
                return False
            note_file.unlink()
            self._touch(investigation_id)
            return True

    # ==================== LEGACY MIGRATION ====================

    def _migrate_legacy_layout(self) -> None:
        """Convert the old flat layout (one JSON per result in the root, inline
        base64 pictures, auto-generated notes) into per-investigation folders.

        Runs once per results dir; a compressed backup of the old files is
        written to ``backups/`` first.
        """
        key = str(self.results_dir.resolve())
        if key in _MIGRATED_DIRS:
            return
        with _STORE_LOCK:
            if key in _MIGRATED_DIRS:
                return
            try:
                self._run_migration()
            except Exception:
                logger.exception("Investigation storage migration failed; legacy files left untouched")
            try:
                self._repair_legacy_records()
            except Exception:
                logger.exception("Legacy result repair failed")
            try:
                self._rebuild_indexes_if_needed()
            except Exception:
                logger.exception("Index rebuild failed")
            _MIGRATED_DIRS.add(key)

    def _repair_legacy_records(self) -> None:
        """One-time cleanup of results saved by older decorator versions:

        * username searches stored as the raw SSE text of the whole stream ->
          compact found-profiles format;
        * results/parameters stored as ``str(pydantic_model)`` text -> dicts.
        """
        marker = self.results_dir / ".legacy_repaired_v1"
        if marker.exists():
            return
        repaired = 0
        for inv_id in self._load_investigations():
            for summary in list(self._load_index(inv_id).values()):
                record = self.get_result(inv_id, summary["result_id"])
                if record is None:
                    continue
                changed = False
                result = record.get("result")
                if record.get("service_name") == "username":
                    converted = legacy_username_result(result)
                    if converted is not result:
                        record["result"], changed = converted, True
                elif isinstance(result, str):
                    parsed = parse_model_repr(result)
                    if parsed is not None:
                        record["result"], changed = parsed, True
                kwargs = (record.get("parameters") or {}).get("kwargs")
                if isinstance(kwargs, dict):
                    for name, value in list(kwargs.items()):
                        parsed = parse_model_repr(value)
                        if parsed is not None:
                            kwargs[name], changed = parsed, True
                if changed:
                    self._write_result(inv_id, record)
                    repaired += 1
        marker.write_text(datetime.now().isoformat())
        if repaired:
            logger.info("Converted %d legacy investigation results to structured data", repaired)

    def _legacy_files(self) -> Tuple[List[Path], Optional[Path], Optional[Path]]:
        result_files = [
            p for p in self.results_dir.glob("*_*.json")
            if p.name not in ("current_investigation.json",)
        ]
        metadata = self.results_dir / "metadata.json"
        notes_dir = self.results_dir / "notes"
        return (
            result_files,
            metadata if metadata.exists() else None,
            notes_dir if notes_dir.is_dir() else None,
        )

    def _run_migration(self) -> None:
        result_files, metadata_file, notes_dir = self._legacy_files()
        investigations = self._load_investigations()
        inline_pictures = any(isinstance(i.get("picture"), str) and i.get("picture") for i in investigations.values())
        if not (result_files or metadata_file or notes_dir or inline_pictures):
            return

        logger.info("Migrating investigation storage to per-investigation layout...")

        # 1. Backup everything that is about to change
        backups = self.results_dir / "backups"
        backups.mkdir(exist_ok=True)
        backup_path = backups / f"pre_migration_{datetime.now().strftime('%Y%m%d_%H%M%S')}.tar.gz"
        with tarfile.open(backup_path, "w:gz") as tar:
            for path in result_files + [p for p in (metadata_file, notes_dir, self.investigations_file) if p]:
                tar.add(path, arcname=path.name)
        logger.info("Legacy investigation data backed up to %s", backup_path)

        # 2. Pictures -> resized files
        for inv_id, info in investigations.items():
            self._inv_dir(inv_id).joinpath("results").mkdir(parents=True, exist_ok=True)
            picture = info.pop("picture", None)
            info.setdefault("has_picture", False)
            if isinstance(picture, str) and picture:
                try:
                    encoded = picture.split(",", 1)[1] if picture.startswith("data:") else picture
                    self._picture_file(inv_id).write_bytes(process_picture(base64.b64decode(encoded)))
                    info["has_picture"] = True
                    info["picture_version"] = info.get("updated_at")
                except Exception as e:
                    logger.warning("Could not convert picture for %s: %s", inv_id, e)
        self._save_investigations(investigations)

        # 3. Results -> gzip per investigation
        by_inv: Dict[str, List[Dict[str, Any]]] = {}
        for path in result_files:
            record = _read_json(path, None)
            if not isinstance(record, dict) or record.get("investigation_id") not in investigations:
                continue
            record["service_name"] = SERVICE_RENAMES.get(record.get("service_name"), record.get("service_name"))
            if record["service_name"] == "username":
                record["result"] = legacy_username_result(record.get("result"))
            record["result_id"] = path.stem.split("_", 1)[1] if "_" in path.stem else _new_result_id()
            record.setdefault("children", [])
            record.setdefault("partial", False)
            record.setdefault("timestamp", datetime.fromtimestamp(path.stat().st_mtime).isoformat())
            by_inv.setdefault(record["investigation_id"], []).append(record)

        for inv_id, records in by_inv.items():
            records.sort(key=lambda r: r.get("timestamp", ""))
            for record in self._group_ns_whois(records):
                self._write_result(inv_id, record)

        # 4. Keep analyst notes, drop auto-generated copies of results
        if notes_dir:
            for path in notes_dir.glob("*.json"):
                note = _read_json(path, None)
                if not note or note.get("note_type") == "auto" or note.get("investigation_id") not in investigations:
                    continue
                try:
                    _write_json_atomic(self._note_file(note["investigation_id"], note["note_id"]), note)
                except (KeyError, ValueError):
                    continue

        # 5. Remove the legacy files (they are in the backup)
        for path in result_files:
            path.unlink(missing_ok=True)
        if metadata_file:
            metadata_file.unlink(missing_ok=True)
        if notes_dir:
            shutil.rmtree(notes_dir, ignore_errors=True)

        for inv_id in investigations:
            self._touch(inv_id, investigations)
        logger.info("Investigation storage migration complete")

    @staticmethod
    def _group_ns_whois(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Fold the per-domain WHOIS lookups made by the NS module into one
        ``whois_analysis`` child of the NS lookup they followed."""
        def ts(record):
            try:
                return datetime.fromisoformat(record.get("timestamp", ""))
            except ValueError:
                return datetime.min

        whois = [r for r in records if r.get("service_name") == "whois" and r.get("method_name") == "lookup_whois"]
        others = [r for r in records if r not in whois]
        if not whois:
            return records

        # Cluster lookups that happened within 10 minutes of each other
        clusters: List[List[Dict[str, Any]]] = []
        for record in whois:
            if clusters and (ts(record) - ts(clusters[-1][-1])).total_seconds() <= 600:
                clusters[-1].append(record)
            else:
                clusters.append([record])

        ns_lookups = [r for r in others if r.get("service_name") == "ns"]
        for cluster in clusters:
            domains = {}
            for record in cluster:
                kwargs = (record.get("parameters") or {}).get("kwargs", {})
                domain = kwargs.get("domain") or ((record.get("parameters") or {}).get("args") or ["unknown"])[0]
                domains[str(domain)] = record.get("result")
            analysis = {"domains": domains}

            start = ts(cluster[0])
            parent = None
            for candidate in ns_lookups:
                delta = (start - ts(candidate)).total_seconds()
                if 0 <= delta <= 7200:
                    parent = candidate  # latest NS lookup before the cluster
            if parent is not None:
                parent.setdefault("children", []).append({
                    "child_id": cluster[0]["result_id"],
                    "service_name": "ns",
                    "method_name": "whois_analysis",
                    "parameters": {"kwargs": {"domains": list(domains)}},
                    "result": analysis,
                    "summary": summarize(analysis),
                    "partial": False,
                    "timestamp": cluster[-1].get("timestamp"),
                })
            else:
                others.append({
                    **cluster[0],
                    "service_name": "ns",
                    "method_name": "whois_analysis",
                    "parameters": {"kwargs": {"domains": list(domains)}},
                    "result": analysis,
                    "children": [],
                })
        return others
