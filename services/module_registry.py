"""What every module can look up, how to run it, what it costs and whether it
is ready to use. Drives the search box, background jobs, pivot menus, the
dashboard readiness badges and the settings page."""
import asyncio
import json
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from collections.abc import Callable

import httpx

from utils.config import get_setting

FREE, PAID, PAID_API = "free", "paid", "paid"


@dataclass
class RunSpec:
    """How to call the module's API for one input type."""
    method: str
    path: str
    build: Callable[[str], dict[str, Any]]   # value -> {"params": {...}} or {"json": ...}
    stream: bool = False                      # SSE / NDJSON response


@dataclass
class Module:
    id: str
    name: str
    page: str
    icon: str
    accepts: dict[str, RunSpec]
    cost: str = FREE                 # free / paid
    cost_note: str = ""              # e.g. "1 OSINT Industries credit"
    speed: str = "fast"              # fast (<10s) / medium (<1 min) / slow (minutes)
    keys: list[str] = field(default_factory=list)          # required settings
    optional_keys: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)          # settings that name executables
    optional_tools: list[str] = field(default_factory=list)  # executables that only add results
    needs_telegram: bool = False
    concurrency: int = 2
    # module page prefill: CSS selector of the main input (+ optional select value)
    prefill: Optional[dict[str, str]] = None
    # service_name its results are saved under (to find earlier lookups)
    service: str = ""
    plugin: bool = False             # added from plugins/ (services/plugin_loader.py)
    extra_problems: Optional[Callable[[], list[str]]] = None

    def __post_init__(self):
        self.service = self.service or SAVED_SERVICE.get(self.id, self.id)


SAVED_SERVICE = {"whois_history": "whois", "ip_info": "ip", "phone_info": "phone"}


def _q(name: str) -> Callable[[str], dict[str, Any]]:
    return lambda v: {"params": {name: v}}


MODULES: list[Module] = [
    Module("phone_info", "Phone number info", "/phone", "phone",
           {"phone": RunSpec("GET", "/api/phone/info", _q("phone"))},
           cost_note="Offline - country, carrier, line type", prefill={"input": "#phoneInput"}),
    Module("hlr", "HLR lookup", "/phone", "radio-tower",
           {"phone": RunSpec("POST", "/api/hlr/lookup", lambda v: {"json": {"phones": v}})},
           cost=PAID, cost_note="smsc.ru balance", speed="medium", concurrency=1,
           prefill={"input": "#phoneInput"}),
    Module("username", "Username search", "/username", "user-check",
           {"username": RunSpec("GET", "/api/username/search/stream",
                                lambda v: {"params": {"username": v, "extract_profile": "true"}}, stream=True),
            "telegram_username": RunSpec("GET", "/api/username/search/stream",
                                         lambda v: {"params": {"username": v, "extract_profile": "true"}}, stream=True)},
           speed="slow", concurrency=1, prefill={"input": "#usernameSearchInput"}),
    Module("gitfive", "GitHub (GitFive)", "/gitfive", "github",
           {"username": RunSpec("GET", "/api/gitfive/query", _q("username"))},
           speed="slow", tools=["GITFIVE_SCRIPT_PATH"], concurrency=1, prefill={"input": "#usernameInput"}),
    Module("ghunt", "Google account (GHunt)", "/ghunt", "mail",
           {"email": RunSpec("GET", "/api/ghunt/email", _q("email")),
            "gaia_id": RunSpec("GET", "/api/ghunt/gaia", _q("gaia_id")),
            "bssid": RunSpec("GET", "/api/ghunt/geolocate", _q("bssid")),
            "domain": RunSpec("GET", "/api/ghunt/spiderdal", _q("domain"))},
           speed="medium", concurrency=1, prefill={"input": "#searchInput"}),
    Module("oi", "OSINT Industries", "/oi", "shield-alert",
           {t: RunSpec("GET", "/api/oi/query", (lambda kind: lambda v: {"params": {"type": kind, "query": v}})(t))
            for t in ("email", "phone", "username")},
           cost=PAID, cost_note="OSINT Industries credits", speed="medium", keys=["OSINT_INDUSTRIES_API_KEY"],
           prefill={"input": "#queryInput", "type_select": "#queryType"}),
    Module("cavalier", "Infostealer exposure (Hudson Rock)", "/cavalier", "shield",
           {"email": RunSpec("GET", "/api/cavalier/search", _q("query")),
            "username": RunSpec("GET", "/api/cavalier/search", _q("query"))},
           prefill={"input": "#usernameInput"}),
    Module("funstat", "Telegram user (Funstat)", "/funstat", "message-square",
           {"telegram_id": RunSpec("GET", "/funstat/users/basic_info_by_id", _q("id")),
            "telegram_username": RunSpec("GET", "/funstat/users/resolve_username", _q("name"))},
           cost=PAID, cost_note="Funstat credits", keys=["FUNSTAT_API_KEY"], prefill={"input": "#userSearchInput"}),
    Module("vk_profile", "VK profile history", "/vk", "user",
           {"vk": RunSpec("GET", "/api/telegram/search/stream", _q("user_id"), stream=True)},
           speed="medium", needs_telegram=True, concurrency=1, prefill={"input": "#user-id"}),
    Module("whois_history", "WHOIS history", "/whois", "history",
           {"domain": RunSpec("GET", "/api/domain/history", _q("domain"))},
           cost=PAID, cost_note="WhoisXML credits", keys=["WHOIS_XML_API_KEY"], prefill={"input": "#domainInput"}),
    Module("dns_recon", "DNS reconnaissance", "/dnsrecon", "globe",
           {"domain": RunSpec("POST", "/api/recon/", lambda v: {"json": {"domain": v}})},
           speed="slow", optional_tools=["SUBFINDER_PATH", "HTTPX_PATH"],
           optional_keys=["SECURITYTRAILS_API_KEY", "VIRUSTOTAL_API_KEY"], concurrency=1,
           prefill={"input": "#domainInput"}),
    Module("ip_info", "IP address info", "/ip", "map-pin",
           {"ip": RunSpec("GET", "/api/ip/lookup", _q("ip"))},
           optional_keys=["IPINFO_API_TOKEN", "ABUSEIPDB_API_KEY", "SHODAN_API_KEY"], prefill={"input": "#ipInput"}),
    Module("web_search", "Web dorking (SerpAPI)", "/websearch", "search",
           {t: RunSpec("POST", "/web/search",
                       (lambda kind: lambda v: {"json": {"value": v, "input_type": kind, "engines": ["google"]}})(k))
            for t, k in (("email", "email"), ("username", "username"), ("phone", "phone"), ("text", "full_name"))},
           cost=PAID, cost_note="SerpAPI searches (one per dork)", speed="medium", keys=["SERPAPI_KEY"],
           prefill={"input": "#searchInput"}),
]

