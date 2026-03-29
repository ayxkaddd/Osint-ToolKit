import os
import re
import threading
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

TOKEN_REGISTRY: dict[str, dict] = {

    "JWT_SECRET": {
        "label":       "JWT Secret",
        "description": "Secret key used to sign JWT tokens. Change before first run.",
        "required":    True,
        "category":    "app",
        "sensitive":   True,
        "hint":        "Any long random string, e.g. openssl rand -hex 32",
    },
    "ROOT_EMAIL": {
        "label":       "Root Admin Email",
        "description": "Login email for the root admin account.",
        "required":    True,
        "category":    "app",
        "sensitive":   False,
        "hint":        "e.g. admin@localhost",
    },
    "ROOT_PASSWORD": {
        "label":       "Root Admin Password (bcrypt)",
        "description": "Bcrypt hash of the root admin password.",
        "required":    True,
        "category":    "app",
        "sensitive":   True,
        "hint":        "Generate at https://bcrypt-generator.com/ — never store plaintext",
    },

    "GITFIVE_VENV_PATH": {
        "label":       "GitFive — Venv Python Path",
        "description": "Absolute path to the GitFive virtualenv Python binary.",
        "required":    False,
        "category":    "tool_path",
        "sensitive":   False,
        "hint":        "Linux: /home/user/GitFive/venv/bin/python  |  Windows: venv\\Scripts\\python.exe",
    },
    "GITFIVE_SCRIPT_PATH": {
        "label":       "GitFive — Script Path",
        "description": "Absolute path to the GitFive main.py entry point.",
        "required":    False,
        "category":    "tool_path",
        "sensitive":   False,
        "hint":        "e.g. /home/user/scripts/GitFive/main.py",
    },
    "HTTPX_PATH": {
        "label":       "httpx Binary Path",
        "description": "Absolute path to the httpx binary (ProjectDiscovery).",
        "required":    False,
        "category":    "tool_path",
        "sensitive":   False,
        "hint":        "e.g. /usr/local/bin/httpx",
    },
    "SUBFINDER_PATH": {
        "label":       "Subfinder Binary Path",
        "description": "Absolute path to the subfinder binary.",
        "required":    False,
        "category":    "tool_path",
        "sensitive":   False,
        "hint":        "e.g. /usr/local/bin/subfinder",
    },
    "NMAP_PATH": {
        "label":       "Nmap Binary Path",
        "description": "Absolute path to the nmap binary.",
        "required":    False,
        "category":    "tool_path",
        "sensitive":   False,
        "hint":        "e.g. /usr/bin/nmap",
    },

    "OSINT_INDUSTRIES_API_KEY": {
        "label":       "OSINT Industries API Key",
        "description": "API key for OSINT Industries search queries.",
        "required":    False,
        "category":    "api_key",
        "sensitive":   True,
        "hint":        "https://osint.industries — account dashboard",
    },
    "HACKER_TARGET_API_KEY": {
        "label":       "HackerTarget API Key",
        "description": "API key for HackerTarget network recon tools.",
        "required":    False,
        "category":    "api_key",
        "sensitive":   True,
        "hint":        "https://hackertarget.com/account/",
    },
    "WHOIS_XML_API_KEY": {
        "label":       "WhoisXML API Key",
        "description": "API key for WHOIS, DNS, and IP intelligence lookups.",
        "required":    False,
        "category":    "api_key",
        "sensitive":   True,
        "hint":        "https://user.whoisxmlapi.com/products",
    },
    "SECURITYTRAILS_API_KEY": {
        "label":       "SecurityTrails API Key",
        "description": "API key for historical DNS and domain intel via SecurityTrails.",
        "required":    False,
        "category":    "api_key",
        "sensitive":   True,
        "hint":        "https://securitytrails.com/app/account/apikey",
    },
    "VIRUSTOTAL_API_KEY": {
        "label":       "VirusTotal API Key",
        "description": "API key for file, URL, domain, and IP reputation lookups.",
        "required":    False,
        "category":    "api_key",
        "sensitive":   True,
        "hint":        "https://www.virustotal.com/gui/my-apikey",
    },

    # ── Telegram ─────────────────────────────────────────────────────────────
    "TELEGRAM_API_ID": {
        "label":       "Telegram API ID",
        "description": "Numeric API ID for Telegram client (Telethon).",
        "required":    False,
        "category":    "telegram",
        "sensitive":   True,
        "hint":        "https://my.telegram.org/apps — integer value",
    },
    "TELEGRAM_API_HASH": {
        "label":       "Telegram API Hash",
        "description": "API hash string paired with TELEGRAM_API_ID.",
        "required":    False,
        "category":    "telegram",
        "sensitive":   True,
        "hint":        "https://my.telegram.org/apps — 32-char hex string",
    },
}

