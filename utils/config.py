import os
import threading
from pathlib import Path
from typing import Dict, Optional

from dotenv import dotenv_values

ENV_PATH = Path(".env")

_lock = threading.Lock()
_cache: Dict[str, Optional[str]] = {}
_cache_mtime: Optional[float] = None


def _load() -> Dict[str, Optional[str]]:
    """Return .env contents, re-reading the file only when it changed on disk."""
    global _cache, _cache_mtime
    try:
        mtime = ENV_PATH.stat().st_mtime
    except FileNotFoundError:
        return {}
    with _lock:
        if mtime != _cache_mtime:
            _cache = dict(dotenv_values(ENV_PATH))
            _cache_mtime = mtime
        return _cache


def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    """Read a setting from .env (fresh) falling back to the process environment."""
    value = _load().get(key)
    if value is None or value == "":
        value = os.getenv(key, default)
    return value


def update_env(values: Dict[str, Optional[str]]) -> None:
    """Set keys in .env in place, keeping comments, ordering and unrelated keys.

    A value of None removes the key. Updated values are also exported to
    os.environ so services reading os.getenv() pick them up immediately.
    """
    lines = ENV_PATH.read_text().splitlines() if ENV_PATH.exists() else []
    remaining = dict(values)
    out = []
    for line in lines:
        stripped = line.strip()
        key = stripped.split("=", 1)[0].strip() if "=" in stripped and not stripped.startswith("#") else None
        if key is not None and key in remaining:
            value = remaining.pop(key)
            if value is not None:
                out.append(f"{key}={value}")
            continue
        out.append(line)
    for key, value in remaining.items():
        if value is not None:
            out.append(f"{key}={value}")

    tmp = ENV_PATH.with_suffix(".tmp")
    tmp.write_text("\n".join(out) + "\n")
    os.replace(tmp, ENV_PATH)

    for key, value in values.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
