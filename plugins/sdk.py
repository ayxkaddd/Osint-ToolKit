"""What a Python plugin's ``plugin.py`` imports.

A Python plugin is a folder with ``plugin.yaml`` (name, inputs, settings - see
plugins/README.md) and ``plugin.py`` defining ``run``::

    from plugins.sdk import Item, PluginError

    async def run(value, type, ctx):
        r = await ctx.http.get("https://api.example.com/lookup", params={"q": value},
                               headers={"X-Key": ctx.settings.EXAMPLE_API_KEY})
        if r.status_code == 404:
            return []                                   # nothing found
        r.raise_for_status()
        data = r.json()
        return Item(title=data["name"], url=data["profile"], fields={"Joined": data["created"]})

``run`` may return an ``Item``, a list of them, any other JSON-like data (shown as
a tree), or None. Written as an async generator (``yield Item(...)``), its cards
appear one by one while it runs. A plain ``def run`` works too (it runs in a thread).
"""
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

import httpx

__all__ = ["Item", "PluginError", "Context", "Settings"]

FieldList = Union[Mapping[str, Any], Sequence[Tuple[str, Any]]]


@dataclass
class Item:
    """One result card.

    title     - main line (site, account, record name)
    subtitle  - small line under the title
    url       - "Open" link of the card
    image     - profile picture / photo (gets reverse image search buttons)
    site      - domain whose favicon is the card icon, e.g. "github.com"
    icon      - icon URL, if not the site's favicon
    category  - group label, e.g. "Social"
    fields    - rows shown on the card: {"Label": value} or [("Label", value), ...]
    entities  - identifiers to pivot on: {"email": "a@b.c", "url": ["...", "..."]}
                types: email, phone, username, domain, ip, url, telegram_id,
                telegram_username, vk, gaia_id, bssid, crypto_btc, crypto_eth
    """
    title: str
    subtitle: str = ""
    url: str = ""
    image: str = ""
    site: str = ""
    icon: str = ""
    category: str = ""
    fields: FieldList = field(default_factory=dict)
    entities: Dict[str, Any] = field(default_factory=dict)


class PluginError(Exception):
    """Raise with a message the user should see ("API key rejected", "Rate limited")."""


class Settings:
    """The plugin's own settings (declared in plugin.yaml): ``ctx.settings.MY_KEY``
    or ``ctx.settings["MY_KEY"]``. Unset settings are None."""

    _values: Dict[str, Optional[str]]

    def __init__(self, values: Dict[str, Optional[str]]):
        object.__setattr__(self, "_values", dict(values))

    def __getattr__(self, key: str) -> Optional[str]:
        if key.startswith("__"):
            raise AttributeError(key)
        return self._values.get(key)

    def __getitem__(self, key: str) -> Optional[str]:
        return self._values.get(key)

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        return self._values.get(key) or default

    def __setattr__(self, _key, _value):
        raise AttributeError("Settings are read-only")

    def __repr__(self) -> str:  # never print key values
        return f"Settings({', '.join(self._values)})"


class Context:
    """Passed to ``run`` as ``ctx``.

    ctx.value / ctx.type - what is being looked up ("someone@mail.com", "email")
    ctx.settings         - the plugin's settings (Settings)
    ctx.http             - httpx.AsyncClient (30 s timeout, follows redirects); closed after the run
    ctx.log              - logger; setting values marked secret are masked in its output
    ctx.run_command(cmd) - run a CLI tool without blocking the server (returns CommandResult)
    """

    def __init__(self, plugin_id: str, value: str, type: str, settings: Settings,
                 http: httpx.AsyncClient, log: logging.Logger):
        self.plugin_id = plugin_id
        self.value = value
        self.type = type
        self.settings = settings
        self.http = http
        self.log = log

    async def run_command(self, cmd: List[str], timeout: float = 120, cwd: Optional[str] = None):
        from utils.subprocess_runner import run_command
        return await run_command(cmd, timeout=timeout, cwd=cwd)
