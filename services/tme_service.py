"""Public Telegram profile from the t.me/<username> preview page: name, bio, avatar.

Free and needs no Telegram login. The avatar link on the page is a signed CDN URL
that expires, so the image is saved under media/avatars (served behind login).
A new file is written only when the picture changes, which keeps earlier avatars.
"""
import hashlib
import html
import logging
import os
import re
from typing import Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

AVATAR_DIR = os.path.join("media", "avatars")
AVATAR_URL = "/funstat/media/avatars"
USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")
# Avatars only ever come from Telegram's CDNs
AVATAR_HOST_RE = re.compile(r"^(cdn\d*\.telesco\.pe|cdn\d*\.telegram-cdn\.org|telegram\.org)$")
MAX_AVATAR_BYTES = 5 * 1024 * 1024
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}


class TmeError(Exception):
    pass


def normalize_username(value: str) -> str:
    username = (value or "").strip()
    username = re.sub(r"^(https?://)?(www\.)?(t|telegram)\.me/", "", username, flags=re.I).lstrip("@").strip("/")
    if not USERNAME_RE.match(username):
        raise TmeError("Not a valid Telegram username")
    return username


def _first(pattern: str, page: str) -> Optional[str]:
    match = re.search(pattern, page, re.S)
    return match.group(1) if match else None


def _text(fragment: Optional[str]) -> Optional[str]:
    """Inner HTML of a t.me element -> plain text (bios use <br/> for newlines)."""
    if fragment is None:
        return None
    text = re.sub(r"<br\s*/?>", "\n", fragment)
    text = html.unescape(re.sub(r"<[^>]+>", "", text)).strip()
    return text or None


def parse_profile(page: str) -> dict:
    """Pull name, bio and avatar URL out of a t.me preview page."""
    name = _text(_first(r'<div class="tgme_page_title"[^>]*>(.*?)</div>', page))
    bio = _text(_first(r'<div class="tgme_page_description[^"]*"[^>]*>(.*?)</div>', page))
    extra = _text(_first(r'<div class="tgme_page_extra"[^>]*>(.*?)</div>', page))
    avatar = _first(r'<img class="tgme_page_photo_image"[^>]*src="([^"]+)"', page)
    return {
        # Unknown usernames get the generic "Contact @x" page without a title block
        "exists": name is not None,
        "name": name,
        "bio": bio,
        # Channels/groups show "N subscribers" / "N members" here
        "extra": extra,
        "avatar_source": html.unescape(avatar) if avatar else None,
    }


async def _save_avatar(client: httpx.AsyncClient, username: str, url: str) -> Optional[str]:
    if urlparse(url).scheme != "https" or not AVATAR_HOST_RE.match(urlparse(url).hostname or ""):
        logger.warning("Ignoring avatar from unexpected host: %s", urlparse(url).hostname)
        return None
    response = await client.get(url)
    response.raise_for_status()
    data = response.content
    if not data or len(data) > MAX_AVATAR_BYTES or not response.headers.get("content-type", "").startswith("image/"):
        return None
    filename = f"{username.lower()}_{hashlib.sha256(data).hexdigest()[:16]}.jpg"
    path = os.path.join(AVATAR_DIR, filename)
    if not os.path.isfile(path):
        os.makedirs(AVATAR_DIR, exist_ok=True)
        with open(path + ".part", "wb") as f:
            f.write(data)
        os.replace(path + ".part", path)
    return f"{AVATAR_URL}/{filename}"


async def fetch_profile(username: str) -> dict:
    username = normalize_username(username)
    async with httpx.AsyncClient(timeout=15, headers=HEADERS, follow_redirects=False) as client:
        try:
            response = await client.get(f"https://t.me/{username}")
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise TmeError(f"t.me did not answer: {e}") from e
        profile = parse_profile(response.text)
        avatar_url = None
        if profile["avatar_source"]:
            try:
                avatar_url = await _save_avatar(client, username, profile["avatar_source"])
            except httpx.HTTPError as e:
                logger.warning("Avatar download failed for %s: %s", username, e)
    profile.pop("avatar_source")
    return {"username": username, "link": f"https://t.me/{username}", **profile, "avatar_url": avatar_url}
