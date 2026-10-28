"""The single Telegram (Telethon) client shared by every feature.

Login (/auth/tg), VK history (bot conversation) and Funstat media all use the
same ``telegram_session`` file. Separate TelegramClient objects on one SQLite
session file lock each other out ("database is locked") and can corrupt the
session, so everything goes through this module instead.
"""
import asyncio
import inspect
import logging
import os
from typing import Optional

from dotenv import load_dotenv
from telethon import TelegramClient

logger = logging.getLogger(__name__)

SESSION_NAME = "telegram_session"

_client: Optional[TelegramClient] = None
_connect_lock: Optional[asyncio.Lock] = None


class TelegramNotAuthorized(Exception):
    """The session exists but nobody has logged in (use the Telegram auth page)."""


def get_client() -> TelegramClient:
    """Return the shared client (created on first use, not necessarily connected)."""
    global _client
    if _client is None:
        load_dotenv()
        api_id = int(os.getenv("TG_API_ID") or 0)
        api_hash = os.getenv("TG_API_HASH") or ""
        if not api_id or not api_hash:
            logger.warning("TG_API_ID / TG_API_HASH are not configured; Telegram features will fail")
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
