"""Plugin builder (templates/plugin_builder.html): create and edit no-code plugins
from the UI.

* ``parse_curl`` - a pasted curl command -> request, with the API key moved into a
  setting and the looked-up value replaced by ``{value}``.
* ``test_draft`` - send a draft plugin's request and return the answer, the cards
  it gives and a suggested ``response:`` mapping (``suggest_mapping``).
* ``preview_draft`` - cards for a mapping, from an answer already fetched.
* ``save_draft`` / ``delete_plugin`` - write or remove plugins/<id>/plugin.yaml.
  Plugins made here are marked as yours (no "from another source" review).
"""
import base64
import json
import re
import shlex
import shutil
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, urlsplit, urlunsplit

import yaml
from pydantic import ValidationError

from plugins.sdk import PluginError
from services import plugin_loader as pl
from services.entities import ENTITY_TYPES, _key_hint, detect, make_entity
from utils.config import update_env

SECRET_NAME_RE = re.compile(r"auth|api[-_]?key|apikey|token|secret|access[-_]?key|password|^key$|x-.*-key", re.I)
TITLE_KEYS = ("title", "name", "full_name", "fullname", "display_name", "displayname", "username", "login",
              "screen_name", "handle", "nickname", "email", "domain", "hostname", "ip")
TITLE_SUFFIXES = ("name", "title", "label")
DOMAIN_KEY_RE = re.compile(r"domain|host|name_value|common_name|dns|fqdn|cn$", re.I)
SUBTITLE_KEYS = ("username", "login", "screen_name", "handle", "email", "headline", "job_title", "description",
                 "bio", "status", "type", "category")
URL_KEYS = ("html_url", "profile_url", "profile", "url", "link", "href", "permalink", "web_url", "website")
IMAGE_RE = re.compile(r"avatar|photo|image|picture|pic$|thumbnail|thumb|logo|icon", re.I)
IMAGE_URL_RE = re.compile(r"\.(png|jpe?g|gif|webp|svg|bmp)(\?|$)", re.I)
MAX_FIELDS = 14


class DraftError(Exception):
    """A draft that can't be used, with a message for the builder."""


# ---------------------------------------------------------------------------
# Drafts
# ---------------------------------------------------------------------------

def draft_plugin(plugin_id: str, manifest: Dict[str, Any],
                 settings: Optional[Dict[str, Optional[str]]] = None) -> pl.Plugin:
    """A Plugin object for a manifest from the builder (not written anywhere)."""
    plugin_id = (plugin_id or "").strip()
    if not pl.ID_RE.match(plugin_id):
        raise DraftError("The folder name can only use lowercase letters, digits and _ (More options, step 2)")
    plugin = pl.Plugin(id=plugin_id, path=pl.PLUGINS_DIR / plugin_id, kind="yaml", source="local")
    try:
        parsed = pl.Manifest.model_validate(manifest)
        pl._check_manifest(plugin, parsed)
    except ValidationError as e:
        raise DraftError(pl._validation_message(e)) from None
    except ValueError as e:
        raise DraftError(str(e)) from None
    plugin.manifest = parsed
    plugin.settings_override = {k: v for k, v in (settings or {}).items() if k in parsed.settings and v}
    return plugin


def to_yaml(manifest: Dict[str, Any]) -> str:
    """plugin.yaml text, fields in the README's order, empty parts left out."""
    order = ["name", "description", "icon", "site", "placeholder", "accepts", "cost", "cost_note", "speed",
             "concurrency", "timeout", "settings", "request", "request_by_type", "response", "requests"]
    unknown = [k for k in manifest if k not in order and k != "id"]
    clean = {k: _strip_empty(manifest[k]) for k in order + unknown if k in manifest}
    clean = {k: v for k, v in clean.items() if v not in (None, "", [], {})}
    for key, default in (("icon", "puzzle"), ("cost", "free"), ("speed", "fast"), ("concurrency", 2)):
        if clean.get(key) == default:
            clean.pop(key)
    body = yaml.safe_dump(clean, sort_keys=False, allow_unicode=True, default_flow_style=False, width=120)
    return "# Made with the plugin builder (Plugins page). Format: plugins/README.md\n" + body


