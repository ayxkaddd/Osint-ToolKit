"""Identifiers (entities) an investigator pivots on.

Two jobs:
* ``detect(query)`` - what kind of identifier did the user paste into the
  search box (email, phone, @username, domain, IP, ...)?
* ``extract_entities(result)`` - which identifiers appear in a module result
  (so they can be listed, triaged and looked up with other modules).

Extraction is key-aware (a value under "email" is an email, under "username"
a username) plus conservative free-text matching (emails, URLs, "+"-prefixed
phone numbers) - usernames and bare numbers are never guessed from free text.
"""
import ipaddress
import re
from dataclasses import dataclass
from typing import Any, Optional
from collections.abc import Iterable
from urllib.parse import urlparse

import phonenumbers

ENTITY_TYPES = {
    "email": "Email",
    "phone": "Phone",
    "username": "Username",
    "domain": "Domain",
    "ip": "IP address",
    "url": "URL",
    "telegram_id": "Telegram ID",
    "telegram_username": "Telegram @username",
    "vk": "VK profile",
    "gaia_id": "Google Gaia ID",
    "bssid": "Wi-Fi BSSID",
    "crypto_btc": "Bitcoin address",
    "crypto_eth": "Ethereum address",
    "text": "Free text",
}

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}")
URL_RE = re.compile(r"https?://[^\s<>\"'`{}|\\^\[\]]+", re.I)
DOMAIN_RE = re.compile(r"^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$")
USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$")
BSSID_RE = re.compile(r"^[0-9A-Fa-f]{2}([:-][0-9A-Fa-f]{2}){5}$")
PHONE_TEXT_RE = re.compile(r"\+\d[\d\s().-]{7,18}\d")
BTC_RE = re.compile(r"^(bc1[a-z0-9]{25,62}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})$")
ETH_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")

# Infrastructure / boilerplate that is never a lead
NOISE_DOMAINS = {
    "example.com", "example.org", "localhost", "w3.org", "schema.org", "gstatic.com", "googleapis.com",
    "googleusercontent.com", "googletagmanager.com", "google-analytics.com", "doubleclick.net",
    "cloudflare.com", "cloudflare-dns.com", "cloudfront.net", "akamaihd.net", "fastly.net", "jsdelivr.net",
    "unpkg.com", "cdnjs.cloudflare.com", "gravatar.com", "fbcdn.net", "twimg.com", "ytimg.com",
    "userapi.com", "vk.me", "icann.org", "iana.org", "verisign.com", "whois.icann.org", "rdap.org",
    "markmonitor.com", "godaddy.com", "namecheap.com", "domainsbyproxy.com", "withheldforprivacy.com",
}
NOISE_EMAIL_LOCALS = {"abuse", "noreply", "no-reply", "donotreply", "privacy", "hostmaster", "postmaster",
                      "dnsadmin", "domainabuse", "abuse-contact", "support", "whois", "registrar"}
# Only filtered when *found* in results (you can still search for them): mail
# providers and platforms show up everywhere and are never leads by themselves
PLATFORM_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "outlook.com", "hotmail.com", "live.com", "icloud.com", "me.com",
    "mail.ru", "bk.ru", "list.ru", "inbox.ru", "yandex.ru", "ya.ru", "yandex.com", "ukr.net", "i.ua", "meta.ua",
    "proton.me", "protonmail.com", "pm.me", "tutanota.com", "gmx.com", "gmx.net", "aol.com", "zoho.com",
    "github.com", "users.noreply.github.com", "gitlab.com", "google.com", "youtube.com", "facebook.com",
    "instagram.com", "twitter.com", "x.com", "t.me", "telegram.me", "vk.com", "ok.ru", "linkedin.com",
    "tiktok.com", "reddit.com", "wikipedia.org", "apple.com", "microsoft.com", "amazonaws.com",
}
NOISE_USERNAMES = {"noreply", "no-reply", "web-flow", "github-actions", "dependabot", "actions-user",
                   "root", "test", "guest", "anonymous", "support", "info", "contact"}
IMAGE_EXT_RE = re.compile(r"\.(png|jpe?g|gif|svg|webp|ico|bmp|css|js|woff2?)(\?|$)", re.I)