MODULES_BY_ID = {m.id: m for m in MODULES}


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------

_labels_cache: dict[str, Any] = {"mtime": None, "labels": {}}


def setting_label(key: str) -> str:
    """A setting's name as the Settings page shows it ("OSINT Industries API Key"), for
    messages: people know the field's label, not OSINT_INDUSTRIES_API_KEY."""
    path = Path("resources.json")
    try:
        mtime = path.stat().st_mtime
        if _labels_cache["mtime"] != mtime:
            labels = {}
            for module in json.loads(path.read_text()).get("modules", []):
                for name, config in (module.get("settings") or {}).items():
                    # "SerpAPI Key (Optional)", "Telegram API ID (https://...)" -> the name alone
                    label = re.sub(r"\s*\([^)]*\)", "", str(config.get("label") or "")).strip()
                    if label:
                        labels[name.upper()] = label
            _labels_cache.update(mtime=mtime, labels=labels)
    except (OSError, ValueError):
        pass
    if key in _labels_cache["labels"]:
        return _labels_cache["labels"][key]
    from services import plugin_loader
    for plugin in plugin_loader.refresh().values():
        spec = plugin.manifest.settings.get(key) if plugin.manifest else None
        if spec and spec.label:
            return f"{plugin.name} {spec.label}" if plugin.name.lower() not in spec.label.lower() else spec.label
    return key.replace("_", " ").capitalize()


def _fix(problem: str, action: str, href: str = "/settings") -> dict[str, str]:
    """What stops a module, with what to do about it (a few words) and where."""
    return {"problem": problem, "action": action, "href": href}


def _tool_available(setting: str) -> Optional[dict[str, str]]:
    """None if the executable/script named by a setting exists, else what to fix."""
    defaults = {"SUBFINDER_PATH": "subfinder", "HTTPX_PATH": "httpx-toolkit"}
    value = get_setting(setting) or defaults.get(setting)
    label = setting_label(setting)
    if not value:
        return _fix(f"{label} is not set", f"Set the {label}", f"/settings#{setting}")
    if os.sep in value or value.endswith(".py"):
        return None if Path(value).exists() else _fix(f"{label}: {value} was not found", f"Fix the {label}",
                                                      f"/settings#{setting}")
    return None if shutil.which(value) else _fix(f"{value} is not installed", f"Install {value}")


_telegram_cache: dict[str, Any] = {"at": 0.0, "ok": None}


