"""Plugins: modules users add in plugins/<id>/ (format: plugins/README.md).

Every plugin has a ``plugin.yaml``: name, what it looks up, its settings. A
no-code plugin also describes one HTTP request there and how to read the answer;
a Python plugin has a ``plugin.py`` with ``run(value, type, ctx)`` instead.
Optional files: ``renderer.js`` (custom result view), ``icon.png``.

Loaded plugins are added to ``module_registry.MODULES``, so the lookup box,
background jobs, pivot menus, readiness checks and settings pick them up. Runs
stream NDJSON events (started / item / data / error / done) which the
investigation decorator saves through ``reduce_plugin_stream``.

Trust: plugins shipped with the toolkit and ones you made (``python -m plugins
new``, or marked "mine" on the Plugins page) run as they are. Any other plugin is
"from another source": a no-code one still works but carries a warning, while
code (plugin.py, renderer.js), other modules' API keys and local network
addresses stay off until it is reviewed and enabled. Enabling is tied to the
files' hash, so a plugin that changes has to be enabled again.
"""
import asyncio
import dataclasses
import hashlib
import importlib.util
import inspect
import ipaddress
import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, AsyncIterator, Callable, Dict, List, Literal, Mapping, Optional, Tuple, Union
from urllib.parse import quote, urlsplit

import httpx
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from plugins.sdk import Context, Item, PluginError, Settings
from services.entities import ENTITY_TYPES, detect, make_entity
from services.module_registry import MODULES, MODULES_BY_ID, Module, RunSpec
from utils.config import get_setting

logger = logging.getLogger(__name__)

PLUGINS_DIR = Path("plugins")
TRUST_FILE = PLUGINS_DIR / ".trust.json"
RESOURCES_PATH = Path("resources.json")
BUNDLED = {"github_user", "crtsh", "gravatar"}   # shipped with the toolkit
ICON_FILES = ("icon.png", "icon.svg", "icon.webp", "icon.jpg")
USER_AGENT = "Mozilla/5.0 (compatible; OSINT-Toolkit plugin)"
MAX_ITEMS = 500
MAX_RAW_CHARS = 256 * 1024
MAX_FILES = 200
MASK = "••••"

ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
TEMPLATE_RE = re.compile(r"\{([^{}|\s]+)((?:\|[a-z0-9_]+)*)\}")
PATH_TOKEN_RE = re.compile(r"\[(-?\d*)\]|([^.\[\]]+)")
EMAIL_INPUT_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Built-in modules and the services their results are saved under
RESERVED_IDS = {m.id for m in MODULES} | {m.service for m in MODULES} | {
    "ns", "whois", "dns_recon", "username", "hlr", "gitfive", "vk_profile", "oi", "cavalier", "ghunt",
    "web_search", "data_search", "face_search", "sharetrace", "funstat", "ip", "phone",
    "sdk", "new", "reload", "client", "builder",
}

FILTERS: Dict[str, Callable[[str], str]] = {
    "lower": str.lower,
    "upper": str.upper,
    "trim": lambda s: s.strip().lstrip("@"),
    "md5": lambda s: hashlib.md5(s.encode()).hexdigest(),
    "sha1": lambda s: hashlib.sha1(s.encode()).hexdigest(),
    "sha256": lambda s: hashlib.sha256(s.encode()).hexdigest(),
    "urlencode": lambda s: quote(s, safe=""),
    "date": lambda s: s[:10],
}


# ---------------------------------------------------------------------------
# plugin.yaml
# ---------------------------------------------------------------------------

Scalar = Union[str, int, float, bool]


class SettingSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = ""
    secret: bool = False
    required: bool = True
    help: str = ""


class RequestSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    method: Literal["GET", "POST"] = "GET"
    url: str
    query: Dict[str, Scalar] = {}
    headers: Dict[str, Scalar] = {}
    json_body: Any = Field(None, alias="json")
    form: Dict[str, Scalar] = {}
    timeout: float = Field(30, ge=1, le=300)
    empty_status: List[int] = [404]

    @field_validator("url")
    @classmethod
    def literal_host(cls, url: str) -> str:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.netloc or "{" in parts.netloc:
            raise ValueError("url must start with http(s)://host/ and the host can't contain {placeholders}")
        return url


class ResponseSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["json", "text"] = "json"
    root: str = ""
    items: Optional[str] = None
    limit: int = Field(200, ge=1, le=MAX_ITEMS)
    unique: Optional[str] = None
    title: str = ""
    subtitle: str = ""
    url: str = ""
    image: str = ""
    site: str = ""
    category: str = ""
    fields: Optional[Dict[str, str]] = None
    entities: Dict[str, Union[str, List[str]]] = {}
    # Work the cards out from every answer (APIs whose answers change shape). What is
    # set above still wins: title, link...; fields and entities are added to the detected ones.
    auto: bool = False

    @field_validator("entities")
    @classmethod
    def known_types(cls, entities):
        unknown = [t for t in entities if t not in ENTITY_TYPES]
        if unknown:
            raise ValueError(f"unknown identifier type {', '.join(unknown)} (known: {', '.join(ENTITY_TYPES)})")
        return entities