# Keys whose values are raw blobs (WHOIS rawText, HTML...) - too noisy to scan
SKIP_KEY_RE = re.compile(r"raw|html|jarm|hash|favicon|signature|token|cookie|header|query_image", re.I)

# Endings that make a dotted word a site rather than a handle (detect)
COMMON_TLDS = {
    "com", "net", "org", "io", "co", "info", "biz", "me", "app", "dev", "xyz", "online", "site", "top", "shop",
    "club", "pro", "tv", "cc", "ai", "gg", "to", "ly", "edu", "gov", "mil", "int", "eu", "us", "uk", "de", "fr",
    "ru", "su", "ua", "by", "kz", "pl", "nl", "it", "es", "pt", "se", "no", "fi", "dk", "ch", "at", "be", "cz",
    "ro", "gr", "tr", "il", "ir", "in", "cn", "jp", "kr", "au", "nz", "ca", "br", "mx", "ar", "za", "id", "vn",
}

MAX_STRINGS = 50_000
MAX_ENTITIES_PER_RESULT = 3_000


@dataclass(frozen=True)
class Entity:
    type: str
    value: str          # normalized, used for identity
    display: str = ""   # as it should be shown

    @property
    def key(self) -> str:
        return f"{self.type}:{self.value}"


# ---------------------------------------------------------------------------
# Normalizers: return the canonical value or None if not a usable identifier.
#
# Identifiers *found* in results are filtered for noise (example.com, abuse@...,
# private IPs, "admin"): they are boilerplate there. What the user *typed* is
# never noise - with ``typed=True`` a value only has to have the right shape.
# ---------------------------------------------------------------------------

def norm_email(value: str, typed: bool = False) -> Optional[str]:
    value = (value or "").strip().strip(".,;:()<>[]\"'").lower()
    if value.startswith("mailto:"):
        value = value[7:]
    if not EMAIL_RE.fullmatch(value):
        return None
    if typed:
        return value
    local, _, domain = value.partition("@")
    if any(noise in local for noise in NOISE_EMAIL_LOCALS) or domain in NOISE_DOMAINS \
            or "redacted" in value or any(w in domain for w in ("privacy", "proxy", "whoisguard")) \
            or domain.endswith("noreply.github.com"):
        return None
    return value


def norm_phone(value: str, assume_international: bool = False) -> Optional[str]:
    raw = (value or "").strip()
    digits = re.sub(r"[^\d+]", "", raw)
    if not digits:
        return None
    if not digits.startswith("+"):
        if not assume_international:
            return None
        digits = "+" + digits.lstrip("0") if not digits.startswith("00") else "+" + digits[2:]
    try:
        number = phonenumbers.parse(digits, None)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(number):
        return None
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


def norm_domain(value: str, typed: bool = False) -> Optional[str]:
    value = (value or "").strip().lower().rstrip(".")
    value = re.sub(r"^https?://", "", value).split("/")[0].split(":")[0]
    if value.startswith("www."):
        value = value[4:]
    if not DOMAIN_RE.match(value):
        return None
    if typed:
        return value
    if value in NOISE_DOMAINS or any(value.endswith("." + d) for d in NOISE_DOMAINS):
        return None
    return value


def norm_ip(value: str, typed: bool = False) -> Optional[str]:
    try:
        ip = ipaddress.ip_address((value or "").strip())
    except ValueError:
        return None
    if typed:
        return str(ip)
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
        return None
    return str(ip)


def norm_url(value: str, typed: bool = False) -> Optional[str]:
    value = (value or "").strip().rstrip(".,;:)]}>\"'")
    if not re.match(r"^https?://", value, re.I):
        return None
    try:
        host = urlparse(value).hostname or ""
    except ValueError:   # e.g. a broken [IPv6] host
        return None
    if typed:
        return value if host and len(value) <= 2000 else None
    if len(value) > 500 or IMAGE_EXT_RE.search(value):
        return None
    if not host or norm_domain(host) is None:
        return None
    return value


