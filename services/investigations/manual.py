"""Results added by hand: text, identifiers, a link and files."""
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Optional
from uuid import UUID, uuid4

from services.entities import detect
from services.events import parse_date
from .constants import MANUAL_FILES_MAX, MANUAL_FILE_MAX_UPLOAD, MANUAL_FILE_NAME, MANUAL_FILE_TEXT_MAX, MANUAL_SERVICE, MANUAL_TEXT_EXTS, MANUAL_TEXT_MAX
from .storage import _read_json


class ManualResultsMixin:
    def manual_items(self, investigation_id: UUID) -> list[dict[str, Any]]:
        """Everything added by hand (results and follow-ups), oldest first, for the report."""
        items = []
        for summary in self.get_investigation_results(investigation_id):
            services = [summary.get("service_name")] + [c.get("service_name") for c in summary.get("children", [])]
            if MANUAL_SERVICE not in services:
                continue
            record = self.get_result(investigation_id, summary["result_id"]) or {}
            parts = [record] + list(record.get("children", []))
            for part in parts:
                result = part.get("result")
                if part.get("service_name") == MANUAL_SERVICE and isinstance(result, dict):
                    images = [f for f in result.get("files") or []
                              if str(f.get("stored", "")).rsplit(".", 1)[-1] in ("png", "jpg", "jpeg", "gif", "webp", "bmp")]
                    items.append({**result, "images": images, "result_id": record["result_id"],
                                  "timestamp": part.get("timestamp"),
                                  "under": summary.get("target") if part is not record else None})
        return sorted(items, key=lambda i: i.get("timestamp") or "")

    def _files_dir(self, investigation_id) -> Path:
        return self._inv_dir(investigation_id) / "files"

    @staticmethod
    def _record_files(record: dict[str, Any]) -> list[str]:
        """Stored names of the files a result (and its follow-ups) added by hand."""
        names = []
        for part in [record] + list(record.get("children", [])):
            result = part.get("result")
            if part.get("service_name") == MANUAL_SERVICE and isinstance(result, dict):
                names += [f["stored"] for f in result.get("files") or []
                          if isinstance(f, dict) and MANUAL_FILE_NAME.fullmatch(str(f.get("stored", "")))]
        return names

    def _result_files(self, investigation_id, summary: dict[str, Any]) -> list[str]:
        """Files of a result, read only when its index entry says it has manual parts."""
        services = [summary.get("service_name")] + [c.get("service_name") for c in summary.get("children", [])]
        if MANUAL_SERVICE not in services:
            return []
        record = self.get_result(investigation_id, summary["result_id"])
        return self._record_files(record) if record else []

    def _delete_files(self, investigation_id, result_id: str, names: list[str]) -> None:
        """Delete a removed result's files, unless a note keeps a snapshot of it."""
        if not names:
            return
        snapshots = _read_json(self._snapshots_dir(investigation_id) / "index.json", {})
        if result_id in snapshots.values():
            return
        for name in names:
            (self._files_dir(investigation_id) / name).unlink(missing_ok=True)

    def get_file_path(self, investigation_id: UUID, name: str) -> Optional[Path]:
        if not MANUAL_FILE_NAME.fullmatch(name or ""):
            return None
        path = self._files_dir(investigation_id) / name
        return path if path.is_file() else None

    @staticmethod
    def _clean_filename(name: str) -> str:
        name = re.split(r"[\\/]", name or "")[-1]
        name = "".join(c for c in name if c.isprintable()).strip()
        return name[:200] or "file"

    def add_manual_result(
        self,
        investigation_id: UUID,
        title: str,
        source: str = "",
        url: str = "",
        date: str = "",
        text: str = "",
        identifiers: str = "",
        files: Optional[list[tuple[str, bytes]]] = None,
        parent_result_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Save something found outside the toolkit (a screenshot, a page, a bot's answer)
        as a result. Returns {"result_id", "skipped": identifier lines not recognised}."""
        title = (title or "").strip()[:200]
        if not title:
            raise ValueError("Give it a title")
        files = files or []
        if len(files) > MANUAL_FILES_MAX:
            raise ValueError(f"At most {MANUAL_FILES_MAX} files at once")
        text = (text or "").strip()
        if len(text.encode("utf-8")) > MANUAL_TEXT_MAX:
            raise ValueError("The text is too long (max 1 MB) - add it as a file instead")
        url = (url or "").strip()
        if url and not re.match(r"https?://\S+$", url, re.I):
            raise ValueError("The link must start with http:// or https://")
        parsed_date = None
        if (date or "").strip():
            parsed_date = parse_date(date.strip(), "date")
            if not parsed_date:
                raise ValueError("The date is not recognised - use YYYY-MM-DD")

        entities: dict[str, list[str]] = {}
        skipped = []
        for line in (identifiers or "").splitlines():
            line = line.strip()
            if not line:
                continue
            found = detect(line)
            if found:
                values = entities.setdefault(found[0].type, [])
                if found[0].value not in values:
                    values.append(found[0].value)
            else:
                skipped.append(line)

        data = None
        if text[:1] in "{[":
            try:
                data, text = json.loads(text), ""
            except json.JSONDecodeError:
                pass
        if not (text or data is not None or entities or files or url):
            raise ValueError("Add some text, identifiers, a link or a file")

        stored = []
        directory = self._files_dir(investigation_id)
        try:
            for filename, content in files:
                if len(content) > MANUAL_FILE_MAX_UPLOAD:
                    raise ValueError(f"{self._clean_filename(filename)} is too large (max 50 MB)")
                name = self._clean_filename(filename)
                ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
                ext = ext if re.fullmatch(r"[a-z0-9]{1,10}", ext) else "bin"
                item = {"name": name, "stored": f"{uuid4().hex}.{ext}", "size": len(content),
                        "sha256": hashlib.sha256(content).hexdigest()}
                if ext in MANUAL_TEXT_EXTS and len(content) <= MANUAL_FILE_TEXT_MAX:
                    decoded = content.decode("utf-8", errors="replace")
                    item["content"] = decoded
                    if ext == "json":
                        try:
                            item["content"] = json.loads(decoded)
                        except json.JSONDecodeError:
                            pass
                directory.mkdir(parents=True, exist_ok=True)
                tmp = directory / f"{item['stored']}.tmp"
                tmp.write_bytes(content)
                os.replace(tmp, directory / item["stored"])
                stored.append(item)

            result = {
                "kind": "manual",
                "title": title,
                "source": (source or "").strip()[:200] or None,
                "url": url or None,
                "date": parsed_date[0] if parsed_date else None,
                "date_precision": parsed_date[1] if parsed_date else None,
                "text": text or None,
                "data": data,
                "entities": entities or None,
                "files": stored,
            }
            parameters = {k: v for k, v in {"title": title, "source": result["source"]}.items() if v}
            result_id = self.save_investigation_result(investigation_id, MANUAL_SERVICE, "upload", parameters,
                                                       result, parent_result_id=parent_result_id)
        except Exception:
            for item in stored:
                (directory / item["stored"]).unlink(missing_ok=True)
            raise
        return {"result_id": result_id, "skipped": skipped}
