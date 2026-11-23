"""Notes, the images in them, and snapshots of results attached to notes."""
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from uuid import UUID, uuid4

from .constants import NOTE_IMAGE_NAME
from .images import process_note_image
from .storage import _STORE_LOCK, _read_gz, _read_json, _valid_id, _write_gz_atomic, _write_json_atomic
from .summaries import find_target, summarize


class NotesMixin:
    def _note_file(self, investigation_id, note_id) -> Path:
        return self._notes_dir(investigation_id) / f"{UUID(str(note_id))}.json"

    def create_note(
        self,
        investigation_id: UUID,
        title: str,
        content: str,
        note_type: str = "manual",
        related_result_id: Optional[str] = None,
        tags: Optional[list[str]] = None,
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
        tags: Optional[list[str]] = None
    ) -> list[dict[str, Any]]:
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

    def get_note(self, investigation_id: UUID, note_id: UUID) -> Optional[dict[str, Any]]:
        return _read_json(self._note_file(investigation_id, note_id), None)

    def update_note(
        self,
        investigation_id: UUID,
        note_id: UUID,
        title: Optional[str] = None,
        content: Optional[str] = None,
        tags: Optional[list[str]] = None
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

    def _note_images_dir(self, investigation_id) -> Path:
        return self._notes_dir(investigation_id) / "images"

    def save_note_image(self, investigation_id: UUID, data: bytes) -> str:
        """Store an image for notes under a generated name, which is returned. Nothing
        from the upload (its name, its type) is used for the path."""
        image = process_note_image(data)
        name = f"{uuid4().hex}.webp"
        directory = self._note_images_dir(investigation_id)
        directory.mkdir(parents=True, exist_ok=True)
        tmp = directory / f"{name}.tmp"
        tmp.write_bytes(image)
        os.replace(tmp, directory / name)
        return name

    def get_note_image_path(self, investigation_id: UUID, name: str) -> Optional[Path]:
        if not NOTE_IMAGE_NAME.fullmatch(name or ""):
            return None
        path = self._note_images_dir(investigation_id) / name
        return path if path.is_file() else None

    def _snapshots_dir(self, investigation_id) -> Path:
        return self._notes_dir(investigation_id) / "snapshots"

    def create_snapshot(self, investigation_id: UUID, result_id: str) -> Optional[dict[str, Any]]:
        """Copy a result so a note keeps it as it was, even if the result is deleted later."""
        record = self.get_result(investigation_id, result_id) if _valid_id(result_id) else None
        if record is None:
            return None
        meta = {
            "snapshot_id": uuid4().hex,
            "result_id": record["result_id"],
            "service_name": record.get("service_name"),
            "method_name": record.get("method_name"),
            "parameters": record.get("parameters"),
            "target": find_target(record.get("parameters") or {}),
            "summary": summarize(record.get("result")),
            "timestamp": record.get("timestamp"),
            "created_at": datetime.now().isoformat(),
        }
        directory = self._snapshots_dir(investigation_id)
        with _STORE_LOCK:
            _write_gz_atomic(directory / f"{meta['snapshot_id']}.json.gz", {**meta, "record": record})
            index = _read_json(directory / "index.json", {})
            index[meta["snapshot_id"]] = record["result_id"]
            _write_json_atomic(directory / "index.json", index)
        return meta

    def get_snapshot(self, investigation_id: UUID, snapshot_id: str) -> Optional[dict[str, Any]]:
        if not re.fullmatch(r"[0-9a-f]{32}", snapshot_id or ""):
            return None
        return _read_gz(self._snapshots_dir(investigation_id) / f"{snapshot_id}.json.gz")

    def get_snapshots(self, investigation_id: UUID) -> list[dict[str, Any]]:
        directory = self._snapshots_dir(investigation_id)
        return [snap for path in sorted(directory.glob("*.json.gz")) if (snap := _read_gz(path))]

    def result_references(self, investigation_id: UUID, result_id: str) -> list[dict[str, Any]]:
        """Notes that link to a result or hold a snapshot of it."""
        snapshots = [s for s, r in _read_json(self._snapshots_dir(investigation_id) / "index.json", {}).items() if r == result_id]
        link = re.compile(r"\[\[result:" + re.escape(result_id) + r"(?:[|\]])")
        found = []
        for note in self.get_investigation_notes(investigation_id):
            content = note.get("content") or ""
            links = len(link.findall(content))
            attached = sum(content.count(f"snapshot:{s}") for s in snapshots)
            if links or attached:
                found.append({"note_id": note["note_id"], "title": note.get("title") or "Untitled note",
                              "links": links, "snapshots": attached})
        return found