def norm_username(value: str, typed: bool = False) -> Optional[str]:
    value = (value or "").strip().lstrip("@")
    if not USERNAME_RE.match(value) or value.isdigit() or "@" in value:
        return None
    if typed:
        return value
    if value.lower() in {"null", "none", "undefined", "unknown", "admin", "user", "true", "false"}:
        return None
    return value


def norm_telegram_id(value: Any) -> Optional[str]:
    text = str(value).strip()
    if not re.fullmatch(r"\d{5,12}", text):
        return None
    return text


# Types whose normalizer drops noise (and so takes ``typed``)
NOISE_FILTERED = {"email", "domain", "ip", "url", "username", "telegram_username"}

NORMALIZERS = {
    "email": norm_email,
    "phone": lambda v: norm_phone(v, assume_international=True),
    "domain": norm_domain,
    "ip": norm_ip,
    "url": norm_url,
    "username": norm_username,
    "telegram_username": norm_username,
    "telegram_id": norm_telegram_id,
    "vk": lambda v: (str(v).strip() or None),
    "gaia_id": lambda v: str(v).strip() if re.fullmatch(r"\d{15,25}", str(v).strip()) else None,
    "bssid": lambda v: str(v).strip().replace("-", ":").upper() if BSSID_RE.match(str(v).strip()) else None,
    "crypto_btc": lambda v: str(v).strip() if BTC_RE.match(str(v).strip()) else None,
    "crypto_eth": lambda v: str(v).strip().lower() if ETH_RE.match(str(v).strip()) else None,
    "text": lambda v: (str(v).strip() or None),
}


def make_entity(entity_type: str, value: Any, display: Optional[str] = None,
                typed: bool = False) -> Optional[Entity]:
    """The identifier, or None if the value isn't one. ``typed``: the user entered it
    (search box, a lookup's target, a reference in a note), so it is kept even if it
    would be noise inside a result."""
    normalizer = NORMALIZERS.get(entity_type)
    if normalizer is None or value is None or isinstance(value, (dict, list, bool)):
        return None
    if typed and entity_type in NOISE_FILTERED:
        normalized = normalizer(str(value), typed=True)
    else:
        normalized = normalizer(str(value))
    if not normalized:
        return None
    return Entity(entity_type, normalized, display or (normalized if entity_type != "phone" else str(value).strip()))


# ---------------------------------------------------------------------------
# Detection of a search-box query
# ---------------------------------------------------------------------------

def detect(query: str) -> list[Entity]:
    """Likely interpretations of a pasted query, most likely first."""
    q = (query or "").strip()
    if not q:
        return []
    found: list[Entity] = []

    def add(entity_type: str, value: Any, display: Optional[str] = None):
        entity = make_entity(entity_type, value, display, typed=True)
        if entity and entity not in found:
            found.append(entity)

    lowered = q.lower()
    # Profile links first: they say exactly what they are
    if re.search(r"(^|//|\.)vk\.(com|ru)/", lowered):
        match = re.search(r"vk\.(?:com|ru)/([A-Za-z0-9_.]+)", q)
        if match:
            name = match.group(1)
            add("vk", name[2:] if re.fullmatch(r"id\d+", name) else name, q)
    if re.search(r"(^|//)(t\.me|telegram\.me)/", lowered):
        match = re.search(r"(?:t|telegram)\.me/([A-Za-z0-9_]{4,32})", q)
        if match:
            add("telegram_username", match.group(1))
    if re.search(r"(^|//)(www\.)?github\.com/", lowered):
        match = re.search(r"github\.com/([A-Za-z0-9-]{1,39})", q)
        if match:
            add("username", match.group(1))
    if q.startswith("@"):
        add("telegram_username", q[1:])
        add("username", q[1:])

    if "@" in q and not q.startswith("@"):
        add("email", q)
    if re.match(r"^https?://", q, re.I):
        add("url", q)
        try:
            host = urlparse(q).hostname or ""
        except ValueError:
            host = ""
        add("ip", host)       # http://203.0.113.5/admin
        add("domain", host)
    add("ip", q)
    add("bssid", q)
    add("crypto_eth", q)
    if not q.isdigit():
        add("crypto_btc", q)

    digits = re.sub(r"[\s().-]", "", q)
    if re.fullmatch(r"\+?\d{7,15}", digits):
        add("phone", digits)
    if re.fullmatch(r"\d{15,25}", q):
        add("gaia_id", q)
    if re.fullmatch(r"\d{5,12}", q):
        add("telegram_id", q)
        add("vk", q)
    if " " not in q and "." in q and not q.replace(".", "").isdigit():
        add("domain", q)
    strong = {e.type for e in found} & {"email", "phone", "url", "ip", "bssid", "gaia_id", "crypto_btc", "crypto_eth", "vk"}
    if not strong and (not found or (not q.isdigit() and " " not in q and "." not in q and "@" not in q)):
        add("username", q)
    # "john.doe" has the shape of a domain, but is far more often a handle: offered as
    # the second reading unless it ends like a site (john.com stays a domain only)
    if [e.type for e in found] == ["domain"] and q.count(".") == 1 and "/" not in q \
            and q.rsplit(".", 1)[1].lower() not in COMMON_TLDS:
        add("username", q)
    if " " in q and not strong:
        add("text", q)
    return found