def _strip_empty(value: Any) -> Any:
    if isinstance(value, dict):
        out = {k: _strip_empty(v) for k, v in value.items()}
        return {k: v for k, v in out.items() if v not in (None, "", [], {})}
    if isinstance(value, list):
        return [_strip_empty(v) for v in value]
    return value


async def test_draft(plugin_id: str, manifest: Dict[str, Any], value: str, kind: Optional[str],
                     settings: Dict[str, Optional[str]], detect_mapping: bool) -> Dict[str, Any]:
    """Send the draft's request. Returns {status, ok, format, raw, items, suggestion, error}."""
    plugin = draft_plugin(plugin_id, manifest, settings)
    assert plugin.manifest is not None
    secrets = plugin.secret_values()
    try:
        value, kind = pl._check_input(plugin, value, kind)
        missing = plugin.missing_settings()
        if missing:
            raise DraftError("Paste your API key first (step 4) - the service needs it")
        actions = plugin.actions(kind)
        if not actions:
            raise DraftError("Pick what you search with (step 3)")
        action = actions[0]   # the builder tries one lookup at a time
        response = await pl.send_request(plugin, value, kind, action.request)
    except pl.RunRefused as e:
        raise DraftError(e.detail) from None
    except PluginError as e:
        raise DraftError(pl.redact(str(e), secrets)) from None

    out: Dict[str, Any] = {"status": response.status_code, "url": pl.redact(str(response.request.url), secrets),
                           "content_type": response.headers.get("content-type", ""), "value": value, "type": kind}
    fmt = action.response.format
    try:
        data = pl.parse_response(response, fmt)
    except ValueError:
        fmt = "text"   # not JSON: read it as text
        data = pl.parse_response(response, fmt)
    out["format"] = fmt
    out["raw"] = pl.redact(data, secrets)
    if response.status_code in action.request.empty_status:
        out["note"] = f"HTTP {response.status_code}: counted as \"nothing found\". Try a value that exists."
    elif response.status_code >= 400:
        out["error"] = f"HTTP {response.status_code}: {pl._snippet(response.text)}"
    if detect_mapping and not out.get("error"):
        out["suggestion"] = suggest_mapping(data, fmt)
    if not out.get("error"):
        mapped = dict(manifest)
        if detect_mapping and out.get("suggestion"):
            mapped["response"] = out["suggestion"]
        mapped.setdefault("response", {})
        mapped["response"] = {**mapped["response"], "format": fmt}
        out["items"] = pl.redact(preview(plugin_id, mapped, data, value, kind), secrets)
    out["raw"] = pl._cap_raw(out["raw"])
    return out


def preview(plugin_id: str, manifest: Dict[str, Any], raw: Any, value: str, kind: str) -> List[Dict[str, Any]]:
    """Cards for a mapping, from an answer already fetched (no request)."""
    plugin = draft_plugin(plugin_id, manifest)
    return pl.build_items(plugin, raw, value or "", kind or "")