class ActionSpec(BaseModel):
    """One of several lookups of a no-code plugin (requests:), e.g. Hunter's email
    verifier and domain search: each has its own inputs, request and cards."""
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    name: str = Field(min_length=1, max_length=80)
    accepts: List[str] = Field(min_length=1)
    request: RequestSpec
    response: ResponseSpec = Field(default_factory=lambda: ResponseSpec())

    @field_validator("accepts")
    @classmethod
    def known_accepts(cls, accepts):
        unknown = [t for t in accepts if t not in ENTITY_TYPES]
        if unknown:
            raise ValueError(f"unknown identifier type {', '.join(unknown)} (known: {', '.join(ENTITY_TYPES)})")
        return list(dict.fromkeys(accepts))


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Optional[str] = None
    name: str = Field(min_length=1, max_length=80)
    description: str = ""
    icon: str = Field("puzzle", pattern=r"^[a-z0-9-]{1,40}$")   # lucide icon name
    site: str = ""                                               # domain: card icon
    placeholder: str = ""
    cost: Literal["free", "paid"] = "free"
    cost_note: str = ""
    speed: Literal["fast", "medium", "slow"] = "fast"
    concurrency: int = Field(2, ge=1, le=5)
    timeout: float = Field(120, ge=5, le=1800)                   # Python plugins: the whole run
    accepts: List[str] = []              # with requests: defaults to what its lookups accept
    settings: Dict[str, SettingSpec] = {}
    request: Optional[RequestSpec] = None
    request_by_type: Dict[str, RequestSpec] = {}
    response: ResponseSpec = Field(default_factory=lambda: ResponseSpec())
    requests: List[ActionSpec] = []      # several lookups instead of request:/response:

    @field_validator("accepts")
    @classmethod
    def known_accepts(cls, accepts):
        unknown = [t for t in accepts if t not in ENTITY_TYPES]
        if unknown:
            raise ValueError(f"unknown identifier type {', '.join(unknown)} (known: {', '.join(ENTITY_TYPES)})")
        return list(dict.fromkeys(accepts))

    @field_validator("settings")
    @classmethod
    def setting_names(cls, settings):
        bad = [k for k in settings if not KEY_RE.match(k)]
        if bad:
            raise ValueError(f"setting names must be UPPER_CASE: {', '.join(bad)}")
        return settings

    @model_validator(mode="after")
    def by_type_accepted(self):
        if self.requests:
            if self.request or self.request_by_type:
                raise ValueError("use either request: (one lookup) or requests: (several), not both")
            ids = [a.id for a in self.requests]
            if len(set(ids)) != len(ids):
                raise ValueError("every lookup in requests: needs a different id")
            self.accepts = list(dict.fromkeys(self.accepts + [t for a in self.requests for t in a.accepts]))
        if not self.accepts:
            raise ValueError("accepts: what the plugin looks up (email, username, domain, ...)")
        extra = [t for t in self.request_by_type if t not in self.accepts]
        if extra:
            raise ValueError(f"request_by_type has {', '.join(extra)}, which is not in accepts")
        return self


def _validation_message(error: ValidationError) -> str:
    parts = []
    for e in error.errors()[:4]:
        where = ".".join(str(p) for p in e.get("loc", ()))
        msg = str(e.get("msg") or "").removeprefix("Value error, ")
        parts.append(f"{where}: {msg}" if where else msg)
    return "; ".join(parts)


def builtin_setting_keys() -> set:
    """API keys / paths of the built-in modules (resources.json)."""
    try:
        modules = json.loads(RESOURCES_PATH.read_text()).get("modules", [])
    except (OSError, json.JSONDecodeError):
        return set()
    return {key.upper() for module in modules for key in (module.get("settings") or {})}


def _templates(manifest: Manifest) -> Tuple[List[str], List[str]]:
    """(request templates, response templates) for checking placeholders."""
    request, response = [], []
    specs = [manifest.request, *manifest.request_by_type.values(), *(a.request for a in manifest.requests)]
    for spec in specs:
        if not spec:
            continue
        request.append(spec.url)
        request += [str(v) for part in (spec.query, spec.headers, spec.form) for v in part.values()]
        request += [s for s in _strings(spec.json_body)]
    for r in [manifest.response, *(a.response for a in manifest.requests)]:
        response += [r.title, r.subtitle, r.url, r.image, r.site, r.category]
        response += [v for v in (r.fields or {}).values() if "{" in v]
    return request, response