# Countries tried for a number typed without its country code, most likely first
# (the reader's own countries, from the browser's languages, go before these).
# A short list on purpose: every country tried loads its numbering plan.
PHONE_REGIONS = {
    "US": "United States / Canada", "RU": "Russia", "UA": "Ukraine", "GB": "United Kingdom", "DE": "Germany",
    "FR": "France", "PL": "Poland", "IT": "Italy", "ES": "Spain", "NL": "Netherlands", "TR": "Turkey",
    "KZ": "Kazakhstan", "BY": "Belarus", "IN": "India", "BR": "Brazil", "MX": "Mexico", "AU": "Australia",
    "CN": "China", "JP": "Japan", "ID": "Indonesia", "NG": "Nigeria", "ZA": "South Africa", "AE": "UAE",
    "IL": "Israel",
}
PHONE_SUGGESTIONS_MAX = 5
NATIONAL_PHONE_RE = re.compile(r"[\d\s().-]+")


def phone_suggestions(query: str, prefer: Iterable[str] = ()) -> list[dict[str, str]]:
    """Full numbers a phone number typed *without* a country code could be.

    "(415) 555-2671" is a phone number, but which one depends on the country, and a
    guess would look up somebody else. So nothing is assumed: each reading that is a
    valid number in a likely country is offered and the user picks. ``prefer``: region
    codes to try first (e.g. from Accept-Language). [] if the query has a + or 00
    prefix, already is a full number, or isn't number-shaped.
    """
    q = (query or "").strip()
    digits = re.sub(r"\D", "", q)
    if not NATIONAL_PHONE_RE.fullmatch(q) or not 7 <= len(digits) <= 15 or digits.startswith("00"):
        return []
    if norm_phone(digits, assume_international=True):
        return []   # country code included, only the + is missing: detect() reads it
    regions = [r.upper() for r in prefer if r and r.upper() in phonenumbers.SUPPORTED_REGIONS]
    out: dict[str, dict[str, str]] = {}
    for region in dict.fromkeys([*regions, *PHONE_REGIONS]):
        try:
            number = phonenumbers.parse(q, region)
        except phonenumbers.NumberParseException:
            continue
        if not phonenumbers.is_valid_number(number):
            continue
        e164 = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
        if e164 in out:
            continue
        actual = phonenumbers.region_code_for_number(number) or region
        out[e164] = {
            "type": "phone", "value": e164,
            "display": phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.INTERNATIONAL),
            "region": actual, "country": PHONE_REGIONS.get(actual, actual),
        }
        if len(out) >= PHONE_SUGGESTIONS_MAX:
            break
    return list(out.values())


# ---------------------------------------------------------------------------
# Extraction from results
# ---------------------------------------------------------------------------

