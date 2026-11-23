"""What a plugin returns, made into result items; secrets redacted, raw data capped."""
import dataclasses
import json
import re
from typing import Any, Union
from collections.abc import Mapping
from urllib.parse import quote


from plugins.sdk import Item
from services.entities import ENTITY_TYPES
from .constants import MASK, MAX_RAW_CHARS
from .registry import Plugin


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ", ".join(_text(v) for v in value if v not in (None, ""))
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


ITEM_KEYS = {f.name for f in dataclasses.fields(Item)}


def _flatten(values: Any) -> list[Any]:
    if isinstance(values, (list, tuple)):
        return [v for value in values for v in _flatten(value)]
    return [values]


def normalize_item(obj: Union[Item, Mapping[str, Any]], plugin: Plugin) -> dict[str, Any]:
    """An Item / item dict -> the stored card: {title, subtitle, url, image, site, icon,
    category, fields: [[label, value]], entities: {type: [values]}}."""
    if isinstance(obj, Item):
        obj = dataclasses.asdict(obj)
    raw_fields = obj.get("fields") or {}
    pairs = raw_fields.items() if isinstance(raw_fields, Mapping) else raw_fields
    fields = []
    for pair in pairs:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            continue
        label, value = pair
        if value is None or value == "" or value == [] or value == {}:
            continue
        if isinstance(value, (list, tuple)):
            value = _text(value)
        elif isinstance(value, dict):
            value = json.dumps(value, ensure_ascii=False)
        if isinstance(value, str):
            lines = [line.strip() for line in value.strip().splitlines() if line.strip()]
            value = (", " if all(len(line) <= 80 for line in lines) else " ").join(lines)[:2000]
        fields.append([_text(label)[:80], value])
    entities: dict[str, list[str]] = {}
    for etype, values in (obj.get("entities") or {}).items():
        if etype not in ENTITY_TYPES:
            continue
        found = []
        for value in _flatten(values):
            if value in (None, ""):
                continue
            parts = [part[:500] for part in re.split(r"\s*\n\s*", _text(value).strip()) if part]
            if etype == "domain":
                parts = [part.removeprefix("*.") for part in parts]
            found += parts
        if found:
            entities[etype] = list(dict.fromkeys(found))[:200]
    site = _text(obj.get("site")).strip().lower() or (plugin.manifest.site if plugin.manifest else "")
    icon = _text(obj.get("icon")) or (f"/api/oi/icon/{quote(site)}" if site else plugin.icon_url)
    item = {
        "title": _text(obj.get("title")).strip()[:300] or plugin.name,
        "subtitle": _text(obj.get("subtitle")).strip()[:300],
        "url": _text(obj.get("url")).strip()[:2000],
        "image": _text(obj.get("image")).strip()[:2000],
        "site": site,
        "icon": icon,
        "category": _text(obj.get("category")).strip()[:80],
        "fields": fields[:100],
        "entities": entities,
    }
    return {k: v for k, v in item.items() if k == "title" or v not in ("", [], {})}


def _is_item(value: Any) -> bool:
    return isinstance(value, Item) or (isinstance(value, dict) and "title" in value and set(value) <= ITEM_KEYS)


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str, ensure_ascii=False))


def split_output(result: Any, plugin: Plugin) -> tuple[list[dict[str, Any]], Any]:
    """What run() returned/yielded -> (cards, other data shown as a tree)."""
    if result is None:
        return [], None
    if _is_item(result):
        return [normalize_item(result, plugin)], None
    if isinstance(result, (list, tuple)):
        if not result:
            return [], None
        if all(_is_item(r) for r in result):
            return [normalize_item(r, plugin) for r in result], None
    return [], _json_safe(result)


def redact(value: Any, secrets: list[str]) -> Any:
    if not secrets:
        return value
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, MASK)
        return value
    if isinstance(value, dict):
        return {k: redact(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, secrets) for v in value]
    return value


def _cap_raw(raw: Any) -> Any:
    if raw is None:
        return None
    text = json.dumps(raw, default=str, ensure_ascii=False)
    if len(text) > MAX_RAW_CHARS:
        return {"truncated": True, "characters": len(text)}
    return raw


def _snippet(text: str, limit: int = 300) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:limit] + ("…" if len(text) > limit else "")
