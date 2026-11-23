"""The loaded plugins: scanning plugins/, the Plugin object and its module in the registry."""
import importlib.util
import ipaddress
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from collections.abc import Callable
from urllib.parse import quote, urlsplit

import yaml
from pydantic import ValidationError

from services.entities import ENTITY_TYPES
from services.module_registry import MODULES, MODULES_BY_ID, Module, RunSpec
from utils.config import get_setting
from .constants import ICON_FILES, ID_RE, MASK, PLUGINS_DIR, RESERVED_IDS, RESOURCES_PATH, TRUST_FILE, _lock, logger
from .manifest import Manifest, RequestSpec, ResponseSpec, _check_manifest, _validation_message
from .trust import _files, _hash, _source, load_trust


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
    settings_override: Optional[dict[str, Optional[str]]] = None   # plugin builder drafts

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

    def requests(self) -> list[RequestSpec]:
        if not self.manifest:
            return []
        specs = [self.manifest.request, *self.manifest.request_by_type.values(), *(a.request for a in self.manifest.requests)]
        return [s for s in specs if s]

    def actions(self, kind: str) -> list["Action"]:
        """The lookups a no-code plugin runs for this input type."""
        m = self.manifest
        if not m:
            return []
        if m.requests:
            return [Action(a.id, a.name, a.request, a.response) for a in m.requests if kind in a.accepts]
        spec = m.request_by_type.get(kind) or m.request
        return [Action("lookup", m.name, spec, m.response)] if spec else []

    def hosts(self) -> list[str]:
        return sorted({urlsplit(s.url).hostname or "" for s in self.requests()} - {""})

    def foreign_keys(self) -> list[str]:
        prefix = self.id.upper() + "_"
        return [k for k in (self.manifest.settings if self.manifest else {}) if not k.startswith(prefix)]

    def settings_values(self) -> dict[str, Optional[str]]:
        return {k: self.setting(k) for k in (self.manifest.settings if self.manifest else {})}

    def secret_values(self) -> list[str]:
        if not self.manifest:
            return []
        values = [self.setting(k) for k, s in self.manifest.settings.items() if s.secret]
        return [v for v in values if v and len(v) >= 4]

    def missing_settings(self) -> list[str]:
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

    def warnings(self) -> list[str]:
        if self.trusted or not self.manifest or self.blocked():
            return []   # a blocked plugin already says why
        where = "changed since you reviewed it" if self.source == "changed" else "from another source and not reviewed"
        hosts = ", ".join(self.hosts()) or "the sites its code chooses"
        return [f"This plugin is {where}. What you look up with it is sent to {hosts}."]

    def public(self) -> dict[str, Any]:
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


_plugins: dict[str, Plugin] = {}

_state: dict[str, Any] = {"signature": None, "checked": 0.0}


def _folders() -> list[Path]:
    if not PLUGINS_DIR.is_dir():
        return []
    return sorted(p for p in PLUGINS_DIR.iterdir()
                  if p.is_dir() and not p.name.startswith((".", "_")) and (p / "plugin.yaml").is_file())


def _signature() -> tuple:
    entries = []
    for folder in _folders():
        for path in _files(folder):
            stat = path.stat()
            entries.append((str(path), stat.st_mtime_ns, stat.st_size))
    trust = TRUST_FILE.stat().st_mtime_ns if TRUST_FILE.exists() else 0
    resources = RESOURCES_PATH.stat().st_mtime_ns if RESOURCES_PATH.exists() else 0
    return tuple(entries), trust, resources


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


def _load(folder: Path, trust: dict[str, dict[str, Any]], previous: Optional[Plugin]) -> Plugin:
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


def refresh(force: bool = False) -> dict[str, Plugin]:
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


def plugin_files(plugin: Plugin) -> list[dict[str, Any]]:
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
