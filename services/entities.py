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
import csv
import io
import ipaddress
import re
import unicodedata
from collections import Counter
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
    "name": "Name",
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
# "your_username", "email_username" ...: not the owner's username on a service
NOT_OWNER_PREFIXES = {"your", "viewer", "current", "logged", "my", "email", "mail", "author", "editor", "owner"}
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


# ---------------------------------------------------------------------------
# Names of people: "John Smith", "Іван Петренко", "ПЕТРОВ Иван Иванович"
# ---------------------------------------------------------------------------

NAME_WORD_RE = re.compile(r"[^\W\d_]+(?:['’ʼ-][^\W\d_]+)*")     # letters of any alphabet, O'Brien, Анна-Марія
NAME_INITIAL_RE = re.compile(r"[^\W\d_]\.")                     # "J."
NAME_PARTICLES = {"van", "von", "de", "da", "di", "del", "della", "der", "den", "la", "le", "du", "dos", "das",
                  "bin", "ibn", "al", "el", "ben", "y", "zu", "ter", "ten"}
# Words that make two capitalised words something other than a person (results only)
NAME_NOISE_WORDS = {
    "privacy", "private", "redacted", "protected", "protection", "protect", "proxy", "whois", "domain", "domains",
    "admin", "administrator", "administration", "registrar", "registrant", "registration", "contact", "contacts",
    "data", "disclosed", "withheld", "hidden", "unknown", "none", "null", "undefined", "user", "users", "deleted",
    "account", "anonymous", "telegram", "google", "facebook", "support", "team", "service", "services", "company",
    "group", "llc", "inc", "ltd", "gmbh", "corp", "corporation", "limited", "holding", "holdings", "foundation",
    "bank", "university", "school", "official", "news", "shop", "store", "online", "media", "studio", "agency",
    "club", "channel", "chat", "bot", "the", "and", "of", "for", "test", "demo", "example", "sample", "street",
    "ооо", "тов", "пао", "оао", "зао", "ао", "ип", "фоп", "бот", "канал", "чат", "группа", "група", "новости",
    "новини", "компания", "компанія", "магазин", "банк", "админ", "адмін", "администратор", "адміністратор",
    "поддержка", "підтримка", "служба", "улица", "вулиця", "пользователь", "користувач", "удален", "видалений",
    # headings in pasted text
    "information", "info", "details", "personal", "address", "location", "results", "result", "report",
    "summary", "profile", "page", "social", "networks", "found", "search", "number", "phone", "email",
    "информация", "інформація", "данные", "дані", "результат", "результаты", "результати", "адрес", "адреса",
    "профиль", "профіль", "найдено", "знайдено", "поиск", "пошук", "телефон", "номер", "почта", "пошта",
}


def _script(ch: str) -> str:
    try:
        return unicodedata.name(ch).split(" ", 1)[0]     # LATIN, CYRILLIC, GREEK...
    except ValueError:
        return ""


def _name_case(word: str, first: bool) -> str:
    """IVAN / ivan -> Ivan (O'BRIEN -> O'Brien); mixed case (McDonald) and particles stay."""
    if not first and word.lower() in NAME_PARTICLES:
        return word.lower()
    if word.isupper() and len(word) > 2 or word.islower():
        return re.sub(r"[^\W\d_]+", lambda m: m.group(0).capitalize(), word)
    return word


def norm_name(value: str, typed: bool = False, prose: bool = False) -> Optional[str]:
    """A person's name: 2-4 words of letters (one alphabet), initials allowed.

    ``typed``: entered by the user - only the shape counts. Otherwise (found in a
    result) words like "Privacy", "LLC", "ТОВ" rule it out, and with ``prose`` (no
    field name says it is a name) every word must also start with a capital."""
    text = re.sub(r"\s+", " ", str(value or "")).strip(" ,;:()[]{}\"'«»“”")
    if not 3 <= len(text) <= 80:
        return None
    words = text.split(" ")
    if not 2 <= len(words) <= 4:
        return None
    full = [w for w in words if not NAME_INITIAL_RE.fullmatch(w)]
    if len(full) < 2 or not all(NAME_WORD_RE.fullmatch(w) for w in full):
        return None
    if len({_script(c) for c in text if c.isalpha()}) > 1:   # no look-alike Latin/Cyrillic mixes
        return None
    lowered = [w.lower().rstrip(".") for w in words]
    if not typed:
        if NAME_NOISE_WORDS.intersection(lowered) or all(w in NAME_PARTICLES for w in lowered):
            return None
        if any(len(w) < 2 for w in full):
            return None
        if prose and any(not w[0].isupper() for w, low in zip(words, lowered, strict=True) if low not in NAME_PARTICLES):
            return None
    return " ".join(_name_case(w, i == 0) for i, w in enumerate(words))