async def telegram_authorized() -> bool:
    """Cached for 60 s: is the shared Telegram client logged in?"""
    if time.monotonic() - _telegram_cache["at"] < 60 and _telegram_cache["ok"] is not None:
        return _telegram_cache["ok"]
    from utils import telegram_client
    try:
        client = await asyncio.wait_for(telegram_client.ensure_connected(require_authorized=False), timeout=10)
        ok = bool(await client.is_user_authorized())
    except Exception:
        ok = False
    _telegram_cache.update(at=time.monotonic(), ok=ok)
    return ok


async def module_status(module: Module) -> dict[str, Any]:
    fixes: list[dict[str, str]] = []
    for key in module.keys:
        if not get_setting(key):
            label = setting_label(key)
            fixes.append(_fix(f"{label} is not set", f"Add the {label}", f"/settings#{key}"))
    if module.id == "hlr" and not Path("assets/sms_logins.json").exists():
        fixes.append(_fix("The HLR login file (assets/sms_logins.json) is missing", "Add the HLR login file"))
    if module.id == "ghunt":
        from services.ghunt_service import ghunt_command
        problem = ghunt_command()[1]
        if problem:
            fixes.append(_fix(problem, "Set up GHunt", "/settings#GHUNT_SCRIPT_PATH"))
    for tool in module.tools:
        fix = _tool_available(tool)
        if fix:
            fixes.append(fix)
    if module.needs_telegram:
        from utils import telegram_client
        if not telegram_client.is_configured():
            fixes.append(_fix("The Telegram API ID and hash are not set", "Add the Telegram API ID and hash", "/settings#TG_API_ID"))
        elif not await telegram_authorized():
            fixes.append(_fix("Telegram is not logged in", "Log in to Telegram", "/telegram_auth"))
    if module.extra_problems:
        fixes += [_fix(problem, "Review the plugin" if module.plugin else problem,
                       "/plugins" if module.plugin else "/settings") for problem in module.extra_problems()]
    problems = [fix["problem"] for fix in fixes]
    missing_optional = [k for k in module.optional_keys if not get_setting(k)]
    missing_optional += [t for t in module.optional_tools if _tool_available(t)]
    return {
        "id": module.id,
        "name": module.name,
        "page": module.page,
        "icon": module.icon,
        "accepts": sorted(module.accepts),
        "cost": module.cost,
        "cost_note": module.cost_note,
        "speed": module.speed,
        "ready": not problems,
        "problems": problems,
        # the same, each with what to do (a few words) and the page to do it on
        "setup": fixes,
        "optional_missing": missing_optional,
        "settings": module.keys + module.optional_keys + module.tools + module.optional_tools,
        "prefill": module.prefill,
        "service": module.service,
        "plugin": module.plugin,
    }


async def all_module_status() -> list[dict[str, Any]]:
    from services import plugin_loader
    plugin_loader.refresh()
    return list(await asyncio.gather(*(module_status(m) for m in MODULES)))


# ---------------------------------------------------------------------------
# Balances (cheap calls only, cached)
# ---------------------------------------------------------------------------

_balance_cache: dict[str, Any] = {}


async def balances() -> dict[str, Any]:
    """Remaining credits where a free balance endpoint exists (cached 5 min)."""
    from services.funstat_service import last_tech
    funstat = {"funstat": f"{last_tech['balance']} credits"} if last_tech.get("balance") is not None else {}
    if _balance_cache and time.monotonic() - _balance_cache.get("_at", 0) < 300:
        return {**{k: v for k, v in _balance_cache.items() if k != "_at"}, **funstat}
    result: dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=8) as client:
        async def oi():
            key = get_setting("OSINT_INDUSTRIES_API_KEY")
            if key:
                try:
                    r = await client.get("https://api.osint.industries/misc/credits", headers={"api-key": key})
                    if r.status_code == 200:
                        result["oi"] = r.text.strip()
                except httpx.HTTPError:
                    pass

        async def serpapi():
            key = get_setting("SERPAPI_KEY")
            if key:
                try:
                    r = await client.get("https://serpapi.com/account", params={"api_key": key})
                    if r.status_code == 200:
                        data = r.json()
                        result["web_search"] = f"{data.get('total_searches_left', '?')} searches left"
                except (httpx.HTTPError, ValueError):
                    pass

        await asyncio.gather(oi(), serpapi())
    _balance_cache.clear()
    _balance_cache.update(result, _at=time.monotonic())
    return {**result, **funstat}


def modules_for(entity_type: str) -> list[Module]:
    return [m for m in MODULES if entity_type in m.accepts]
