"""The single Telegram (Telethon) client shared by every feature.

Login (/auth/tg), VK history (bot conversation) and Funstat media all use the
same ``telegram_session`` file. Separate TelegramClient objects on one SQLite
session file lock each other out ("database is locked") and can corrupt the
session, so everything goes through this module instead.
"""
import asyncio
import inspect
import logging
from typing import Optional, Tuple

from telethon import TelegramClient

from utils.config import get_setting

logger = logging.getLogger(__name__)

SESSION_NAME = "telegram_session"

_client: Optional[TelegramClient] = None
_connect_lock: Optional[asyncio.Lock] = None


class TelegramNotAuthorized(Exception):
    """The session exists but nobody has logged in (use the Telegram auth page)."""


class TelegramNotConfigured(ValueError):
    """TG_API_ID / TG_API_HASH are missing or invalid (set them in Settings)."""


def _credentials() -> Optional[Tuple[int, str]]:
    api_id = (get_setting("TG_API_ID") or "").strip()
    api_hash = (get_setting("TG_API_HASH") or "").strip()
    if not api_id.isdecimal() or int(api_id) == 0 or not api_hash:
        return None
    return int(api_id), api_hash


def is_configured() -> bool:
    return _credentials() is not None


def get_client() -> TelegramClient:
    """Return the shared client (created on first use, not necessarily connected)."""
    global _client
    if _client is None:
        credentials = _credentials()
        if credentials is None:
            raise TelegramNotConfigured("Telegram API ID and hash are not set - add them in Settings")
        api_id, api_hash = credentials
        _client = TelegramClient(SESSION_NAME, api_id, api_hash, flood_sleep_threshold=60)
    return _client


async def ensure_connected(require_authorized: bool = True) -> TelegramClient:
    """Connect the shared client if needed. Never prompts for a login code."""
    global _connect_lock
    if _connect_lock is None:
        _connect_lock = asyncio.Lock()
    client = get_client()
    async with _connect_lock:
        if not client.is_connected():
            await client.connect()
    if require_authorized and not await client.is_user_authorized():
        raise TelegramNotAuthorized("Telegram is not logged in - open the Telegram auth page first")
    return client


async def disconnect() -> None:
    if _client is not None and _client.is_connected():
        # Telethon returns a coroutine only when called inside a running loop
        result = _client.disconnect()
        if inspect.isawaitable(result):
            await result
