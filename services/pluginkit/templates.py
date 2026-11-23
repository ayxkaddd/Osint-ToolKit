"""No-code plugins: paths into the answer, {value} templates, and the cards built from them."""
from typing import Any, Optional
from collections.abc import Callable
from urllib.parse import quote


from .constants import FILTERS, PATH_TOKEN_RE, TEMPLATE_RE
from .manifest import ResponseSpec
from .registry import Plugin
from .results import _text, normalize_item


def get_path(data: Any, path: str) -> Any:
    """``a.b[0].c``; ``list[].x`` collects x from every element (returns a list)."""
    if path in ("", "."):
        return data
    current, spread = [data], False
    for index, key in PATH_TOKEN_RE.findall(path):
        nxt = []
        for value in current:
            if key:
                if isinstance(value, dict) and key in value:
                    nxt.append(value[key])
            elif index == "":
                if isinstance(value, list):
                    nxt.extend(value)
                    spread = True
            elif isinstance(value, list):
                i = int(index)
                if -len(value) <= i < len(value):
                    nxt.append(value[i])
        current = nxt
    if spread:
        return [v for v in current if v not in (None, "")]
    return current[0] if current else None


def render(template: str, lookup: Callable[[str], Any], quote_values: bool = False) -> str:
    def substitute(match):
        value = _text(lookup(match.group(1)))
        for name in filter(None, match.group(2).split("|")):
            value = FILTERS[name](value)
        return quote(value, safe="") if quote_values else value
    return TEMPLATE_RE.sub(substitute, template)


def _row_lookup(row: Any, value: str, kind: str) -> Callable[[str], Any]:
    def lookup(name: str) -> Any:
        if name == "$value":
            return value
        if name == "$type":
            return kind
        return get_path(row, name)
    return lookup


def _default_title(row: Any, fallback: str) -> str:
    if isinstance(row, dict):
        for key in ("title", "name", "full_name", "display_name", "login", "username", "domain", "email", "id"):
            if row.get(key) not in (None, ""):
                return _text(row[key])
        return fallback
    return _text(row) or fallback


def _auto_fields(row: Any) -> list[tuple[str, Any]]:
    if not isinstance(row, dict):
        return []
    rows = []
    for key, value in row.items():
        if isinstance(value, (dict, list)) and not (isinstance(value, list) and all(not isinstance(v, (dict, list)) for v in value)):
            continue
        rows.append((str(key).replace("_", " ").strip().capitalize(), value))
    return rows[:40]


def _auto_spec(spec: ResponseSpec, data: Any) -> ResponseSpec:
    """response: auto - the mapping detected for this answer, with what the manifest sets on top."""
    from services.plugin_builder import suggest_mapping
    detected = suggest_mapping(get_path(data, spec.root) if spec.root else data, spec.format)
    merged = spec.model_dump()
    merged["auto"] = False
    if spec.items is None and detected.get("items"):
        merged["items"] = detected["items"]
    for key in ("title", "subtitle", "url", "image"):
        if not merged[key] and detected.get(key):
            merged[key] = detected[key]
    merged["fields"] = {**(detected.get("fields") or {}), **(spec.fields or {})}
    entities: dict[str, list[str]] = {}
    for source in (detected.get("entities") or {}, spec.entities):
        for etype, paths in source.items():
            for path in paths if isinstance(paths, list) else [paths]:
                if path not in entities.setdefault(etype, []):
                    entities[etype].append(path)
    merged["entities"] = entities
    return ResponseSpec.model_validate(merged)


def build_items(plugin: Plugin, data: Any, value: str, kind: str,
                spec: Optional[ResponseSpec] = None) -> list[dict[str, Any]]:
    """Cards from an API answer, as described by a response: section."""
    assert plugin.manifest is not None
    spec = spec or plugin.manifest.response
    if spec.auto:
        spec = _auto_spec(spec, data)
    root = get_path(data, spec.root) if spec.root else data
    rows = get_path(root, spec.items) if spec.items not in (None, "", ".") else root
    if rows in (None, "", {}, []):
        return []
    if not isinstance(rows, list):
        rows = [rows]
    if spec.unique:
        seen, unique_rows = set(), []
        for row in rows:
            key = _text(get_path(row, spec.unique))
            if key not in seen:
                seen.add(key)
                unique_rows.append(row)
        rows = unique_rows
    items = []
    for row in rows[:spec.limit]:
        lookup = _row_lookup(row, value, kind)

        def field_value(expr: str, row=row, lookup=lookup) -> Any:
            """A path into the row ("owner.name"), or a template ("{first} {last}")."""
            if not expr:
                return None
            return render(expr, lookup) if "{" in expr else get_path(row, expr)

        fields = ([(label, field_value(expr)) for label, expr in spec.fields.items()]
                  if spec.fields is not None else _auto_fields(row))
        items.append(normalize_item({
            "title": field_value(spec.title) if spec.title else _default_title(row, plugin.name),
            "subtitle": field_value(spec.subtitle),
            "url": field_value(spec.url),
            "image": field_value(spec.image),
            "site": field_value(spec.site),
            "category": field_value(spec.category),
            "fields": fields,
            "entities": {t: [get_path(row, p) for p in (paths if isinstance(paths, list) else [paths])]
                         for t, paths in spec.entities.items()},
        }, plugin))
    return items
