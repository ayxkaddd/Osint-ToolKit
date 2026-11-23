"""Which plugins the user has checked: plugins/.trust.json and the hash of a plugin's files."""
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


from .constants import BUNDLED, MAX_FILES, TRUST_FILE, _lock


def _files(folder: Path) -> list[Path]:
    files = [p for p in folder.rglob("*") if p.is_file()
             and "__pycache__" not in p.parts and not any(part.startswith(".") for part in p.relative_to(folder).parts)
             and p.suffix != ".pyc"]
    return sorted(files)[:MAX_FILES]


def _hash(folder: Path) -> str:
    digest = hashlib.sha256()
    for path in _files(folder):
        digest.update(path.relative_to(folder).as_posix().encode() + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def load_trust() -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(TRUST_FILE.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def write_trust(plugin_id: str, mode: Optional[str], sha: str = "") -> None:
    """mode "local" (your own plugin: always runs), "approved" (reviewed: runs while
    its files stay the same) or None (forget)."""
    with _lock:
        trust = load_trust()
        if mode:
            trust[plugin_id] = {"mode": mode, "sha": sha, "at": datetime.now().isoformat(timespec="seconds")}
        else:
            trust.pop(plugin_id, None)
        TRUST_FILE.parent.mkdir(parents=True, exist_ok=True)
        TRUST_FILE.write_text(json.dumps(trust, indent=2) + "\n")


def _source(plugin_id: str, sha: str, trust: dict[str, dict[str, Any]]) -> str:
    entry = trust.get(plugin_id) or {}
    if entry.get("mode") == "local":
        return "local"
    if entry.get("mode") == "approved":
        return "approved" if entry.get("sha") == sha else "changed"
    return "bundled" if plugin_id in BUNDLED else "unreviewed"