def save_draft(plugin_id: str, manifest: Optional[Dict[str, Any]], yaml_text: Optional[str],
               settings: Dict[str, Optional[str]], editing: bool) -> pl.Plugin:
    """Write plugins/<id>/plugin.yaml (from the form, or YAML typed in the builder)."""
    if yaml_text is not None:
        try:
            manifest = yaml.safe_load(yaml_text) or {}
        except yaml.YAMLError as e:
            raise DraftError(f"YAML: {e}") from None
        if not isinstance(manifest, dict):
            raise DraftError("YAML: expected name:, accepts: ... at the top level")
        manifest.pop("id", None)
    assert manifest is not None
    plugin = draft_plugin(plugin_id, manifest)
    folder = pl.PLUGINS_DIR / plugin.id
    existing = pl.refresh(force=True).get(plugin.id)
    if plugin.id in pl.RESERVED_IDS:
        raise DraftError(f"'{plugin.id}' is the name of a built-in module")
    if existing or folder.exists():
        if not editing:
            raise DraftError(f"There is already a plugin called '{plugin.id}' - change the name or the folder name (step 2)")
        if not existing or not can_edit(existing):
            raise DraftError("Only no-code plugins you made can be edited here - duplicate it instead")
    text = yaml_text if yaml_text is not None else to_yaml(manifest)
    written = yaml.safe_load(text) or {}
    written.pop("id", None)
    draft_plugin(plugin.id, written)   # what is written must load the same way
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "plugin.yaml").write_text(text, encoding="utf-8")
    pl.write_trust(plugin.id, "local")
    own: Dict[str, Optional[str]] = {k: v.strip() for k, v in (settings or {}).items()
           if v and v.strip() and k in manifest.get("settings", {}) and k.startswith(plugin.id.upper() + "_")}
    if own:
        update_env(own)
    saved = pl.refresh(force=True).get(plugin.id)
    if not saved:
        raise DraftError("Saved, but the plugin did not load - check plugins/" + plugin.id)
    return saved


def can_edit(plugin: pl.Plugin) -> bool:
    return plugin.editable


def delete_plugin(plugin: pl.Plugin) -> None:
    if not can_edit(plugin):
        raise DraftError("Only no-code plugins you made can be deleted here")
    folder = plugin.path.resolve()
    if folder.parent != pl.PLUGINS_DIR.resolve() or not (folder / "plugin.yaml").is_file():
        raise DraftError("Unexpected plugin folder")
    shutil.rmtree(folder)
    pl.write_trust(plugin.id, None)
    pl.refresh(force=True)


def load_for_builder(plugin: pl.Plugin) -> Dict[str, Any]:
    """An existing plugin's manifest for the builder (edit, or duplicate)."""
    try:
        text = (plugin.path / "plugin.yaml").read_text(encoding="utf-8")
        manifest = yaml.safe_load(text) or {}
    except (OSError, yaml.YAMLError) as e:
        raise DraftError(f"Can't read plugin.yaml: {e}") from None
    return {"id": plugin.id, "yaml": text, "manifest": manifest, "editable": can_edit(plugin),
            "settings": {k: {"configured": bool(plugin.setting(k))} for k in (manifest.get("settings") or {})}}


# ---------------------------------------------------------------------------
# curl import
# ---------------------------------------------------------------------------