def _key_hint(key: str) -> Optional[str]:
    k = key.lower()
    if "email" in k or k in ("mail", "e-mail"):
        return "email"
    if any(h in k for h in ("phone", "msisdn", "mobile", "tel")) and "hotel" not in k:
        return "phone"
    if k in ("vk_id", "vkid"):
        return "vk"
    if "gaia" in k or k == "personid":
        return "gaia_id"
    if k in ("bssid",):
        return "bssid"
    if k in ("ip", "ip_address", "ipaddress", "ip_addr", "a"):
        return "ip"
    if k in ("domain", "domains", "hostname", "hostnames", "host", "hosts", "input", "name_servers", "nameservers",
             "subdomain", "subdomains") or k.endswith(("_domain", "_domains")):
        return "domain"
    if k in ("url", "link", "profile", "profile_url", "href", "website", "blog", "html_url", "uri"):
        return "url"
    if k in ("username", "user_name", "login", "screen_name", "nickname", "handle", "usernames"):
        return "username"
    return None


def _service_hints(service: str, parent: dict[str, Any], key: str) -> Optional[str]:
    """Context that turns an ambiguous value into a typed identifier."""
    k = key.lower()
    if service == "funstat":
        if k == "id" and ("first_name" in parent or "username" in parent) and "title" not in parent:
            return "telegram_id"
        if k == "username" and "title" not in parent:
            return "telegram_username"
    if service in ("face_search",) and k == "vk_id":
        return "vk"
    if service == "vk_profile" and k == "username":
        return "vk"
    return None


def is_noise(entity: Entity) -> bool:
    """Boilerplate that appears in results but is never a lead by itself."""
    if entity.type == "domain":
        return entity.value in PLATFORM_DOMAINS or any(entity.value.endswith("." + d) for d in PLATFORM_DOMAINS)
    if entity.type in ("username", "telegram_username"):
        return entity.value.lower() in NOISE_USERNAMES
    return False


# Keys naming a person's or company's own website (its domain is a lead too)
OWN_SITE_KEYS = {"blog", "website", "homepage", "web", "site", "personal_website"}

# Bulk data that would bury the leads (every probed subdomain of a big site)
SERVICE_SKIP_KEYS = {
    "dns_recon": {"httpx_results", "httpx_data", "subdomains", "hosts", "detected_urls"},
    "oi": {"raw"},  # the same data is in "modules", flattened
}


def extract_entities(result: Any, service: str = "") -> list[tuple[Entity, str]]:
    """(entity, json path) pairs found in a result payload."""
    out: dict[str, tuple[Entity, str]] = {}
    if isinstance(result, dict) and result.get("kind") == "plugin_result":
        # card pictures and icons are never leads
        result = {**result, "items": [{k: v for k, v in item.items() if k not in ("image", "icon")}
                                      for item in result.get("items") or [] if isinstance(item, dict)]}

    # Identifiers the user listed when adding a result by hand are theirs, never noise
    by_hand = isinstance(result, dict) and result.get("kind") == "manual"

    def add(entity: Optional[Entity], path: str, typed: bool = False):
        if entity and entity.key not in out and len(out) < MAX_ENTITIES_PER_RESULT and (typed or not is_noise(entity)):
            out[entity.key] = (entity, path)
            # an email's domain (a company or personal domain) is a lead of its own;
            # free mail providers are dropped by is_noise
            if entity.type == "email":
                add(make_entity("domain", entity.value.rsplit("@", 1)[1]), path)

    # Typed values with their parent dict (for service hints)
    def visit(value: Any, path: str, depth: int):
        if depth > 10 or len(out) >= MAX_ENTITIES_PER_RESULT:
            return
        if isinstance(value, dict):
            for k, v in value.items():
                k = str(k)
                if SKIP_KEY_RE.search(k) or k in SERVICE_SKIP_KEYS.get(service, ()):
                    continue
                sub = f"{path}.{k}" if path else k
                if k == "entities" and isinstance(v, dict) and set(v) <= set(ENTITY_TYPES):
                    # plugin cards list their identifiers by type
                    for entity_type, values in v.items():
                        for i, item in enumerate(values if isinstance(values, list) else [values]):
                            add(make_entity(entity_type, item, typed=by_hand), f"{sub}.{entity_type}[{i}]", by_hand)
                    continue
                add(make_entity("email", k), sub)  # emails used as dict keys (GitFive)
                hint = _service_hints(service, value, k) or _key_hint(k)
                if hint and not isinstance(v, (dict, list)):
                    add(make_entity(hint, v), sub)
                    if k.lower() in OWN_SITE_KEYS and isinstance(v, str):   # someone's own site: its domain too
                        add(make_entity("domain", urlparse(v if "//" in v else f"http://{v}").hostname or ""), sub)
                elif hint and isinstance(v, list):
                    for i, item in enumerate(v[:500]):
                        if not isinstance(item, (dict, list)):
                            add(make_entity(hint, item), f"{sub}[{i}]")
                visit(v, sub, depth + 1)
        elif isinstance(value, list):
            for i, v in enumerate(value[:5000]):
                visit(v, f"{path}[{i}]", depth + 1)
        elif isinstance(value, str):
            scan_text(value, path)

    scanned = [0]

    def scan_text(text: str, path: str):
        if scanned[0] >= MAX_STRINGS or len(text) < 6:
            return
        scanned[0] += 1
        for m in EMAIL_RE.finditer(text):
            add(make_entity("email", m.group(0)), path)
        for m in URL_RE.finditer(text):
            url = make_entity("url", m.group(0))
            add(url, path)
        for m in PHONE_TEXT_RE.finditer(text):
            phone = norm_phone(m.group(0))
            if phone:
                add(Entity("phone", phone, m.group(0).strip()), path)

    visit(result, "", 0)
    return list(out.values())


