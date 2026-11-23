"""Where the client keeps the server address and the login token.

``config.json`` in the user's config folder (platformdirs), or in ``OSINT_CONFIG_DIR``
when that is set. The file holds a login token, so on Linux and macOS only its owner
can read it.
"""
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from platformdirs import user_config_dir

DEFAULT_URL = "http://127.0.0.1:8000"


def config_dir() -> Path:
    override = os.environ.get("OSINT_CONFIG_DIR")
    return Path(override) if override else Path(user_config_dir("osint-toolkit"))


def config_path() -> Path:
    return config_dir() / "config.json"


@dataclass
class Config:
    url: str = DEFAULT_URL
    token: Optional[str] = None


def load() -> Config:
    try:
        data = json.loads(config_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return Config()
    return Config(url=data.get("url") or DEFAULT_URL, token=data.get("token") or None)


def save(config: Config) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    # created readable by the owner only (the mode is ignored on Windows)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"url": config.url, "token": config.token}, f, indent=2)
    os.replace(tmp, path)
    if os.name != "nt":
        os.chmod(path, 0o600)


def server_url(option: Optional[str], config: Config) -> str:
    """--url, then OSINT_URL, then the address used at login."""
    url = option or os.environ.get("OSINT_URL") or config.url or DEFAULT_URL
    return url.rstrip("/")