# Types whose normalizer drops noise (and so takes ``typed``)
NOISE_FILTERED = {"email", "domain", "ip", "url", "username", "telegram_username", "name"}

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
    "name": norm_name,
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
        add("name", q)      # "Іван Петренко", "john smith"
        add("text", q)
    return found


def browser_regions(accept_language: Optional[str]) -> list[str]:
    """Countries of the browser's languages ("en-US,ru-RU;q=0.9" -> US, RU), likeliest first."""
    regions = []
    for part in (accept_language or "").split(","):
        tag = part.split(";")[0].strip()
        if "-" in tag:
            region = tag.rsplit("-", 1)[1].upper()
            if len(region) == 2 and region.isalpha() and region not in regions:
                regions.append(region)
    return regions[:5]


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
    if k.endswith(("_username", "_screen_name")) and k.split("_", 1)[0] not in NOT_OWNER_PREFIXES:
        return "username"   # twitter_username: the owner's username on that service
    if k in NAME_KEYS:
        return "name"
    return None


# Fields that hold a person's whole name ("name" alone is too often a site, a file
# or a company: it counts only next to fields a person has, see PERSON_FIELDS)
NAME_KEYS = {"full_name", "fullname", "display_name", "displayname", "real_name", "realname", "person_name",
             "owner_name", "registrant_name", "contact_name", "holder_name", "account_holder", "cardholder",
             "sender_name", "author_name", "committer_name", "normalized_name", "fio", "names"}
PERSON_FIELDS = {"email", "emails", "phone", "phones", "telephone", "username", "login", "first_name", "last_name",
                 "birthday", "birth_date", "bdate", "dob", "gender", "sex", "avatar", "avatar_url", "photo", "bio",
                 "about", "street", "address", "organization", "organisation", "job_title", "followers"}
FIRST_NAME_KEYS = {"first_name", "firstname", "given_name", "givenname", "forename"}
LAST_NAME_KEYS = {"last_name", "lastname", "family_name", "familyname", "surname"}


# ---------------------------------------------------------------------------
# Text added by hand (manual results): "Label: value" lines in English, Ukrainian
# or Russian, phone numbers written without "+", tables (CSV) read by their headers
# ---------------------------------------------------------------------------

LABEL_HINTS = {
    **{k: "phone" for k in ("телефон", "тел", "моб", "мобильный", "мобільний", "мобилка", "номер", "номер телефона",
                            "номер телефону", "phone number", "cell", "mob", "whatsapp", "viber", "telephone")},
    **{k: "email" for k in ("почта", "пошта", "эл почта", "ел пошта", "електронна пошта", "электронная почта",
                            "e-mail", "mail", "емейл", "имейл", "email address", "мейл")},
    **{k: "name" for k in ("фио", "ф и о", "піб", "п і б", "full name", "name", "имя и фамилия", "ім'я та прізвище",
                           "ім'я і прізвище", "прізвище та ім'я", "фамилия и имя", "owner", "власник", "владелец",
                           "holder", "sender", "отправитель", "відправник", "получатель", "одержувач",
                           "person", "особа", "лицо", "клиент", "клієнт", "абонент", "subscriber",
                           "ф и о (нормал)", "ф и")},
    **{k: "username" for k in ("логин", "логін", "ник", "нік", "никнейм", "нікнейм", "nick", "user")},
    **{k: "telegram_username" for k in ("телеграм", "telegram", "tg", "тг")},
}
FIRST_NAME_LABELS = FIRST_NAME_KEYS | {"имя", "ім'я", "імя", "first name", "given name"}
LAST_NAME_LABELS = LAST_NAME_KEYS | {"фамилия", "прізвище", "last name", "family name"}


def _label(text: str) -> str:
    """ "  E-Mail.  " -> "e-mail", "Ім’я" -> "ім'я", "full_name" -> "full name" """
    text = re.sub(r"[’ʼ`]", "'", str(text)).lower().replace("_", " ").replace(".", " ")
    return re.sub(r"\s+", " ", text).strip(" :-*•")


def _label_hint(label: str) -> Optional[str]:
    k = _label(label)
    if k in FIRST_NAME_LABELS or k.replace(" ", "_") in FIRST_NAME_LABELS:
        return "first_name"
    if k in LAST_NAME_LABELS or k.replace(" ", "_") in LAST_NAME_LABELS:
        return "last_name"
    return LABEL_HINTS.get(k) or _key_hint(k.replace(" ", "_"))