def parse_curl(command: str, example: str = "") -> Dict[str, Any]:
    """A curl command (as copied from API docs or the browser) -> request parts.

    The API key moves into a setting ({key:API_KEY} - the builder names it), and the
    looked-up value (``example``, or an email/phone/domain/IP it finds) becomes {value}."""
    text = re.sub(r"\\\r?\n", " ", command or "").strip()
    try:
        tokens = shlex.split(text)
    except ValueError as e:
        raise DraftError(f"Couldn't read that example ({e}) - paste the whole command, starting with curl") from None
    if tokens and tokens[0].lower() in ("curl", "curl.exe"):
        tokens = tokens[1:]
    method, url, headers, data, is_json = None, None, {}, None, False
    takes_value = {"-o", "--output", "-m", "--max-time", "--connect-timeout", "-A", "--user-agent", "-e", "--referer",
                   "-b", "--cookie", "-x", "--proxy", "-w", "--write-out", "--retry"}
    i = 0
    while i < len(tokens):
        token = tokens[i]
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if token in ("-X", "--request") and nxt:
            method = nxt.upper(); i += 2; continue
        if token in ("-H", "--header") and nxt:
            name, _, val = nxt.partition(":")
            if name.strip():
                headers[name.strip()] = val.strip()
            i += 2; continue
        if token in ("-d", "--data", "--data-raw", "--data-binary", "--data-ascii", "--data-urlencode") and nxt:
            data = nxt if data is None else f"{data}&{nxt}"; i += 2; continue
        if token == "--json" and nxt:
            data, is_json = nxt, True; i += 2; continue
        if token in ("-u", "--user") and nxt:
            headers["Authorization"] = "Basic " + base64.b64encode(nxt.encode()).decode(); i += 2; continue
        if token in ("-A", "--user-agent") and nxt:
            headers["User-Agent"] = nxt; i += 2; continue
        if token in ("--url",) and nxt:
            url = nxt; i += 2; continue
        if token in takes_value:
            i += 2; continue
        if token.startswith("-"):
            i += 1; continue
        if url is None:
            url = token
        i += 1
    if not url:
        raise DraftError("No web address found - paste the whole example, starting with curl")
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    base_url = urlunsplit((parts.scheme, parts.netloc, parts.path or "/", "", ""))
    json_body, form = None, {}
    if data is not None:
        stripped = data.strip()
        if is_json or stripped.startswith(("{", "[")):
            try:
                json_body = json.loads(stripped)
            except json.JSONDecodeError:
                form = dict(parse_qsl(stripped, keep_blank_values=True))
        else:
            form = dict(parse_qsl(stripped, keep_blank_values=True))
    method = method or ("POST" if data is not None else "GET")
    if method not in ("GET", "POST"):
        raise DraftError(f"This example uses {method}, which plugins can't do - only GET and POST (searching)")
    headers = {k: v for k, v in headers.items() if k.lower() not in ("content-type", "content-length", "accept-encoding",
                                                                   "user-agent", "cookie", "host", "connection")}

    # API key -> setting
    secret_value = None

    def take_secret(name: str, val: str) -> str:
        nonlocal secret_value
        if not isinstance(val, str) or not val or not SECRET_NAME_RE.search(name):
            return val
        prefix = ""
        match = re.match(r"^(Bearer|Token|Basic|Bot|Key|ApiKey)\s+", val, re.I)
        if match:
            prefix, val = match.group(0), val[match.end():]
        if secret_value is None or secret_value == val:
            secret_value = val
            return prefix + "{key:API_KEY}"
        return prefix + val

    headers = {k: take_secret(k, v) for k, v in headers.items()}
    query = {k: take_secret(k, v) for k, v in query.items()}
    form = {k: take_secret(k, v) for k, v in form.items()}
    if isinstance(json_body, dict):
        json_body = {k: take_secret(k, v) for k, v in json_body.items()}

    # looked-up value -> {value}
    found: Optional[Tuple[str, str]] = None
    example = (example or "").strip()
    candidates: List[str] = [v for v in list(query.values()) + list(form.values()) if isinstance(v, str)]
    candidates += [seg for seg in parts.path.split("/") if seg]
    if isinstance(json_body, dict):
        candidates += [v for v in json_body.values() if isinstance(v, str)]
    if example:
        found = (example, (detect(example)[0].type if detect(example) else "text"))
    else:
        for candidate in candidates:
            if "{key:" in candidate:
                continue
            for entity in detect(candidate):
                if entity.type in ("email", "phone", "domain", "ip", "url", "crypto_btc", "crypto_eth") \
                        and candidate.strip() not in (parts.hostname or ""):
                    found = (candidate, entity.type)
                    break
            if found:
                break

    def put_value(val: Any) -> Any:
        if found and isinstance(val, str) and found[0] in val:
            return val.replace(found[0], "{value}")
        return val

    base_url = put_value(base_url) if found else base_url
    if found and "{" in urlsplit(base_url).netloc:
        base_url = urlunsplit((parts.scheme, parts.netloc, parts.path or "/", "", ""))   # never in the host
    query = {k: put_value(v) for k, v in query.items()}
    form = {k: put_value(v) for k, v in form.items()}
    if isinstance(json_body, dict):
        json_body = {k: put_value(v) for k, v in json_body.items()}
    warnings = []
    if not found:
        warnings.append("Couldn't spot the example value - in step 4, click where it belongs and press "
                        "\"+ what you search for\" (or type the example username next to the command and fill in again).")
    return {
        "request": {"method": method, "url": base_url, "query": query, "headers": headers,
                    "json": json_body, "form": form},
        "api_key": secret_value,
        "value": {"example": found[0], "type": found[1]} if found else None,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Response auto-detection
# ---------------------------------------------------------------------------

def _lists_of_objects(data: Any, path: str = "", depth: int = 0) -> List[Tuple[str, int, int]]:
    """(path, length, depth) of every list of objects in the answer."""
    found = []
    if depth > 5:
        return found
    if isinstance(data, list):
        if data and sum(isinstance(v, dict) for v in data[:20]) >= max(1, len(data[:20]) // 2):
            found.append((path or ".", len(data), depth))
    elif isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                found += _lists_of_objects(value, f"{path}.{key}" if path else str(key), depth + 1)
    return found


def _flatten(element: Any, prefix: str = "", depth: int = 0) -> Dict[str, Any]:
    """Paths of the simple values in one result: {"owner.login": "x", "tags": [...], "sources[].uri": [...]}."""
    out: Dict[str, Any] = {}
    if not isinstance(element, dict) or depth > 2:
        return out
    for key, value in element.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            out.update(_flatten(value, path, depth + 1))
        elif isinstance(value, list):
            if value and all(not isinstance(v, (dict, list)) for v in value):
                out[path] = value
            elif value and isinstance(value[0], dict) and depth < 2:
                for sub_key, sub_value in value[0].items():
                    if not isinstance(sub_value, (dict, list)):
                        out[f"{path}[].{sub_key}"] = [v.get(sub_key) for v in value if isinstance(v, dict)]
        else:
            out[path] = value
    return out


def _label(path: str) -> str:
    """"created_at" -> "Created at"; "accounts[].url" -> "Accounts url"."""
    parts = path.replace("[]", "").split(".")
    last = " ".join(parts[-2:]) if "[]" in path and len(parts) > 1 else parts[-1]
    words = re.sub(r"([a-z])([A-Z])", r"\1 \2", last).replace("_", " ").replace("-", " ").strip()
    return (words[:1].upper() + words[1:]) if words else path


def _is_url(value: Any) -> bool:
    return isinstance(value, str) and bool(re.match(r"^https?://", value))


def _is_api_url(value: Any) -> bool:
    """Links into the API itself (api.github.com/users/x/followers{/other}) - not for people."""
    if not _is_url(value):
        return False
    host = urlsplit(value).hostname or ""
    return host.startswith("api.") or "/api/" in value or "{" in value


def suggest_mapping(data: Any, fmt: str = "json") -> Dict[str, Any]:
    """A response: mapping for an answer: where the results are, title, link, picture,
    the rows to show and the identifiers in them."""
    if fmt == "text":
        lines = data.get("lines", [])[:20]
        return {"format": "text", "items": "lines", "title": "{.}", "fields": {},
                "entities": {t: "." for t in _guess_types(lines, domains=all(make_entity("domain", x) for x in lines))}}
    lists = _lists_of_objects(data)
    items_path: Optional[str] = None
    elements: List[Any]
    if lists:
        # the longest list, nearer the top on a tie
        items_path = sorted(lists, key=lambda x: (-x[1], x[2]))[0][0]
        listed = pl.get_path(data, items_path) if items_path != "." else data
        elements = [e for e in (listed or []) if isinstance(e, dict)][:20]
    else:
        elements = [data] if isinstance(data, dict) else []
    # a profile with a list inside (linked accounts...): the object itself is the result.
    # Search answers wrap their list in a few values (status, total, page) instead.
    if items_path and items_path != "." and isinstance(data, dict):
        top_values = [v for v in data.values() if v not in (None, "", [], {}) and not isinstance(v, (dict, list))]
        if len(top_values) >= 5:
            items_path, elements = None, [data]

    flat: Dict[str, Any] = {}
    for element in elements:
        for path, val in _flatten(element).items():
            if path not in flat or flat[path] in (None, "", []):
                flat[path] = val
    present = {p: v for p, v in flat.items() if v not in (None, "", [], False)}

    def pick(keys, exclude=(), check=lambda v: not isinstance(v, (list, dict)), suffixes=()):
        by_last = {}
        for path, val in present.items():
            by_last.setdefault(path.split(".")[-1].lower(), []).append((path, val))
        for key in keys:
            for path, val in sorted(by_last.get(key, []), key=lambda pv: pv[0].count(".")):
                if path not in exclude and check(val):
                    return path
        # "*_name" keys: nearer the top first, and an identifier (domain, email) before other text
        def identifier_first(pv):
            return pv[0].count("."), not any(make_entity(t, pv[1]) for t in ("domain", "email", "ip"))
        for path, val in sorted(present.items(), key=identifier_first):
            if path.split(".")[-1].lower().endswith(suffixes or ("\0",)) and path not in exclude and check(val):
                return path
        return None

    title = pick(TITLE_KEYS, suffixes=TITLE_SUFFIXES) or pick(("id",))
    subtitle = pick(SUBTITLE_KEYS, exclude=(title,),
                    check=lambda v: isinstance(v, str) and 0 < len(v) <= 120)
    image = next((p for p, v in present.items() if IMAGE_RE.search(p.split(".")[-1]) and _is_url(v)), None) \
        or next((p for p, v in present.items() if _is_url(v) and IMAGE_URL_RE.search(v)), None)
    url = pick(URL_KEYS, exclude=(image,), check=lambda v: _is_url(v) and not IMAGE_URL_RE.search(v) and not _is_api_url(v)) \
        or next((p for p, v in present.items() if _is_url(v) and p != image and not IMAGE_URL_RE.search(v)
                 and not _is_api_url(v)), None)

    skip = {title, image, url}
    fields: Dict[str, str] = {}
    for path, val in present.items():
        if path in skip or len(fields) >= MAX_FIELDS:
            continue
        last = path.split(".")[-1].lower()
        values = val if isinstance(val, list) else [val]
        if all(v in (None, "", False) for v in values) or (IMAGE_RE.search(last) and any(_is_url(v) for v in values)):
            continue
        if _is_api_url(val) or last in ("node_id", "gravatar_id", "etag", "hash") \
                or (isinstance(val, str) and len(val) > 400):
            continue
        label = _label(path)
        if label in fields:
            label = _label(path.replace(".", " "))
        template = f"{{{path}|date}}" if isinstance(val, str) and re.match(r"^\d{4}-\d\d-\d\dT", val) else path
        fields[label] = template

    entities: Dict[str, List[str]] = {}
    for path, val in present.items():
        values = val if isinstance(val, list) else [val]
        values = [v for v in values if isinstance(v, (str, int)) and not _is_api_url(v)][:10]
        if not values:
            continue
        kind = _key_hint(path.split(".")[-1].replace("[]", ""))
        if path == image:
            continue
        if kind and any(make_entity(kind, v) for v in values):
            entities.setdefault(kind, []).append(path)
            continue
        for guess in _guess_types(values, domains=bool(DOMAIN_KEY_RE.search(path.split(".")[-1]))):
            entities.setdefault(guess, []).append(path)
    mapping: Dict[str, Any] = {"format": "json"}
    if items_path:
        mapping["items"] = items_path
    for key, val in (("title", title), ("subtitle", subtitle), ("url", url), ("image", image)):
        if val:
            mapping[key] = val
    mapping["fields"] = fields
    mapping["entities"] = {t: (p[0] if len(p) == 1 else p[:5]) for t, p in entities.items() if t in ENTITY_TYPES}
    return mapping


def _guess_types(values: List[Any], domains: bool = False) -> List[str]:
    """Identifier types that unambiguous values are (emails, URLs, IPs, phones with +;
    domains only where the key says so - "Jane.Doe" would pass as one)."""
    types = []
    for v in values:
        text = str(v).strip()
        if domains and "domain" not in types and all(make_entity("domain", line.removeprefix("*."))
                                                       for line in text.splitlines() if line.strip()):
            types.append("domain")
        for kind in ("email", "url", "ip"):
            if kind not in types and make_entity(kind, text) and (kind != "url" or not IMAGE_URL_RE.search(text)):
                types.append(kind)
        if "phone" not in types and text.startswith("+") and make_entity("phone", text):
            types.append("phone")
    return types
