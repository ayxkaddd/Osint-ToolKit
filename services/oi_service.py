import json
import os
import re
import uuid
import aiohttp
from fastapi.responses import JSONResponse

from dotenv import load_dotenv
from services.site_icon_service import domain_from_url
from utils.config import get_setting

load_dotenv()

API_URL = "https://api.osint.industries"
STREAM_PATH = "/v2/request/stream"
# Same response shape as the real API, but deterministic fake data and no credits
SANDBOX_STREAM_PATH = "/sandbox/request/stream"


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"


def _error_text(body: str) -> str:
    try:
        data = json.loads(body)
    except ValueError:
        return body.strip()[:300]
    if isinstance(data, dict):
        return str(data.get("error") or data.get("detail") or data.get("message") or data)[:300]
    return str(data)[:300]


class OiService:
    @property
    def token(self):
        # Read per call so a key saved in settings applies without a restart
        return get_setting("OSINT_INDUSTRIES_API_KEY") or get_setting("OI_API_KEY")

    async def query_oi_api(
        self,
        type: str,
        query: str,
        premium: bool = False,
        premium_modules_only: bool = False,
        format: str = "json",
    ) -> JSONResponse:
        """format=json: results shown on the page, saved and searchable (default);
        format=pdf: OSINT Industries' own PDF report, saved as a file link."""
        query = query.strip()
        type = type.lower()
        premium = bool(premium or premium_modules_only)
        premium_modules_only = bool(premium_modules_only)

        if not self.token:
            return JSONResponse({"detail": "OSINT Industries API key is not configured"}, status_code=500)

        async with aiohttp.ClientSession() as session:
            headers = {
                "content-type": "application/json",
                'accept': 'application/pdf' if format == 'pdf' else 'application/json',
                'api-key': self.token,
            }

            params = {
                "type": type,
                "query": query,
                "timeout": 60,
                "exact_match": True,
                "premium": premium,
                "premium_modules_only": premium_modules_only,
            }

            timeout = aiohttp.ClientTimeout(total=150)
            async with session.post('https://api.osint.industries/v2/request', headers=headers, json=params,
                                    timeout=timeout) as resp:
                content_type = resp.headers.get('Content-Type', '')
                if resp.status >= 400:
                    detail = await resp.text()
                    return JSONResponse(
                        {"detail": detail or "OSINT Industries request failed"},
                        status_code=resp.status,
                    )

                if 'application/pdf' not in content_type:
                    try:
                        data = await resp.json(content_type=None)
                    except Exception:
                        return JSONResponse({"detail": await resp.text()}, status_code=502)
                    return JSONResponse({
                        "type": type,
                        "query": query,
                        "premium": premium,
                        "modules": normalize_oi(data),
                        "raw": data,
                    })

                os.makedirs('reports', exist_ok=True)
                filename = f'reports/{uuid.uuid4()}.pdf'
                with open(filename, 'wb') as f:
                    f.write(await resp.read())
                return JSONResponse({"url": "/" + filename})

    async def stream_oi(self, type: str, query: str, premium: bool = False,
                        premium_modules_only: bool = False, sandbox: bool = False):
        """SSE events as OSINT Industries finishes each module:
        started -> module (normalized cards) ... -> error? -> done."""
        query = query.strip()
        premium = bool(premium or premium_modules_only)
        yield _sse({"event": "started", "type": type, "query": query,
                    "premium": premium, "premium_modules_only": premium_modules_only, "sandbox": sandbox})
        if not self.token:
            yield _sse({"event": "error", "detail": "OSINT Industries API key is not configured"})
            yield _sse({"event": "done", "modules": 0, "completed": False})
            return

        headers = {"content-type": "application/json", "accept": "text/event-stream", "api-key": self.token}
        params = {
            "type": type,
            "query": query,
            "timeout": 60,
            "exact_match": True,
            "premium": premium,
            "premium_modules_only": premium_modules_only,
        }
        modules = 0
        completed = False
        timeout = aiohttp.ClientTimeout(total=180, sock_read=120)
        url = API_URL + (SANDBOX_STREAM_PATH if sandbox else STREAM_PATH)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, headers=headers, json=params) as resp:
                    if resp.status >= 400:
                        detail = _error_text(await resp.text()) or f"OSINT Industries returned HTTP {resp.status}"
                        yield _sse({"event": "error", "status": resp.status, "detail": detail})
                        yield _sse({"event": "done", "modules": 0, "completed": False})
                        return
                    buffer = ""
                    # iter_any + own splitting: one module can be a line longer than aiohttp's readline limit
                    async for chunk in resp.content.iter_any():
                        buffer += chunk.decode("utf-8", errors="replace")
                        *lines, buffer = buffer.split("\n")
                        for line in lines:
                            for event in self._stream_line(line):
                                if event.get("event") == "module":
                                    modules += 1
                                yield _sse(event)
                    for event in self._stream_line(buffer):
                        if event.get("event") == "module":
                            modules += 1
                        yield _sse(event)
                    completed = True
        except (aiohttp.ClientError, TimeoutError) as e:
            yield _sse({"event": "error", "detail": f"Connection to OSINT Industries failed: {e.__class__.__name__}"})
        yield _sse({"event": "done", "modules": modules, "completed": completed})

    @staticmethod
    def _stream_line(line: str) -> list:
        """One line of the upstream stream ("data:{json}" or a bare JSON line) -> our events."""
        line = line.strip()
        if line.startswith("data:"):
            line = line[5:].strip()
        if not line or line[0] not in "[{":
            return []
        try:
            data = json.loads(line)
        except ValueError:
            return []
        events = []
        for item in data if isinstance(data, list) else [data]:
            if not isinstance(item, dict):
                continue
            if item.get("module"):
                events.append({"event": "module", "module": item["module"], "cards": normalize_oi([item])})
            elif item.get("error"):
                events.append({"event": "error", "detail": str(item["error"])[:300]})
        return events

    async def get_credits(self):
        headers = {
            'api-key': self.token,
        }

        try:
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get('https://api.osint.industries/misc/credits', headers=headers) as resp:
                    if resp.status == 200:
                        credits = await resp.text()
                        return {"credits": credits}
                    else:
                        return {"credits": "Unavailable"}
        except Exception as e:
            print(f"Error fetching credits: {e}")
            return {"credits": "Error"}