LABEL_LINE_RE = re.compile(r"^[ \t]*[-*•]?[ \t]*([^\W\d][^:：\n]{0,38}?)[ \t]*[:：][ \t]*(\S[^\n]*?)[ \t]*$", re.M)
# A phone number without "+": 00 380 ..., 380671234567, 067 123 45 67, 8 (916) 123-45-67
LOOSE_PHONE_RE = re.compile(r"(?<![\w+/.:@-])\(?\d[\d \t()-]{6,20}\d(?![\w/@]|\.\d|-\d)")
# Lines whose numbers are documents and accounts, not phones ("ИНН: 771234567890")
ID_LABEL_RE = re.compile(r"\b(?:инн|снилс|паспорт|passport|id|ид|айди|огрн|окпо|єдрпоу|edrpou|іпн|рнокпп|inn|snils|"
                         r"card|карт|сч[её]т|рахунок|iban|account|order|заказ|замовлення|договор|договір|ticket|"
                         r"код|code|індекс|индекс|zip|postal)", re.I)
NAME_SEPARATOR_RE = re.compile(r"\s*(?:[,;|]|\s[-–—]\s)\s*")


def _loose_phone(raw: str, labelled: bool) -> tuple[Optional[str], Optional[str]]:
    """A number written without "+": (E.164, None) when it is a full international
    number, (None, raw) when it is a national one (needs its country), (None, None)
    when it doesn't look like a phone number. Bare digit runs that aren't
    international count only under a phone label (they are more often IDs)."""
    digits = re.sub(r"\D", "", raw)
    if not 9 <= len(digits) <= 15:
        return None, None
    if digits.startswith("00"):
        return norm_phone("+" + digits[2:]), None
    if not digits.startswith("0") and len(digits) >= 11:
        full = norm_phone("+" + digits)
        if full:
            return full, None
    grouped = bool(re.search(r"[ \t()-]", raw.strip()))
    if labelled or digits[0] in "08" or grouped:
        return None, raw.strip()
    return None, None


def resolve_national(raw: str, regions: Iterable[str]) -> Optional[str]:
    """A national number read in the countries given (those of the full numbers next to
    it), only when exactly one of them makes it a valid number."""
    readings = set()
    for region in regions:
        try:
            number = phonenumbers.parse(raw, region)
        except phonenumbers.NumberParseException:
            continue
        if phonenumbers.is_valid_number(number):
            readings.add(phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164))
    return readings.pop() if len(readings) == 1 else None


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
    # links the toolkit builds itself (wa.me/<number>, a Google search): not found anywhere
    "phone": {"links"},
}


# GitFive: only what it proved is the target's ("emails", the registered addresses that are
# the target's, the addresses on the target's own commits elsewhere). Not: the addresses it
# generates to test, tested addresses that belong to other accounts, and the addresses of
# everyone who committed to the target's repositories (often thousands of other people)
GITFIVE_UNCONFIRMED = {"generated_emails", "all_contribs", "internal_contribs", "near_names"}


def username_clues_read(result: dict[str, Any]) -> dict[str, Any]:
    """A username search with each clue's username under a "username" key, so the usernames a
    profile leads to are identifiers found in that account (results[i].clues[j].username)."""
    from services.username_clues import is_site_own, site_own_names   # it imports this module

    results = result.get("results")
    if not isinstance(results, list):
        return result

    def clues(r: dict) -> list[dict[str, Any]]:
        # the site's own accounts (saved before they were left out) are not the owner's
        own = site_own_names(str(r.get("site_name") or ""), None)
        return [{"username": c.get("value"), **{k: v for k, v in c.items() if k != "value"}}
                for c in r["clues"] if isinstance(c, dict) and not is_site_own(str(c.get("value") or ""), own)]

    return {**result, "results": [{**r, "clues": clues(r)} if isinstance(r, dict) and isinstance(r.get("clues"), list)
                                  else r for r in results]}


def gitfive_confirmed(result: dict[str, Any]) -> dict[str, Any]:
    """A GitFive result with only what is the target's (see GITFIVE_UNCONFIRMED)."""
    registered = result.get("registered_emails")
    return {**{k: v for k, v in result.items() if k not in GITFIVE_UNCONFIRMED},
            "registered_emails": {email: info for email, info in registered.items()
                                  if isinstance(info, dict) and info.get("is_target")}
            if isinstance(registered, dict) else registered}


