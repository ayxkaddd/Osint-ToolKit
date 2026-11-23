"""Where plugins live, limits, the names they may not use, template filters."""
import hashlib
import logging
import re
import threading
from pathlib import Path
from collections.abc import Callable
from urllib.parse import quote


from services.module_registry import MODULES


logger = logging.getLogger("services.plugin_loader")

PLUGINS_DIR = Path("plugins")

TRUST_FILE = PLUGINS_DIR / ".trust.json"

RESOURCES_PATH = Path("resources.json")

BUNDLED = {"github_user", "crtsh", "gravatar", "hunter_io", "oathnet"}   # shipped with the toolkit

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

FILTERS: dict[str, Callable[[str], str]] = {
    "lower": str.lower,
    "upper": str.upper,
    "trim": lambda s: s.strip().lstrip("@"),
    "md5": lambda s: hashlib.md5(s.encode()).hexdigest(),
    "sha1": lambda s: hashlib.sha1(s.encode()).hexdigest(),
    "sha256": lambda s: hashlib.sha256(s.encode()).hexdigest(),
    "urlencode": lambda s: quote(s, safe=""),
    "date": lambda s: s[:10],
}

_lock = threading.RLock()