def entities_from_parameters(parameters: dict[str, Any], service: str = "") -> list[Entity]:
    """The identifier(s) a lookup was run on (its query/target)."""
    kwargs = (parameters or {}).get("kwargs", parameters or {})
    if not isinstance(kwargs, dict):
        return []
    flat: dict[str, Any] = {}
    for k, v in kwargs.items():
        if isinstance(v, dict):
            flat.update(v)
        else:
            flat[k] = v

    typed = {
        "email": "email", "phone": "phone", "phones": "phone", "domain": "domain", "ip": "ip",
        "gaia_id": "gaia_id", "bssid": "bssid", "drive_url": "url", "link": "url", "url": "url",
    }
    found: list[Optional[Entity]] = []
    for key, entity_type in typed.items():
        value = flat.get(key)
        if value:
            for part in re.split(r"[,;\n]+", str(value)) if entity_type == "phone" else [value]:
                entity = make_entity(entity_type, part, typed=True)
                if entity:
                    found.append(entity)

    username = flat.get("username")
    if username:
        if service == "funstat":
            found.append(make_entity("telegram_username", username, typed=True))
        found.append(make_entity("username", username, typed=True))
    if service == "funstat":
        for key in ("id", "user_id"):
            if flat.get(key) is not None:
                values = flat[key] if isinstance(flat[key], list) else [flat[key]]
                found.extend(make_entity("telegram_id", v) for v in values)
        if flat.get("name"):
            names = flat["name"] if isinstance(flat["name"], list) else [flat["name"]]
            found.extend(make_entity("telegram_username", n, typed=True) for n in names)
    if service == "vk_profile" and flat.get("user_id"):
        found.append(make_entity("vk", flat["user_id"]))
    if service in ("oi", "cavalier", "web_search") and (flat.get("query") or flat.get("value")):
        for candidate in detect(str(flat.get("query") or flat.get("value"))):
            found.append(candidate)
            break
    if flat.get("plugin_id") and flat.get("value"):   # plugins: the type is optional
        if flat.get("type") in ENTITY_TYPES:
            found.append(make_entity(flat["type"], flat["value"], typed=True))
        else:
            found.extend(detect(str(flat["value"]))[:1])
    if service == "ns":
        for key in ("ns1", "ns2"):
            if flat.get(key):
                found.append(make_entity("domain", flat[key], typed=True))
    seen, unique = set(), []
    for entity in found:
        if entity and entity.key not in seen:
            seen.add(entity.key)
            unique.append(entity)
    return unique


def type_label(entity_type: str) -> str:
    return ENTITY_TYPES.get(entity_type, entity_type)


def iter_types() -> Iterable[tuple[str, str]]:
    return ENTITY_TYPES.items()
