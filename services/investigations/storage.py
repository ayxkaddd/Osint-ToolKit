"""Reading and writing the case files: atomic JSON / gzip writes under one lock."""
import gzip
import json
import logging
import os
import threading
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any


logger = logging.getLogger("services.investigation_service")

# Shared across every InvestigationService instance (routes, decorator and
# templates each construct their own) so concurrent lookups writing to the same
# JSON files cannot interleave and lose data.
_STORE_LOCK = threading.RLock()

# entities.json path -> (file version, {"raw": parsed file, "sorted": decorated list or None, "version"})
_ENTITY_CACHE: dict[str, tuple[Any, dict[str, Any]]] = {}

# Identifiers found in more than one investigation, rebuilt when any entities.json changes
_SHARED_CACHE: dict[str, Any] = {"versions": None, "index": {}}

# (investigation id, noise shown) -> (versions of its files, graph model); least recently used first
_GRAPH_CACHE: OrderedDict = OrderedDict()

_MIGRATED_DIRS: set = set()


def _read_json(path: Path, default):
    try:
        with open(path) as f:
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
