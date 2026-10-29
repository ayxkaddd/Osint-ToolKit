"""What every module can look up, how to run it, what it costs and whether it
is ready to use. Drives the search box, background jobs, pivot menus, the
dashboard readiness badges and the settings page."""
import asyncio
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import httpx

from utils.config import get_setting

FREE, PAID, PAID_API = "free", "paid", "paid"


@dataclass
class RunSpec:
    """How to call the module's API for one input type."""
    method: str
    path: str
    build: Callable[[str], Dict[str, Any]]   # value -> {"params": {...}} or {"json": ...}
    stream: bool = False                      # SSE / NDJSON response


@dataclass
class Module:
    id: str
    name: str
    page: str
    icon: str
    accepts: Dict[str, RunSpec]
    cost: str = FREE                 # free / paid
    cost_note: str = ""              # e.g. "1 OSINT Industries credit"
    speed: str = "fast"              # fast (<10s) / medium (<1 min) / slow (minutes)
    keys: List[str] = field(default_factory=list)          # required settings
    optional_keys: List[str] = field(default_factory=list)
    tools: List[str] = field(default_factory=list)          # settings that name executables
    optional_tools: List[str] = field(default_factory=list)  # executables that only add results
    needs_telegram: bool = False
    concurrency: int = 2
    # module page prefill: CSS selector of the main input (+ optional select value)
    prefill: Optional[Dict[str, str]] = None
    # service_name its results are saved under (to find earlier lookups)
    service: str = ""
    plugin: bool = False             # added from plugins/ (services/plugin_loader.py)
    extra_problems: Optional[Callable[[], List[str]]] = None

    def __post_init__(self):
        self.service = self.service or SAVED_SERVICE.get(self.id, self.id)


SAVED_SERVICE = {"whois_history": "whois", "ip_info": "ip", "phone_info": "phone"}


def _q(name: str) -> Callable[[str], Dict[str, Any]]:
    return lambda v: {"params": {name: v}}


MODULES: List[Module] = [
    Module("phone_info", "Phone number info", "/hlr", "phone",
           {"phone": RunSpec("GET", "/api/phone/info", _q("phone"))},
           cost_note="Offline - country, carrier, line type", prefill={"input": "#phoneInput"}),
    Module("hlr", "HLR lookup", "/hlr", "radio-tower",
           {"phone": RunSpec("POST", "/api/hlr/lookup", lambda v: {"json": {"phones": v}})},
           cost=PAID, cost_note="smsc.ru balance", speed="medium", concurrency=1,
           prefill={"input": "#phoneInput"}),
    Module("username", "Username search", "/username", "user-check",
           {"username": RunSpec("GET", "/api/username/search/stream",
                                lambda v: {"params": {"username": v, "extract_profile": "true"}}, stream=True),
            "telegram_username": RunSpec("GET", "/api/username/search/stream",
                                         lambda v: {"params": {"username": v, "extract_profile": "true"}}, stream=True)},
           speed="slow", concurrency=1, prefill={"input": "#usernameSearchInput"}),
    Module("gitfive", "GitHub (GitFive)", "/git", "github",
           {"username": RunSpec("GET", "/api/gitfive/query", _q("username"))},
           speed="slow", tools=["GITFIVE_SCRIPT_PATH"], concurrency=1, prefill={"input": "#usernameInput"}),
    Module("ghunt", "Google account (GHunt)", "/ghunt", "mail",
           {"email": RunSpec("GET", "/api/ghunt/email", _q("email")),
            "gaia_id": RunSpec("GET", "/api/ghunt/gaia", _q("gaia_id")),
            "bssid": RunSpec("GET", "/api/ghunt/geolocate", _q("bssid")),
            "domain": RunSpec("GET", "/api/ghunt/spiderdal", _q("domain"))},
           speed="medium", tools=["GHUNT_SCRIPT_PATH"], concurrency=1, prefill={"input": "#searchInput"}),
    Module("oi", "OSINT Industries", "/api", "shield-alert",
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
           {"vk": RunSpec("GET", "/api/telegram/search", _q("user_id"))},
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

def _tool_available(setting: str) -> Optional[str]:
    """None if the executable/script named by a setting exists, else a message."""
    defaults = {"GHUNT_SCRIPT_PATH": "ghunt", "SUBFINDER_PATH": "subfinder", "HTTPX_PATH": "httpx-toolkit"}
    value = get_setting(setting) or defaults.get(setting)
    if not value:
        return f"{setting} is not set"
    if os.sep in value or value.endswith(".py"):
        return None if Path(value).exists() else f"{value} not found"
    return None if shutil.which(value) else f"{value} is not installed"


_telegram_cache: Dict[str, Any] = {"at": 0.0, "ok": None}


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


async def module_status(module: Module) -> Dict[str, Any]:
    problems: List[str] = []
    for key in module.keys:
        if not get_setting(key):
            problems.append(f"{key} is not configured")
    if module.id == "hlr" and not Path("assets/sms_logins.json").exists():
        problems.append("assets/sms_logins.json is missing")
    for tool in module.tools:
        problem = _tool_available(tool)
        if problem:
            problems.append(problem)
    if module.needs_telegram and not await telegram_authorized():
        problems.append("Telegram is not logged in")
    if module.extra_problems:
        problems += module.extra_problems()
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
        "optional_missing": missing_optional,
        "settings": module.keys + module.optional_keys + module.tools + module.optional_tools,
        "prefill": module.prefill,
        "service": module.service,
        "plugin": module.plugin,
    }


async def all_module_status() -> List[Dict[str, Any]]:
    from services import plugin_loader
    plugin_loader.refresh()
    return list(await asyncio.gather(*(module_status(m) for m in MODULES)))


# ---------------------------------------------------------------------------
# Balances (cheap calls only, cached)
# ---------------------------------------------------------------------------

_balance_cache: Dict[str, Any] = {}


async def balances() -> Dict[str, Any]:
    """Remaining credits where a free balance endpoint exists (cached 5 min)."""
    from services.funstat_service import last_tech
    funstat = {"funstat": f"{last_tech['balance']} credits"} if last_tech.get("balance") is not None else {}
    if _balance_cache and time.monotonic() - _balance_cache.get("_at", 0) < 300:
        return {**{k: v for k, v in _balance_cache.items() if k != "_at"}, **funstat}
    result: Dict[str, Any] = {}
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


def modules_for(entity_type: str) -> List[Module]:
    return [m for m in MODULES if entity_type in m.accepts]
