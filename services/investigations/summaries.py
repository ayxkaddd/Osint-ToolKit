"""The one-line summary and target of a result, shown in lists without opening it."""
import re
from typing import Any, Optional

from services.entities import SKIP_KEY_RE
from services.events import humanize
from utils.legacy_repr import parse_model_repr
from .constants import CHANGES_MAX_LEAVES, CHANGES_VOLATILE_KEYS, TARGET_KEYS


def _leaf_values(result: Any) -> set:
    """{(path without list positions, value)} of a result's plain values, for comparing runs."""
    out: set = set()

    def visit(value: Any, path: str):
        if len(out) >= CHANGES_MAX_LEAVES:
            return
        if isinstance(value, dict):
            for k, v in value.items():
                k = str(k)
                if k not in CHANGES_VOLATILE_KEYS and not SKIP_KEY_RE.search(k):
                    visit(v, f"{path}.{k}" if path else k)
        elif isinstance(value, list):
            for item in value[:5000]:
                visit(item, f"{path}[]")
        elif value not in (None, "") and not isinstance(value, bool):
            out.add((path, str(value)[:500]))
        elif isinstance(value, bool):
            out.add((path, "yes" if value else "no"))

    visit(result, "")
    return out


def _path_label(path: str) -> str:
    """"results[].profile_data.email" -> "Profile data · Email"."""
    parts = [p for p in re.split(r"\[\]|\.", path) if p]
    return " · ".join(humanize(p) for p in parts[-2:]) if parts else "Value"


def find_target(parameters: dict[str, Any]) -> Optional[str]:
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
    if isinstance(result, dict) and result.get("kind") == "manual":
        files = len(result.get("files") or [])
        identifiers = sum(len(v) for v in (result.get("entities") or {}).values())
        parts = [f"{files} file{'s' if files != 1 else ''}" if files else "",
                 "text" if result.get("text") or result.get("data") is not None else "",
                 f"{identifiers} identifier{'s' if identifiers != 1 else ''}" if identifiers else ""]
        return " · ".join(p for p in parts if p) or "Added manually"
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
