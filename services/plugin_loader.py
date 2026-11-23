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
# Each area is a module in services/pluginkit/; these are the names other code uses.
from services.pluginkit.client import client_script  # noqa: F401
from services.pluginkit.constants import ID_RE, PLUGINS_DIR, RESERVED_IDS  # noqa: F401
from services.pluginkit.manifest import Manifest, _check_manifest, _validation_message, builtin_setting_keys  # noqa: F401
from services.pluginkit.registry import Plugin, get, plugin_files, refresh, setting_keys  # noqa: F401
from services.pluginkit.results import _cap_raw, _snippet, redact  # noqa: F401
from services.pluginkit.runner import RunRefused, _check_input, events, parse_response, prepare, send_request  # noqa: F401
from services.pluginkit.templates import build_items, get_path  # noqa: F401
from services.pluginkit.trust import write_trust  # noqa: F401
