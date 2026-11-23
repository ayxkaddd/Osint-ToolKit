"""Investigations themselves: create, list, update, delete, the current one, the .zip export."""
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from uuid import UUID, uuid4

from .constants import SERVICE_ALIASES, STORED_SUFFIXES
from .images import process_picture
from .storage import _STORE_LOCK, _read_json, _valid_id, _write_json_atomic, logger


class CaseStore:
    def __init__(self, results_dir: str = "investigation_results"):
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(exist_ok=True)
        self.investigations_file = self.results_dir / "investigations.json"
        self.current_file = self.results_dir / "current_investigation.json"
        if not self.investigations_file.exists():
            _write_json_atomic(self.investigations_file, {})
        self._migrate_legacy_layout()

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

    def _load_investigations(self) -> dict[str, Any]:
        return _read_json(self.investigations_file, {})

    def _save_investigations(self, investigations: dict[str, Any]) -> None:
        _write_json_atomic(self.investigations_file, investigations)

    def _load_index(self, investigation_id) -> dict[str, Any]:
        return _read_json(self._index_file(investigation_id), {})

    def _save_index(self, investigation_id, index: dict[str, Any]) -> None:
        _write_json_atomic(self._index_file(investigation_id), index, compact=True)

    def _public_info(self, info: dict[str, Any]) -> dict[str, Any]:
        info = dict(info)
        info.pop("picture", None)
        if info.get("has_picture"):
            version = info.get("picture_version") or info.get("updated_at", "")
            info["picture_url"] = f"/api/investigations/{info['investigation_id']}/picture?v={version}"
        else:
            info["picture_url"] = None
        return info

    def _touch(self, investigation_id, investigations: Optional[dict[str, Any]] = None) -> None:
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

    def get_investigation_info(self, investigation_id) -> Optional[dict[str, Any]]:
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

    def list_all_investigations(self) -> list[dict[str, Any]]:
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

    def get_investigation_result(self, investigation_id: UUID) -> Optional[dict[str, Any]]:
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
    ) -> list[dict[str, Any]]:
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

    def set_current_investigation(self, investigation_id: UUID) -> bool:
        """Set the current active investigation by ID. Returns False if it doesn't exist."""
        if self.get_investigation_info(investigation_id) is None:
            return False
        try:
            with _STORE_LOCK:
                _write_json_atomic(self.current_file, {"investigation_id": str(investigation_id)})
            return True
        except OSError as e:
            logger.error('Failed to set current investigation: %s', e)
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

    def get_current_investigation_details(self) -> Optional[dict[str, Any]]:
        current_id = self.get_current_investigation()
        return self.get_investigation_info(current_id) if current_id else None

    def clear_investigation(self) -> bool:
        try:
            with _STORE_LOCK:
                _write_json_atomic(self.current_file, {"investigation_id": None})
            return True
        except OSError as e:
            logger.error('Failed to clear investigation: %s', e)
            return False

    def export_archive(self, investigation_id: UUID, export_data: dict[str, Any]) -> Path:
        """A .zip of the whole case: investigation.json plus the files added by hand,
        note images and the picture. Written to a temporary file; the caller removes it."""
        import tempfile
        import zipfile
        inv_dir = self._inv_dir(investigation_id)
        tmp = tempfile.NamedTemporaryFile(prefix="investigation-", suffix=".zip", delete=False)
        tmp.close()
        with zipfile.ZipFile(tmp.name, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("investigation.json", json.dumps(export_data, indent=2, default=str, ensure_ascii=False))
            for folder, arc_folder in ((self._files_dir(investigation_id), "files"),
                                       (self._note_images_dir(investigation_id), "notes/images")):
                for path in sorted(folder.glob("*")) if folder.is_dir() else []:
                    if path.is_file() and not path.name.endswith(".tmp"):
                        # images and PDFs are compressed already
                        kind = zipfile.ZIP_STORED if path.suffix.lower() in STORED_SUFFIXES else zipfile.ZIP_DEFLATED
                        archive.write(path, f"{arc_folder}/{path.name}", compress_type=kind)
            picture = inv_dir / "picture.webp"
            if picture.is_file():
                archive.write(picture, "picture.webp", compress_type=zipfile.ZIP_STORED)
        return Path(tmp.name)