def extract_entities(result: Any, service: str = "", no_country_code: Optional[list[str]] = None,
                     written: Optional[dict[str, list[str]]] = None) -> list[tuple[Entity, str]]:
    """(entity, json path) pairs found in a result payload.

    Results added by hand are read more loosely (it is text a person pasted, not an
    API's fields): "Label: value" lines, numbers without "+", names on their own line,
    CSV files by their headers. National numbers there are read in the country of
    the full numbers in the same result; the ones that can't be are appended to
    ``no_country_code`` (as written), not guessed. ``written`` collects every way each
    identifier is written ("067 123 45 67" and "+380671234567"), by key."""
    out: dict[str, tuple[Entity, str]] = {}
    if service == "gitfive" and isinstance(result, dict):
        result = gitfive_confirmed(result)
    if service == "username" and isinstance(result, dict):
        result = username_clues_read(result)
    if isinstance(result, dict) and result.get("kind") == "plugin_result":
        # card pictures and icons are never leads
        result = {**result, "items": [{k: v for k, v in item.items() if k not in ("image", "icon")}
                                      for item in result.get("items") or [] if isinstance(item, dict)]}

    # Identifiers the user listed when adding a result by hand are theirs, never noise
    by_hand = isinstance(result, dict) and result.get("kind") == "manual"
    national: list[tuple[str, str]] = []     # (as written, path) - by hand only

    def add(entity: Optional[Entity], path: str, typed: bool = False):
        if written is not None and entity and (entity.key in out or typed or not is_noise(entity)):
            forms = written.setdefault(entity.key, [])
            if entity.display and entity.display not in forms:
                forms.append(entity.display)
        if entity and entity.key not in out and len(out) < MAX_ENTITIES_PER_RESULT and (typed or not is_noise(entity)):
            out[entity.key] = (entity, path)
            # an email's domain (a company or personal domain) is a lead of its own;
            # free mail providers are dropped by is_noise
            if entity.type == "email":
                add(make_entity("domain", entity.value.rsplit("@", 1)[1]), path)

    def add_name(value: Any, path: str, prose: bool = False):
        if isinstance(value, str):
            normalized = norm_name(value, prose=prose)
            if normalized:
                add(Entity("name", normalized, normalized), path)

    def add_phones(value: str, path: str, labelled: bool):
        """Every phone number in a value (by hand: also without "+")."""
        for m in PHONE_TEXT_RE.finditer(value):
            phone = norm_phone(m.group(0))
            if phone:
                add(Entity("phone", phone, m.group(0).strip()), path)
        if not by_hand:
            return
        for m in LOOSE_PHONE_RE.finditer(value):
            if value[max(0, m.start() - 1):m.start()] == "+":
                continue
            full, local = _loose_phone(m.group(0), labelled)
            if full:
                add(Entity("phone", full, m.group(0).strip()), path)
            elif local:
                national.append((local, path))

    def add_hinted(hint: str, v: Any, path: str):
        if hint == "name":
            add_name(v, path)
        elif hint == "phone" and by_hand and isinstance(v, (str, int)):
            add_phones(str(v), path, labelled=True)
        else:
            add(make_entity(hint, v), path)

    def person_name(value: dict, path: str, hints: dict[str, str]):
        """First and last name in separate fields -> one name."""
        first = next((v for k, v in value.items() if hints.get(k) == "first_name" and isinstance(v, str)), None)
        last = next((v for k, v in value.items() if hints.get(k) == "last_name" and isinstance(v, str)), None)
        if first and last:
            add_name(f"{first.strip()} {last.strip()}", path)

    def field_hint(parent: dict, k: str) -> Optional[str]:
        low = k.lower()
        if low in FIRST_NAME_KEYS:
            return "first_name"
        if low in LAST_NAME_KEYS:
            return "last_name"
        hint = _service_hints(service, parent, k) or (_label_hint(k) if by_hand else _key_hint(k))
        if hint is None and low == "name" and PERSON_FIELDS.intersection(str(x).lower() for x in parent):
            hint = "name"
        return hint

    # Typed values with their parent dict (for service hints)
    def visit(value: Any, path: str, depth: int):
        if depth > 10 or len(out) >= MAX_ENTITIES_PER_RESULT:
            return
        if isinstance(value, dict):
            hints = {}
            for k, v in value.items():
                k = str(k)
                if SKIP_KEY_RE.search(k) or k in SERVICE_SKIP_KEYS.get(service, ()):
                    continue
                sub = f"{path}.{k}" if path else k
                if k == "entities" and isinstance(v, dict) and set(v) <= set(ENTITY_TYPES):
                    # plugin cards list their identifiers by type
                    for entity_type, values in v.items():
                        for i, item in enumerate(values if isinstance(values, list) else [values]):
                            if by_hand and entity_type == "text" and isinstance(item, str):
                                scan_text(item, f"{sub}.text[{i}]")   # a line that wasn't one identifier
                            add(make_entity(entity_type, item, typed=by_hand), f"{sub}.{entity_type}[{i}]", by_hand)
                    continue
                if by_hand and k == "content" and isinstance(v, str) and _is_table(value.get("name")):
                    visit(_table_rows(v, value.get("name")), sub, depth + 1)
                    continue
                add(make_entity("email", k), sub)  # emails used as dict keys (GitFive)
                hint = hints[k] = field_hint(value, k)
                if hint in ("first_name", "last_name"):
                    continue
                if hint and not isinstance(v, (dict, list)):
                    add_hinted(hint, v, sub)
                    if k.lower() in OWN_SITE_KEYS and isinstance(v, str):   # someone's own site: its domain too
                        add(make_entity("domain", urlparse(v if "//" in v else f"http://{v}").hostname or ""), sub)
                elif hint and isinstance(v, list):
                    for i, item in enumerate(v[:500]):
                        if not isinstance(item, (dict, list)):
                            add_hinted(hint, item, f"{sub}[{i}]")
                visit(v, sub, depth + 1)
            person_name(value, path, hints)
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
        if not by_hand:
            add_phones(text, path, labelled=False)
            return
        # "Телефон: 067 123 45 67", "ПІБ: Петренко Олександр", "Имя: Иван" + "Фамилия: Петров"
        person: dict[str, str] = {}
        for m in LABEL_LINE_RE.finditer(text):
            hint, value = _label_hint(m.group(1)), m.group(2)
            if hint in ("first_name", "last_name"):
                if hint in person:   # the next person's
                    person.clear()
                person[hint] = value
                if len(person) == 2:
                    add_name(f"{person['first_name']} {person['last_name']}", path)
            elif hint and not ID_LABEL_RE.search(m.group(1)):
                if hint == "phone":
                    add_phones(value, path, labelled=True)
                else:
                    add_hinted(hint, value, path)
        # numbers outside "ИНН: ...", "Passport: ..." lines
        id_lines = [(m.start(), m.end()) for m in LABEL_LINE_RE.finditer(text) if ID_LABEL_RE.search(m.group(1))]
        if id_lines:
            text_for_phones = "".join(" " * (end - start) if any(start <= s < end for s, _ in id_lines)
                                      else text[start:end] for start, end in _line_spans(text))
        else:
            text_for_phones = text
        add_phones(text_for_phones, path, labelled=False)
        if path in ("title", "source"):
            return
        # a name alone on its line, or before a phone / email on it ("Іван Петренко, +380...")
        for line in text.splitlines():
            first = NAME_SEPARATOR_RE.split(line.strip(), maxsplit=1)
            rest = first[1] if len(first) > 1 else ""
            if len(first) == 1 or EMAIL_RE.search(rest) or re.search(r"\d{3}", rest):
                add_name(first[0], path, prose=True)

    visit(result, "", 0)
    if national:
        # read in the countries of the full numbers found next to them (most common first)
        regions = [r for r, _ in Counter(
            phonenumbers.region_code_for_number(phonenumbers.parse(e.value))
            for e, _ in out.values() if e.type == "phone").most_common() if r]
        for raw, path in national:
            phone = resolve_national(raw, regions)
            if phone:
                add(Entity("phone", phone, raw), path)
            elif no_country_code is not None and raw not in no_country_code:
                no_country_code.append(raw)
    return list(out.values())


def _line_spans(text: str) -> list[tuple[int, int]]:
    spans, start = [], 0
    for line in text.splitlines(keepends=True):
        spans.append((start, start + len(line)))
        start += len(line)
    return spans


TABLE_EXTS = (".csv", ".tsv")


def _is_table(filename: Any) -> bool:
    return isinstance(filename, str) and filename.lower().endswith(TABLE_EXTS)


def _table_rows(content: str, filename: str, limit: int = 5000) -> list[dict[str, str]]:
    """A CSV/TSV file's rows keyed by its headers (so "Телефон" / "ПІБ" columns are read
    as phones / names); the plain text when it has no usable header."""
    sample = content[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel_tab if filename.lower().endswith(".tsv") else csv.excel
    rows = csv.reader(io.StringIO(content), dialect)
    header = next(rows, None)
    if not header or not any(_label_hint(h) for h in header):
        return [content]
    out = []
    for i, row in enumerate(rows):
        if i >= limit:
            break
        out.append({h or f"column {j + 1}": cell for j, (h, cell) in enumerate(zip(header, row, strict=False))})  # rows may be short
    return out


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
