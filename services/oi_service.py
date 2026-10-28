import os
import uuid
import aiohttp
from fastapi.responses import JSONResponse

from dotenv import load_dotenv
from utils.config import get_setting

load_dotenv()

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

# Field names OSINT Industries uses in spec_format, mapped to card slots
OI_SLOTS = {
    "name": "name", "username": "username", "email": "email", "phone": "phone",
    "picture_url": "picture", "profile_url": "profile_url", "location": "location",
    "creation_date": "created", "last_seen": "last_seen", "registered": "registered",
    "id": "account_id", "gender": "gender", "language": "language", "bio": "bio",
}


def _plain(value):
    """{"value": x, "proper_key": "Label"} -> x"""
    return value.get("value") if isinstance(value, dict) and "value" in value else value


def normalize_oi(data) -> list:
    items = data if isinstance(data, list) else (
        (data.get("data") or data.get("results") or [data]) if isinstance(data, dict) else [])
    cards = []
    for item in items:
        if not isinstance(item, dict):
            continue
        module = str(item.get("module") or item.get("platform") or item.get("name") or "unknown")
        specs = item.get("spec_format") if isinstance(item.get("spec_format"), list) else [item]
        for spec in specs:
            if not isinstance(spec, dict):
                continue
            card = {"module": module, "fields": []}
            for key, raw in spec.items():
                if key in ("platform_variables", "spec_format", "front_schemas", "module"):
                    continue
                value = _plain(raw)
                if value in (None, "", [], {}) or isinstance(value, (dict, list)):
                    continue
                slot = OI_SLOTS.get(key)
                if slot:
                    card[slot] = value
                else:
                    label = raw.get("proper_key") if isinstance(raw, dict) else None
                    card["fields"].append({"label": label or key.replace("_", " "), "value": value})
            for var in spec.get("platform_variables") or []:
                if isinstance(var, dict) and var.get("value") not in (None, "", [], {}):
                    value = var["value"]
                    card["fields"].append({
                        "label": var.get("proper_key") or var.get("key") or "",
                        "value": value if isinstance(value, (str, int, float, bool)) else str(value),
                    })
            if card.get("registered") is False and len(card) <= 3 and not card["fields"]:
                continue  # "not registered" with nothing else is noise
            cards.append(card)
    return cards