def _strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def _check_manifest(plugin: "Plugin", manifest: Manifest) -> None:
    if plugin.kind == "python" and (manifest.request or manifest.request_by_type or manifest.requests):
        raise ValueError("has both plugin.py and a request: section - use one of them")
    if plugin.kind == "yaml" and not manifest.request and not manifest.requests \
            and set(manifest.accepts) - set(manifest.request_by_type):
        raise ValueError("needs a request: section (no-code plugin) or a plugin.py (Python plugin)")
    prefix = plugin.id.upper() + "_"
    builtin = builtin_setting_keys()
    for key in manifest.settings:
        if not key.startswith(prefix) and key not in builtin:
            raise ValueError(f"setting {key} must start with {prefix} (or be the key of a built-in module)")
    request, response = _templates(manifest)
    for text in request + response:
        for name, filters in TEMPLATE_RE.findall(text):
            unknown = [f for f in filters.split("|") if f and f not in FILTERS]
            if unknown:
                raise ValueError(f"unknown filter |{unknown[0]} in {text!r} (known: {', '.join(FILTERS)})")
    for text in request:
        for name, _ in TEMPLATE_RE.findall(text):
            if name in ("value", "type"):
                continue
            if name.startswith("settings.") and name[9:] in manifest.settings:
                continue
            raise ValueError(f"{{{name}}} in {text!r}: requests can use {{value}}, {{type}} and "
                             f"{{settings.NAME}} for settings declared in settings:")


# ---------------------------------------------------------------------------
# Loaded plugins
# ---------------------------------------------------------------------------

def _is_private_host(host: str) -> bool:
    host = (host or "").lower().strip("[]")
    if host == "localhost" or host.endswith((".local", ".localhost", ".internal", ".lan")):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved


@dataclass
class Plugin:
    id: str
    path: Path
    manifest: Optional[Manifest] = None
    kind: str = "yaml"               # "yaml" (no-code) or "python"
    sha: str = ""
    source: str = "unreviewed"       # bundled / local / approved / changed / unreviewed
    error: Optional[str] = None
    run: Optional[Callable] = None
    has_renderer: bool = False
    icon_file: Optional[Path] = None
    settings_override: Optional[Dict[str, Optional[str]]] = None   # plugin builder drafts

    def setting(self, key: str) -> Optional[str]:
        if self.settings_override is not None and self.settings_override.get(key):
            return self.settings_override[key]
        return get_setting(key)

    @property
    def name(self) -> str:
        return self.manifest.name if self.manifest else self.id

    @property
    def trusted(self) -> bool:
        return self.source in ("bundled", "local", "approved")

    @property
    def log(self) -> logging.Logger:
        log = logging.getLogger(f"plugins.{self.id}")
        if not any(isinstance(f, _RedactFilter) for f in log.filters):
            log.addFilter(_RedactFilter(self.id))
        return log

    @property
    def editable(self) -> bool:
        """The plugin builder edits (and deletes) no-code plugins you made."""
        return self.kind == "yaml" and self.source == "local" and not self.has_renderer

    @property
    def icon_url(self) -> str:
        if self.icon_file:
            return f"/api/plugins/{self.id}/icon"
        site = self.manifest.site if self.manifest else ""
        return f"/api/oi/icon/{quote(site)}" if site else ""

    def requests(self) -> List[RequestSpec]:
        if not self.manifest:
            return []
        specs = [self.manifest.request, *self.manifest.request_by_type.values(), *(a.request for a in self.manifest.requests)]
        return [s for s in specs if s]

    def actions(self, kind: str) -> List["Action"]:
        """The lookups a no-code plugin runs for this input type."""
        m = self.manifest
        if not m:
            return []
        if m.requests:
            return [Action(a.id, a.name, a.request, a.response) for a in m.requests if kind in a.accepts]
        spec = m.request_by_type.get(kind) or m.request
        return [Action("lookup", m.name, spec, m.response)] if spec else []

    def hosts(self) -> List[str]:
        return sorted({urlsplit(s.url).hostname or "" for s in self.requests()} - {""})

    def foreign_keys(self) -> List[str]:
        prefix = self.id.upper() + "_"
        return [k for k in (self.manifest.settings if self.manifest else {}) if not k.startswith(prefix)]

    def settings_values(self) -> Dict[str, Optional[str]]:
        return {k: self.setting(k) for k in (self.manifest.settings if self.manifest else {})}

    def secret_values(self) -> List[str]:
        if not self.manifest:
            return []
        values = [self.setting(k) for k, s in self.manifest.settings.items() if s.secret]
        return [v for v in values if v and len(v) >= 4]

    def missing_settings(self) -> List[str]:
        if not self.manifest:
            return []
        return [k for k, s in self.manifest.settings.items() if s.required and not self.setting(k)]

    def blocked(self) -> Optional[str]:
        """Why the plugin can't run until it is reviewed (None if it can)."""
        if self.error:
            return self.error
        if self.trusted:
            return None
        reasons = []
        if self.kind == "python":
            reasons.append("runs Python code")
        if self.has_renderer:
            reasons.append("adds JavaScript to the pages")
        if self.foreign_keys():
            reasons.append(f"reads other modules' settings ({', '.join(self.foreign_keys())})")
        private = [h for h in self.hosts() if _is_private_host(h)]
        if private:
            reasons.append(f"connects to a local network address ({', '.join(private)})")
        if not reasons:
            return None
        where = "Changed since you enabled it" if self.source == "changed" else "From another source"
        return f"{where}: {', '.join(reasons)}. Review and enable it on the Plugins page."

    def warnings(self) -> List[str]:
        if self.trusted or not self.manifest or self.blocked():
            return []   # a blocked plugin already says why
        where = "changed since you reviewed it" if self.source == "changed" else "from another source and not reviewed"
        hosts = ", ".join(self.hosts()) or "the sites its code chooses"
        return [f"This plugin is {where}. What you look up with it is sent to {hosts}."]

    def public(self) -> Dict[str, Any]:
        m = self.manifest
        blocked = self.blocked()
        return {
            "id": self.id,
            "name": self.name,
            "description": m.description if m else "",
            "icon": m.icon if m else "puzzle",
            "icon_url": self.icon_url,
            "site": m.site if m else "",
            "placeholder": m.placeholder if m else "",
            "kind": self.kind,
            "source": self.source,
            "trusted": self.trusted,
            "enabled": bool(m) and not blocked,
            "error": self.error,
            "blocked": blocked,
            "warnings": self.warnings(),
            "accepts": [{"type": t, "label": ENTITY_TYPES[t]} for t in (m.accepts if m else [])],
            "cost": m.cost if m else "free",
            "cost_note": m.cost_note if m else "",
            "speed": m.speed if m else "fast",
            "hosts": self.hosts(),
            "page": f"/plugins/{self.id}",
            "folder": str(self.path),
            "has_renderer": self.has_renderer,
            "editable": self.editable,
            "actions": [{"id": a.id, "name": a.name, "accepts": a.accepts} for a in (m.requests if m else [])],
            "missing_settings": self.missing_settings(),
            "settings": [{
                "key": k, "label": s.label or k, "secret": s.secret, "required": s.required, "help": s.help,
                "own": k.startswith(self.id.upper() + "_"), "configured": bool(get_setting(k)),
            } for k, s in (m.settings if m else {}).items()],
        }