CATEGORY_ORDER = ["app", "tool_path", "api_key", "telegram"]

CATEGORY_LABELS = {
    "app":       "Application",
    "tool_path": "Tool Paths",
    "api_key":   "OSINT / Recon APIs",
    "telegram":  "Telegram",
}


class TokenManager:
    """
    Singleton. Owns all API token reads and writes.
    Services call TokenManager.get("KEY") — never os.getenv directly.
    """
    _instance: Optional["TokenManager"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._env_path = Path(__file__).parent.parent / ".env"
        self._cache: dict[str, str] = {}
        self._write_lock = threading.Lock()
        self._reload()
        self._initialized = True

    # ── public API ──────────────────────────────────────────────

    def get(self, key: str, default: str = "") -> str:
        """Get a token value. Used by every service."""
        return self._cache.get(key, default)

    def get_all(self, redact: bool = True) -> dict[str, dict]:
        result = {}
        for key, meta in TOKEN_REGISTRY.items():
            value = self._cache.get(key, "")
            should_redact = redact and meta["sensitive"]
            result[key] = {
                **meta,
                "set":   bool(value),
                "value": self._redact(value) if should_redact else value,
            }
        return result

    def update(self, updates: dict[str, str]) -> list[str]:
        """
        Write one or more tokens back to .env atomically.
        Returns list of keys that were actually changed.
        """
        unknown = [k for k in updates if k not in TOKEN_REGISTRY]
        if unknown:
            raise ValueError(f"Unknown token keys: {unknown}")

        with self._write_lock:
            env_text = self._env_path.read_text() if self._env_path.exists() else ""
            changed = []

            for key, value in updates.items():
                value = value.strip()
                env_text, did_change = self._set_in_text(env_text, key, value)
                if did_change:
                    changed.append(key)

            self._env_path.write_text(env_text)
            self._reload()   # refresh in-memory cache
            return changed

    def reload(self):
        """Force a cache refresh (e.g. after manual .env edit)."""
        self._reload()

    def missing_required(self) -> list[str]:
        return [k for k, m in TOKEN_REGISTRY.items()
                if m["required"] and not self._cache.get(k)]

    # ── internals ───────────────────────────────────────────────

    def _reload(self):
        load_dotenv(self._env_path, override=True)
        self._cache = {key: os.getenv(key, "") for key in TOKEN_REGISTRY}

    def _redact(self, value: str) -> str:
        if not value:
            return ""
        if len(value) <= 8:
            return "••••••••"
        return value[:4] + "••••••••" + value[-4:]

    def _set_in_text(self, text: str, key: str, value: str) -> tuple[str, bool]:
        """Update or append a KEY=VALUE line. Returns (new_text, changed)."""
        pattern = re.compile(rf"^{re.escape(key)}\s*=.*$", re.MULTILINE)
        new_line = f'{key}="{value}"' if value else f"{key}="
        old_value = self._cache.get(key, "")

        if pattern.search(text):
            new_text = pattern.sub(new_line, text)
        else:
            separator = "\n" if text and not text.endswith("\n") else ""
            new_text = text + separator + new_line + "\n"

        changed = old_value != value
        return new_text, changed


# Module-level singleton — import this everywhere
tokens = TokenManager()