# ---------------------------------------------------------------------------
# JSON results -> one flat card per account
# ---------------------------------------------------------------------------
# Response format (https://docs.osint.industries/reference/spec-format): a list of
# modules, each with parallel ``spec_format`` / ``front_schemas`` lists - one entry
# per account (several for "breach" and name searches). Every spec value is
# wrapped as {"type", "proper_key", "value"}; ``platform_variables`` holds the
# module-specific extras in the same shape plus a "key".

# Standard spec_format fields, mapped to card slots
OI_SLOTS = {
    "name": "name", "username": "username", "email": "email", "phone": "phone",
    "picture_url": "picture", "profile_url": "profile_url", "location": "location",
    "creation_date": "created", "last_seen": "last_seen", "website": "website",
    "id": "account_id", "gender": "gender", "bio": "bio", "age": "age",
}
# Modules whose site is not <module>.com (for the site icon)
OI_DOMAINS = {
    "maps": "maps.google.com", "twitter": "x.com", "office365": "office.com", "protonmail": "proton.me",
    "hibp": "haveibeenpwned.com", "yahoo": "yahoo.com", "microsoft": "microsoft.com", "outlook": "outlook.com",
    "skype": "skype.com", "xbox": "xbox.com", "imgur": "imgur.com", "lastpass": "lastpass.com",
    "kakao": "kakao.com", "naver": "naver.com", "vk": "vk.com", "ok": "ok.ru", "mailru": "mail.ru",
    "yandex": "yandex.ru", "wordpress": "wordpress.com", "zoho": "zoho.com", "bitmoji": "bitmoji.com",
}
# Shown by the card itself (or always true), never as extra fields
OI_SKIP = {"registered", "breach", "platform_variables", "first_name", "last_name"}
ISO_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")


def _plain(raw):
    """{"value": x, "type": "datetime"} -> display value; None for nested data."""
    kind = raw.get("type") if isinstance(raw, dict) else None
    value = raw.get("value") if isinstance(raw, dict) and "value" in raw else raw
    if isinstance(value, list):
        items = [str(v) for v in value if isinstance(v, (str, int, float)) and not isinstance(v, bool)]
        return ", ".join(items) if items and len(items) == len(value) else None
    if isinstance(value, dict) or value in (None, ""):
        return None
    if isinstance(value, str) and (kind == "datetime" or ISO_DATETIME.match(value)):
        return value[:16].replace("T", " ")
    return value


def _oi_card(item: dict, spec: dict, front: dict) -> dict:
    slug = str(item.get("module") or "unknown")
    category = item.get("category")
    card = {
        "module": str(front.get("module") or slug),
        "slug": slug,
        "category": category.get("name") if isinstance(category, dict) else None,
        "breach": slug == "breach" or _plain(spec.get("breach")) is True,
        "fields": [],
    }
    card["domain"] = (
        domain_from_url(_plain(spec.get("profile_url")))
        or (domain_from_url(_plain(spec.get("website"))) if card["breach"] else None)
        or OI_DOMAINS.get(slug)
        or (domain_from_url(f"{slug}.com") if not card["breach"] and slug.isalnum() else None)
    )
    if not card["breach"] and _plain(spec.get("registered")) is False:
        card["registered"] = False
    shown = set()
    for key, raw in spec.items():
        if key in OI_SKIP:
            continue
        value = _plain(raw)
        if value is None:
            continue
        slot = OI_SLOTS.get(key)
        if slot:
            card[slot] = value
        else:
            card["fields"].append({"label": raw.get("proper_key") if isinstance(raw, dict) else key, "value": value})
        if isinstance(value, str):
            shown.add(value)
    for var in spec.get("platform_variables") or []:
        if not isinstance(var, dict):
            continue
        value = _plain(var)
        # Breach entries repeat their name/logo/date as variables
        if value is None or value in shown:
            continue
        card["fields"].append({"label": var.get("proper_key") or var.get("key") or "", "value": value})
        if isinstance(value, str):
            shown.add(value)
    for field in card["fields"]:
        if not field["label"]:
            field["label"] = "value"
        elif "_" in field["label"]:
            field["label"] = field["label"].replace("_", " ")
    return card


def normalize_oi(data) -> list:
    items = data if isinstance(data, list) else (
        (data.get("data") or data.get("results") or []) if isinstance(data, dict) else [])
    cards = []
    for item in items:
        if not isinstance(item, dict) or item.get("status", "found") != "found":
            continue
        specs = item.get("spec_format") if isinstance(item.get("spec_format"), list) else []
        fronts = item.get("front_schemas") if isinstance(item.get("front_schemas"), list) else []
        for i, spec in enumerate(specs):
            if isinstance(spec, dict):
                front = fronts[i] if i < len(fronts) and isinstance(fronts[i], dict) else {}
                cards.append(_oi_card(item, spec, front))
    return sort_oi_cards(cards)


def sort_oi_cards(cards: list) -> list:
    """Breaches first, then accounts with the most detail."""
    return sorted(cards, key=lambda c: (not c.get("breach"), -len(c) - len(c.get("fields") or [])))