@dataclass
class Action:
    id: str
    name: str
    request: RequestSpec
    response: ResponseSpec


class _RedactFilter(logging.Filter):
    """Mask the plugin's secret settings in anything it logs."""

    def __init__(self, plugin_id: str):
        super().__init__()
        self.plugin_id = plugin_id

    def filter(self, record: logging.LogRecord) -> bool:
        plugin = _plugins.get(self.plugin_id)
        secrets = plugin.secret_values() if plugin else []
        if secrets:
            message = record.getMessage()
            for secret in secrets:
                message = message.replace(secret, MASK)
            record.msg, record.args = message, ()
        return True


_plugins: Dict[str, Plugin] = {}
_state: Dict[str, Any] = {"signature": None, "checked": 0.0}
_lock = threading.RLock()


def _folders() -> List[Path]:
    if not PLUGINS_DIR.is_dir():
        return []
    return sorted(p for p in PLUGINS_DIR.iterdir()
                  if p.is_dir() and not p.name.startswith((".", "_")) and (p / "plugin.yaml").is_file())


def _files(folder: Path) -> List[Path]:
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


def _signature() -> tuple:
    entries = []
    for folder in _folders():
        for path in _files(folder):
            stat = path.stat()
            entries.append((str(path), stat.st_mtime_ns, stat.st_size))
    trust = TRUST_FILE.stat().st_mtime_ns if TRUST_FILE.exists() else 0
    resources = RESOURCES_PATH.stat().st_mtime_ns if RESOURCES_PATH.exists() else 0
    return tuple(entries), trust, resources


def load_trust() -> Dict[str, Dict[str, Any]]:
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


def _source(plugin_id: str, sha: str, trust: Dict[str, Dict[str, Any]]) -> str:
    entry = trust.get(plugin_id) or {}
    if entry.get("mode") == "local":
        return "local"
    if entry.get("mode") == "approved":
        return "approved" if entry.get("sha") == sha else "changed"
    return "bundled" if plugin_id in BUNDLED else "unreviewed"


