"""Parse captured streaming responses and reduce them to compact stored results.

The investigation decorator tees a streaming response: the client receives each
chunk immediately while a copy is collected. When the stream ends, the copy is
parsed into events here and a module-specific reducer turns the event log into
the result that gets saved (e.g. only the sites where a username was found).
"""
import json
from typing import Any, Callable, Dict, List, Optional


def _maybe_json(text: str) -> Any:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


def parse_sse(text: str) -> List[Any]:
    """Split a text/event-stream body into event payloads.

    Each event's ``data:`` lines are joined; JSON payloads are decoded. Named
    events (``event: x``) come back as ``{"event": x, "data": payload}``.
    """
    events = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        data_lines, name = [], None
        for line in block.split("\n"):
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip(" "))
            elif line.startswith("event:"):
                name = line[6:].strip()
        if not data_lines:
            continue
        payload = _maybe_json("\n".join(data_lines))
        events.append({"event": name, "data": payload} if name else payload)
    return events


def parse_ndjson(text: str) -> List[Any]:
    return [_maybe_json(line) for line in text.splitlines() if line.strip()]


def parse_stream(text: str, media_type: Optional[str]) -> Any:
    media_type = (media_type or "").lower()
    if "event-stream" in media_type:
        return parse_sse(text)
    if "ndjson" in media_type or "jsonl" in media_type:
        return parse_ndjson(text)
    stripped = text.strip()
    if stripped.startswith("data:"):
        return parse_sse(text)
    return _maybe_json(stripped)


# ---------------------------------------------------------------------------
# Reducers: (events) -> stored result
# ---------------------------------------------------------------------------

def reduce_username_search(events: List[Any]) -> Dict[str, Any]:
    """Keep only found profiles (with extracted profile data) and the summary."""
    username = None
    total_sites = None
    completed: Dict[str, Any] = {}
    found: Dict[str, Dict[str, Any]] = {}
    profiles: Dict[str, Any] = {}
    web_mentions: List[Dict[str, Any]] = []
    checked = 0

    for event in events:
        if not isinstance(event, dict):
            continue
        kind = event.get("event_type")
        data = event.get("data") or {}
        if kind == "search_started":
            username = data.get("username", username)
            total_sites = data.get("total_sites", total_sites)
        elif kind == "site_result":
            checked += 1
            if data.get("status") == "found":
                entry = {k: v for k, v in data.items() if k not in ("progress", "error_message")}
                found[entry.get("url") or entry.get("site_name")] = entry
        elif kind == "profile_extracted":
            profiles[data.get("url")] = data.get("profile_data")
        elif kind == "duckduckgo_result":
            web_mentions.append(data)
        elif kind == "search_completed":
            completed = data
            username = data.get("username", username)

    for url, profile in profiles.items():
        if url in found and profile:
            found[url]["profile_data"] = profile

    results = sorted(found.values(), key=lambda r: (r.get("category") or "", r.get("site_name") or ""))
    return {
        "username": username,
        "stats": {
            "total": total_sites if total_sites is not None else completed.get("total_checked"),
            "checked": completed.get("total_checked", checked),
            "found": len(results),
            "errors": completed.get("total_errors"),
            "duration": completed.get("search_time_seconds"),
            "completed": bool(completed),
        },
        "results": results,
        "web_mentions": web_mentions,
    }


def reduce_whois_analysis(events: List[Any]) -> Dict[str, Any]:
    """NDJSON events from the NS WHOIS analysis -> {domains: {domain: whois}}."""
    domains: Dict[str, Any] = {}
    for event in events:
        if isinstance(event, dict) and event.get("type") == "domain":
            domains[event.get("domain")] = event.get("whois") if event.get("ok") else {"error": event.get("error")}
    return {"domains": domains}


def legacy_username_result(result: Any) -> Any:
    """Convert an old raw-SSE username record into the compact format."""
    if isinstance(result, str) and "data:" in result:
        return reduce_username_search(parse_sse(result))
    if isinstance(result, list) and result and isinstance(result[0], dict) and "event_type" in result[0]:
        return reduce_username_search(result)
    return result


def reduce_fingerprints(events: List[Any]) -> Dict[str, Any]:
    """NDJSON events from the NS fingerprint run -> {domains: {domain: fingerprint}, no_response: [...]}."""
    domains: Dict[str, Any] = {}
    no_response: List[str] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get("type") == "domain":
            domains[event.get("domain")] = event.get("fingerprint")
        elif event.get("type") == "complete":
            no_response = event.get("no_response") or []
        elif event.get("type") == "error":
            return {"error": event.get("error"), "domains": domains}
    return {"domains": domains, "no_response": no_response}


Reducer = Callable[[List[Any]], Any]


def reduce_oi_stream(events: List[Any]) -> Dict[str, Any]:
    """OSINT Industries stream -> the same shape as a JSON lookup: {type, query, modules: [cards]}."""
    from services.oi_service import sort_oi_cards

    result: Dict[str, Any] = {"modules": [], "modules_checked": 0, "completed": False}
    for event in events:
        if not isinstance(event, dict):
            continue
        kind = event.get("event")
        if kind == "started":
            for key in ("type", "query", "premium", "premium_modules_only"):
                result[key] = event.get(key)
        elif kind == "module":
            result["modules"].extend(event.get("cards") or [])
            result["modules_checked"] += 1
        elif kind == "error":
            result["error"] = event.get("detail")
        elif kind == "warning":   # one of several lookups failed
            result.setdefault("warnings", []).append(event.get("detail"))
        elif kind == "done":
            result["completed"] = bool(event.get("completed"))
    result["modules"] = sort_oi_cards(result["modules"])
    return result


def reduce_plugin_stream(events: List[Any]) -> Dict[str, Any]:
    """Plugin run (services/plugin_loader.py events) -> {kind: plugin_result, plugin, items, data, ...}."""
    result: Dict[str, Any] = {"kind": "plugin_result", "items": [], "completed": False}
    data: List[Any] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        kind = event.get("event")
        if kind == "started":
            for key in ("plugin", "name", "value", "type"):
                result[key] = event.get(key)
        elif kind == "item":
            result["items"].append(event.get("item"))
        elif kind == "data":
            data.append(event.get("data"))
        elif kind == "error":
            result["error"] = event.get("detail")
        elif kind == "warning":   # one of several lookups failed
            result.setdefault("warnings", []).append(event.get("detail"))
        elif kind == "done":
            result["completed"] = bool(event.get("completed"))
            for key in ("note", "raw", "lookups"):
                if event.get(key) is not None:
                    result[key] = event[key]
    if data:
        result["data"] = data[0] if len(data) == 1 else data
    return result
