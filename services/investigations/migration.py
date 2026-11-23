"""Upgrading case folders written by older versions (run once at startup)."""
import base64
import shutil
import tarfile
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from utils.legacy_repr import parse_model_repr
from utils.stream_reducers import legacy_username_result
from .constants import SERVICE_RENAMES
from .images import process_picture
from .storage import _MIGRATED_DIRS, _STORE_LOCK, _new_result_id, _read_json, _write_json_atomic, logger
from .summaries import summarize


class MigrationMixin:
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

    def _legacy_files(self) -> tuple[list[Path], Optional[Path], Optional[Path]]:
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
        by_inv: dict[str, list[dict[str, Any]]] = {}
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
    def _group_ns_whois(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
        clusters: list[list[dict[str, Any]]] = []
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