def _import_run(plugin: Plugin) -> Optional[Callable]:
    path = plugin.path / "plugin.py"
    try:
        spec = importlib.util.spec_from_file_location(f"osint_plugin_{plugin.id}", path)
        if not spec or not spec.loader:
            raise ImportError("cannot load plugin.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as e:
        logger.warning("Plugin %s: plugin.py failed to load", plugin.id, exc_info=True)
        plugin.error = f"plugin.py failed to load: {e.__class__.__name__}: {e}"
        return None
    run = getattr(module, "run", None)
    if not callable(run):
        plugin.error = "plugin.py has no run(value, type, ctx) function"
        return None
    return run


def _load(folder: Path, trust: Dict[str, Dict[str, Any]], previous: Optional[Plugin]) -> Plugin:
    plugin = Plugin(id=folder.name, path=folder)
    plugin.kind = "python" if (folder / "plugin.py").is_file() else "yaml"
    plugin.has_renderer = (folder / "renderer.js").is_file()
    plugin.icon_file = next((folder / n for n in ICON_FILES if (folder / n).is_file()), None)
    try:
        plugin.sha = _hash(folder)
    except OSError as e:
        plugin.error = f"cannot read the plugin's files: {e}"
        return plugin
    plugin.source = _source(plugin.id, plugin.sha, trust)
    if not ID_RE.match(plugin.id):
        plugin.error = "the folder name is the plugin id: use lowercase letters, digits and _ (2-40 characters)"
        return plugin
    if plugin.id in RESERVED_IDS:
        plugin.error = f"'{plugin.id}' is the name of a built-in module - rename the folder"
        return plugin
    try:
        data = yaml.safe_load((folder / "plugin.yaml").read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError("expected name:, accepts: ... at the top level")
        manifest = Manifest.model_validate(data)
        if manifest.id and manifest.id != plugin.id:
            raise ValueError(f"id '{manifest.id}' doesn't match the folder name '{plugin.id}'")
        _check_manifest(plugin, manifest)
        plugin.manifest = manifest
    except ValidationError as e:
        plugin.error = f"plugin.yaml: {_validation_message(e)}"
    except (yaml.YAMLError, ValueError, OSError) as e:
        plugin.error = f"plugin.yaml: {e}"
    if plugin.manifest and plugin.kind == "python" and plugin.blocked() is None:
        if previous and previous.sha == plugin.sha and previous.run:
            plugin.run = previous.run
        else:
            plugin.run = _import_run(plugin)
    return plugin


def _module(plugin: Plugin) -> Module:
    m = plugin.manifest
    assert m is not None
    accepts = {
        t: RunSpec("POST", f"/api/plugins/{plugin.id}/run",
                   (lambda kind: lambda v: {"json": {"value": v, "type": kind}})(t), stream=True)
        for t in m.accepts
    }
    return Module(
        plugin.id, m.name, f"/plugins/{plugin.id}", m.icon, accepts,
        cost=m.cost, cost_note=m.cost_note, speed=m.speed, concurrency=m.concurrency,
        keys=[k for k, s in m.settings.items() if s.required],
        optional_keys=[k for k, s in m.settings.items() if not s.required],
        prefill={"input": "#pluginInput", "type_select": "#pluginType"},
        service=plugin.id, plugin=True,
        extra_problems=lambda: [b for b in [plugin.blocked()] if b],
    )


def _register() -> None:
    plugin_modules = [_module(p) for p in _plugins.values() if p.manifest]
    MODULES[:] = [m for m in MODULES if not m.plugin] + plugin_modules
    MODULES_BY_ID.clear()
    MODULES_BY_ID.update({m.id: m for m in MODULES})


def refresh(force: bool = False) -> Dict[str, Plugin]:
    """Rescan plugins/ when its files (or the trust list) changed; cheap to call often."""
    now = time.monotonic()
    if not force and now - _state["checked"] < 1.0:
        return _plugins
    with _lock:
        _state["checked"] = now
        signature = _signature()
        if not force and signature == _state["signature"]:
            return _plugins
        _state["signature"] = signature
        trust = load_trust()
        loaded = {}
        for folder in _folders():
            plugin = _load(folder, trust, _plugins.get(folder.name))
            loaded[plugin.id] = plugin
            if plugin.error:
                logger.warning("Plugin %s: %s", plugin.id, plugin.error)
        _plugins.clear()
        _plugins.update(loaded)
        _register()
        logger.info("Plugins: %d loaded (%s)", len(_plugins), ", ".join(_plugins) or "none")
    return _plugins


def get(plugin_id: str) -> Optional[Plugin]:
    return refresh().get(plugin_id)


def plugin_files(plugin: Plugin) -> List[Dict[str, Any]]:
    """The plugin's files for review (text files with their content)."""
    out = []
    for path in _files(plugin.path):
        rel = path.relative_to(plugin.path).as_posix()
        size = path.stat().st_size
        text = None
        if size <= 256 * 1024:
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                text = None
        out.append({"path": rel, "size": size, "text": text})
    return out


def setting_keys() -> set:
    """Plugin settings editable on the settings page (only a plugin's own keys)."""
    keys = set()
    for plugin in refresh().values():
        foreign = set(plugin.foreign_keys())
        keys.update(k for k in (plugin.manifest.settings if plugin.manifest else {}) if k not in foreign)
    return keys


# ---------------------------------------------------------------------------
# Paths and templates (no-code plugins)
# ---------------------------------------------------------------------------

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


def _auto_fields(row: Any) -> List[Tuple[str, Any]]:
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
    entities: Dict[str, List[str]] = {}
    for source in (detected.get("entities") or {}, spec.entities):
        for etype, paths in source.items():
            for path in paths if isinstance(paths, list) else [paths]:
                if path not in entities.setdefault(etype, []):
                    entities[etype].append(path)
    merged["entities"] = entities
    return ResponseSpec.model_validate(merged)


def build_items(plugin: Plugin, data: Any, value: str, kind: str,
                spec: Optional[ResponseSpec] = None) -> List[Dict[str, Any]]:
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


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

ITEM_KEYS = {f.name for f in dataclasses.fields(Item)}


def _flatten(values: Any) -> List[Any]:
    if isinstance(values, (list, tuple)):
        return [v for value in values for v in _flatten(value)]
    return [values]


def normalize_item(obj: Union[Item, Mapping[str, Any]], plugin: Plugin) -> Dict[str, Any]:
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
    entities: Dict[str, List[str]] = {}
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


def split_output(result: Any, plugin: Plugin) -> Tuple[List[Dict[str, Any]], Any]:
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


def redact(value: Any, secrets: List[str]) -> Any:
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


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------

class RunRefused(Exception):
    """The run can't start (unknown plugin, bad input, not set up)."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


@dataclass
class PreparedRun:
    plugin: Plugin
    value: str
    type: str
    items: List[Dict[str, Any]] = dataclasses.field(default_factory=list)
    data: Any = None
    raw: Any = None
    note: Optional[str] = None
    stream: Optional[AsyncGenerator[Tuple[str, Any], None]] = None
    actions: Optional[List[str]] = None    # only these lookups (requests: plugins)
    warnings: List[str] = dataclasses.field(default_factory=list)
    lookups: List[Dict[str, Any]] = dataclasses.field(default_factory=list)   # what each of several did


def _check_input(plugin: Plugin, value: str, kind: Optional[str]) -> Tuple[str, str]:
    assert plugin.manifest is not None
    accepts = plugin.manifest.accepts
    value = (value or "").strip()
    if not value:
        raise RunRefused(400, "Enter something to look up")
    if not kind:
        if len(accepts) == 1:
            kind = accepts[0]
        else:
            kind = next((e.type for e in detect(value) if e.type in accepts), None)
            if not kind:
                raise RunRefused(400, f"Choose what '{value}' is: {', '.join(ENTITY_TYPES[t] for t in accepts)}")
    if kind not in accepts:
        raise RunRefused(400, f"{plugin.name} doesn't look up {ENTITY_TYPES.get(kind, kind)}")
    entity = make_entity(kind, value)
    if entity:
        value = entity.value
    # Normalizing also drops "noise" (example.org, private IPs) meant for result
    # extraction - typed input only has to look right
    elif ((kind == "email" and not EMAIL_INPUT_RE.match(value)) or (kind == "phone" and not re.search(r"\d{5}", value))
          or (kind not in ("text", "phone") and re.search(r"\s", value))):
        raise RunRefused(400, f"'{value}' doesn't look like {ENTITY_TYPES[kind].lower()}")
    return value, kind


def _client(plugin: Plugin, timeout: float) -> httpx.AsyncClient:
    hosts = set(plugin.hosts())

    async def same_hosts(request: httpx.Request):
        # Plugins that aren't reviewed may only talk to the hosts in their manifest (redirects too)
        if request.url.host not in hosts:
            raise PluginError(f"Blocked a request to {request.url.host}: only {', '.join(sorted(hosts))} "
                              "is allowed until the plugin is reviewed")

    hooks = {"request": [same_hosts]} if plugin.kind == "yaml" and not plugin.trusted else {}
    return httpx.AsyncClient(timeout=httpx.Timeout(timeout), follow_redirects=True,
                             headers={"User-Agent": USER_AGENT}, event_hooks=hooks)


async def send_request(plugin: Plugin, value: str, kind: str, spec: RequestSpec) -> httpx.Response:
    """Render and send one of a no-code plugin's requests (also used by the plugin builder)."""
    settings = plugin.settings_values()

    def request_lookup(empty: List[str]) -> Callable[[str], Any]:
        def lookup(name: str) -> Any:
            if name == "value":
                return value
            if name == "type":
                return kind
            setting = settings.get(name[9:]) or ""
            if not setting:
                empty.append(name[9:])
            return setting
        return lookup

    def render_map(entries: Dict[str, Scalar]) -> Dict[str, str]:
        out = {}
        for key, template in entries.items():
            empty: List[str] = []
            text = render(str(template).lower() if isinstance(template, bool) else str(template), request_lookup(empty))
            if not empty:   # entries using an unset optional setting are left out
                out[key] = text
        return out

    def render_json(body: Any) -> Any:
        if isinstance(body, str):
            return render(body, request_lookup([]))
        if isinstance(body, dict):
            return {k: render_json(v) for k, v in body.items()}
        if isinstance(body, list):
            return [render_json(v) for v in body]
        return body

    empty: List[str] = []
    url = render(spec.url, request_lookup(empty), quote_values=True)
    if empty:
        raise RunRefused(400, f"{empty[0]} is not set - add it in Settings")
    host = urlsplit(url).hostname or url
    kwargs: Dict[str, Any] = {"params": render_map(spec.query), "headers": render_map(spec.headers)}
    if spec.json_body is not None:
        kwargs["json"] = render_json(spec.json_body)
    elif spec.form:
        kwargs["data"] = render_map(spec.form)
    try:
        async with _client(plugin, spec.timeout) as client:
            return await client.request(spec.method, url, **kwargs)
    except httpx.TimeoutException:
        raise PluginError(f"{host} did not answer within {spec.timeout:g} s") from None
    except httpx.HTTPError as e:
        raise PluginError(f"Request to {host} failed: {e.__class__.__name__}: {e}") from e


def parse_response(response: httpx.Response, format: str) -> Any:
    """JSON answer, or {text, lines} for format: text. Raises ValueError for bad JSON."""
    if format == "json":
        return response.json()
    text = response.text
    return {"text": text, "lines": [line.strip() for line in text.splitlines() if line.strip()]}


async def _run_action(plugin: Plugin, action: Action, value: str, kind: str) -> Tuple[List[Dict[str, Any]], Any]:
    """One lookup: (cards, answer). Cards are [] when the answer means "nothing found"."""
    response = await send_request(plugin, value, kind, action.request)
    host = response.request.url.host
    if response.status_code in action.request.empty_status:
        return [], None
    if response.status_code >= 400:
        raise PluginError(f"{host} answered HTTP {response.status_code}: {_snippet(response.text)}")
    try:
        data = parse_response(response, action.response.format)
    except ValueError:
        raise PluginError(f"{host} did not answer with JSON: {_snippet(response.text)}") from None
    return build_items(plugin, data, value, kind, action.response), data


async def _run_yaml(run: PreparedRun) -> None:
    """Run the lookups for the input type at the same time. With several, one failing
    is a warning next to the others' cards; all failing is an error."""
    plugin = run.plugin
    actions = plugin.actions(run.type)
    if run.actions:
        actions = [a for a in actions if a.id in run.actions] or actions
    if len(actions) == 1:
        run.items, run.raw = await _run_action(plugin, actions[0], run.value, run.type)
        if plugin.manifest and plugin.manifest.requests:   # say which lookup found them
            for item in run.items:
                item["action"] = actions[0].name
        if run.raw is None:
            run.note = "Nothing found"
        return
    results = await asyncio.gather(*(_run_action(plugin, a, run.value, run.type) for a in actions),
                                   return_exceptions=True)
    errors, raw = [], {}
    for action, result in zip(actions, results):
        if isinstance(result, BaseException):
            if not isinstance(result, (PluginError, RunRefused)):
                logger.warning("Plugin %s, %s failed", plugin.id, action.id, exc_info=result)
            errors.append(f"{action.name}: {getattr(result, 'detail', None) or result}")
            run.lookups.append({"name": action.name, "status": "failed"})
            continue
        items, data = result
        for item in items:
            item["action"] = action.name
        run.items += items
        raw[action.id] = data
        run.lookups.append({"name": action.name, "status": "found" if items else "nothing", "count": len(items)})
    if len(errors) == len(actions):
        raise PluginError("; ".join(errors))
    run.warnings = errors
    run.raw = raw

def _plugin_failure(plugin: Plugin, e: BaseException) -> PluginError:
    if isinstance(e, PluginError):
        return e
    if isinstance(e, httpx.TimeoutException):
        return PluginError(f"A request timed out ({e.request.url.host if e.request else 'unknown host'})")
    if isinstance(e, httpx.HTTPStatusError):
        return PluginError(f"{e.request.url.host} answered HTTP {e.response.status_code}: {_snippet(e.response.text)}")
    if isinstance(e, httpx.HTTPError):
        return PluginError(f"Request failed: {e.__class__.__name__}: {e}")
    logger.error("Plugin %s failed", plugin.id, exc_info=e)
    return PluginError(f"plugin.py failed: {e.__class__.__name__}: {e}")


async def _python_stream(plugin: Plugin, agen, client: httpx.AsyncClient, timeout: float):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    try:
        while True:
            try:
                out = await asyncio.wait_for(agen.__anext__(), max(deadline - loop.time(), 0.01))
            except StopAsyncIteration:
                break
            except asyncio.TimeoutError:
                raise PluginError(f"Stopped after {timeout:g} s (timeout: in plugin.yaml)") from None
            except Exception as e:
                raise _plugin_failure(plugin, e) from e
            items, data = split_output(out, plugin)
            for item in items:
                yield "item", item
            if data is not None:
                yield "data", data
    finally:
        try:
            await agen.aclose()
        finally:
            await client.aclose()


async def _run_python(run: PreparedRun) -> None:
    plugin = run.plugin
    assert plugin.manifest is not None and plugin.run is not None
    timeout = plugin.manifest.timeout
    client = httpx.AsyncClient(timeout=httpx.Timeout(30), follow_redirects=True, headers={"User-Agent": USER_AGENT})
    ctx = Context(plugin.id, run.value, run.type, Settings(plugin.settings_values()), client, plugin.log)
    if inspect.isasyncgenfunction(plugin.run):
        run.stream = _python_stream(plugin, plugin.run(run.value, run.type, ctx), client, timeout)
        return
    try:
        if inspect.iscoroutinefunction(plugin.run):
            result = await asyncio.wait_for(plugin.run(run.value, run.type, ctx), timeout)
        else:
            result = await asyncio.wait_for(asyncio.to_thread(plugin.run, run.value, run.type, ctx), timeout)
    except asyncio.TimeoutError:
        raise PluginError(f"Stopped after {timeout:g} s (timeout: in plugin.yaml)") from None
    except Exception as e:
        raise _plugin_failure(plugin, e) from e
    finally:
        await client.aclose()
    run.items, run.data = split_output(result, plugin)


async def prepare(plugin_id: str, value: str, kind: Optional[str],
                  actions: Optional[List[str]] = None) -> PreparedRun:
    """Check the input and run the lookup (async-generator plugins start streaming
    later). Raises RunRefused, or PluginError when the lookup itself failed."""
    plugin = get(plugin_id)
    if not plugin or not plugin.manifest:
        raise RunRefused(404, plugin.error if plugin and plugin.error else f"No plugin '{plugin_id}'")
    blocked = plugin.blocked()
    if blocked:
        raise RunRefused(403, blocked)
    value, kind = _check_input(plugin, value, kind)
    missing = plugin.missing_settings()
    if missing:
        raise RunRefused(400, f"{', '.join(missing)} {'is' if len(missing) == 1 else 'are'} not set - add it in Settings")
    run = PreparedRun(plugin, value, kind, actions=actions or None)
    try:
        if plugin.kind == "python":
            await _run_python(run)
        else:
            await _run_yaml(run)
    except PluginError as e:
        raise PluginError(redact(str(e), plugin.secret_values())) from None
    return run


async def events(run: PreparedRun) -> AsyncIterator[str]:
    """NDJSON lines: started, item..., data, error, done."""
    plugin = run.plugin
    secrets = plugin.secret_values()

    def line(event: Dict[str, Any]) -> str:
        return json.dumps(redact(event, secrets), ensure_ascii=False, default=str) + "\n"

    yield line({"event": "started", "plugin": plugin.id, "name": plugin.name, "value": run.value, "type": run.type})
    count = len(run.items)
    for item in run.items:
        yield line({"event": "item", "item": item})
    has_data = run.data is not None
    if has_data:
        yield line({"event": "data", "data": run.data})
    for warning in run.warnings:
        yield line({"event": "warning", "detail": warning})
    error = None
    if run.stream is not None:
        try:
            async for kind, payload in run.stream:
                count += kind == "item"
                has_data = has_data or kind == "data"
                yield line({"event": kind, kind: payload})
        except PluginError as e:
            error = str(e)
        finally:
            await run.stream.aclose()
        if error:
            yield line({"event": "error", "detail": error})
    note = run.note or ("Nothing found" if not count and not has_data and not error else None)
    yield line({"event": "done", "count": count, "completed": error is None, "note": note,
                "lookups": run.lookups or None, "raw": _cap_raw(run.raw)})


def client_script() -> str:
    """JS for every page: plugin names/icons for saved results, plus the custom
    renderers of plugins allowed to run code."""
    plugins = [p for p in refresh().values() if p.manifest]
    meta = [{"id": p.id, "name": p.name, "icon": p.manifest.icon if p.manifest else "puzzle",
             "page": f"/plugins/{p.id}", "icon_url": p.icon_url} for p in plugins]
    parts = [f"registerPlugins({json.dumps(meta, ensure_ascii=False)});"]
    for plugin in plugins:
        if not plugin.has_renderer or plugin.blocked():
            continue
        try:
            code = (plugin.path / "renderer.js").read_text(encoding="utf-8")
        except OSError:
            continue
        parts.append(
            f"/* plugin {plugin.id}: renderer.js */\n"
            f"try {{ (function (pluginId) {{\n{code}\n}})({json.dumps(plugin.id)}); }}\n"
            f"catch (e) {{ console.error({json.dumps(f'Plugin {plugin.id}: renderer.js failed')}, e); }}"
        )
    return "\n\n".join(parts) + "\n"
