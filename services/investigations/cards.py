"""Cards: what each lookup said, one card per thing it found (cards.json).

A card is an account on a site, a breach record, a domain's registration, a phone's
carrier, a mention on a page... with the few facts an investigator reads first and the
identifiers found inside that record. The graph draws cards between the identifier that
was looked up and what each record exposed, instead of one box per lookup.

Each module has a reader below (``READERS``) that says where its records are (their JSON
paths) and what to show; which identifiers a record holds comes from extract_entities, so
the noise rules stay in services/entities.py. Plugins return cards already (``items``).

cards.json is {result_id: [card]}, written next to entities.json whenever a result is.
Cards of different lookups that are the same thing (the account OI and the username
search both found, two rows of one breach for one email) have the same ``key``; the
graph merges them.
"""
import hashlib
import re
from typing import Any, Optional
from urllib.parse import urlparse

from services.entities import entities_from_parameters, extract_entities, make_entity
from .storage import _CARD_CACHE, _read_json, _write_json_atomic

CARD_KINDS = {
    "account": "Accounts",
    "breach": "Breaches",
    "person": "People",
    "registration": "Registrations",
    "network": "Networks",
    "place": "Places",
    "mention": "Mentions",
    "document": "Documents",
    "record": "Records",
}

CARD_KIND_ONE = {"account": "Account", "breach": "Breach", "person": "Person", "registration": "Registration",
                 "network": "Network", "place": "Place", "mention": "Mention", "document": "Document",
                 "record": "Record"}

# Facts kept per card, and how long each value may be
FACTS_MAX = 30
FACT_MAX_LEN = 300

# Fields no one reads on a card (paging, quotas, the API's own bookkeeping)
META_LABELS = {"success", "message", "page", "page size", "result limit", "filter id", "plan", "plan type",
               "is plan active", "is authenticated", "left today", "used today", "took ms", "total relation",
               "total", "count", "has more", "next cursor", "status code", "response time", "checked at",
               "extracted from", "request cost", "current balance", "request duration"}

# Where a breach record says which database it came from
BREACH_NAME_LABELS = ("dbname", "database", "db", "breach", "breach name", "leak", "source", "source table")

# Who a breach record is about, for the line under its name
WHO_LABELS = re.compile(r"^(full ?name|name|display ?name|first name|username|login|email)$", re.I)

# Facts that link records when two cards share one (graph: shared facts)
TRAIT_LABELS = (
    ("password", re.compile(r"^(password|pass|passwd|pwd|parol|пароль)$|^(plain|clear)[ _]?password", re.I)),
    ("hash", re.compile(r"hash|salt", re.I)),
    ("address", re.compile(r"^(address|street|address street|addresse?|home address|адрес|адреса)$", re.I)),
    ("dob", re.compile(r"birth|^dob$|^bdate$|^birthday$|дата рождения", re.I)),
    ("city", re.compile(r"^(city|town|locality|hometown|город|місто)$", re.I)),
)
TRAIT_NAMES = {"password": "Password", "hash": "Password hash", "address": "Address", "dob": "Birth date",
               "city": "City"}

# What a data class or field name says about a breach (shown as a badge)
FLAG_PATTERNS = (
    ("password", re.compile(r"password|passwd|pwd|пароль", re.I)),
    ("hash", re.compile(r"hash", re.I)),
    ("address", re.compile(r"address|street|адрес", re.I)),
    ("dob", re.compile(r"birth|dob", re.I)),
    ("phone", re.compile(r"phone|mobile|телефон", re.I)),
    ("card", re.compile(r"credit|card|iban|bank|cc_", re.I)),
    ("id", re.compile(r"ssn|passport|national[ _]id|inn|snils|tax", re.I)),
)

# Sites whose short name differs from their domain's
SITE_ALIASES = {"t": "telegram", "x": "twitter", "fb": "facebook", "ok": "odnoklassniki", "vkontakte": "vk",
                "youtu": "youtube", "googlemail": "google", "gmail": "google"}

DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})|(\d{2})[./](\d{2})[./](\d{4})|^(\d{4})$")

# Not facts: pictures and links shown on the card itself
PICTURE_KEYS = {"image", "avatar", "avatar_url", "avatar_static", "picture", "photo", "photo_url", "profile_pic",
                "profilepic", "profile_image_url", "profileimageurl", "icon_img", "logo", "logourl", "pic_url"}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _text(value: Any, limit: int = FACT_MAX_LEN) -> str:
    if value is None or isinstance(value, (dict, list)):
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _label(key: str) -> str:
    """profile_data keys and API field names as card labels: "last_login" -> "Last login"."""
    words = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(key)).replace("_", " ").strip()
    return words[:1].upper() + words[1:].lower() if words else ""


def facts_from(pairs, skip: tuple = ()) -> list[list[str]]:
    """[[label, value]] from (label, value) pairs or a dict: empty values, meta fields and
    duplicates left out, at most FACTS_MAX."""
    items = pairs.items() if isinstance(pairs, dict) else pairs
    facts, seen = [], set()
    for label, value in items:
        if isinstance(value, list):
            value = ", ".join(_text(v, 80) for v in value[:10] if _text(v, 80))
        label, text = _label(label) if "_" in str(label) or str(label).islower() else str(label), _text(value)
        low = label.lower()
        if not label or not text or low in META_LABELS or low in skip or (low, text) in seen:
            continue
        seen.add((low, text))
        facts.append([label[:60], text])
        if len(facts) >= FACTS_MAX:
            break
    return facts


def day(value: Any) -> Optional[str]:
    """A date as YYYY-MM-DD (or YYYY), whatever way it was written; None if it isn't one."""
    text = _text(value, 60)
    m = DATE_RE.search(text)
    if not m:
        return None
    if m.group(1):
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    if m.group(6):
        return f"{m.group(6)}-{m.group(5)}-{m.group(4)}"
    return m.group(7)


def host(url: Any) -> str:
    text = _text(url, 2000)
    if not text:
        return ""
    parsed = urlparse(text if "//" in text else f"http://{text}")
    return (parsed.hostname or "").lower().removeprefix("www.")


def site_id(value: Any) -> str:
    """A site's short name, the same from its domain and its name: github.com, "GitHub"
    and "github" are all "github"."""
    text = _text(value, 200).lower()
    if "." in text and " " not in text:
        labels = [p for p in host(text).split(".") if p]
        if len(labels) >= 3 and labels[-2] in ("co", "com", "org", "net", "gov", "ac", "edu"):
            text = labels[-3]
        elif len(labels) >= 2:
            text = labels[-2]
        elif labels:
            text = labels[0]
    text = re.sub(r"[^a-z0-9а-яё]+", "", text)
    return SITE_ALIASES.get(text, text)


def mask(value: str) -> str:
    """A password as shown on the graph: its first and last character."""
    value = str(value)
    return value[:1] + "•" * min(6, max(1, len(value) - 2)) + value[-1:] if len(value) > 2 else "••"


def _digest(kind: str, value: str) -> str:
    return hashlib.sha256(f"{kind}\0{value}".encode()).hexdigest()[:20]


def traits_of(facts: list[list[str]]) -> list[list[str]]:
    """[[kind, id, shown]] for the facts two records can share (a password, an address, a
    birth date, a city). The id is a hash, so no value is in a node id."""
    out, seen = [], set()
    for label, value in facts:
        for kind, pattern in TRAIT_LABELS:
            if pattern.search(label):
                norm = re.sub(r"\s+", " ", value).strip()
                if kind in ("address", "city"):
                    norm = norm.casefold()
                elif kind == "dob":
                    norm = day(value) or ""
                if len(norm) < 3 or norm in ("none", "null", "n/a", "-"):
                    break
                ident = _digest(kind, norm)
                if (kind, ident) not in seen:
                    seen.add((kind, ident))
                    shown = mask(value) if kind == "password" else (value[:10] + "…" if kind == "hash" and
                                                                     len(value) > 12 else value)
                    out.append([kind, ident, shown[:80]])
                break
    return out


def flags_of(labels) -> list[str]:
    found = []
    for label in labels:
        for flag, pattern in FLAG_PATTERNS:
            if flag not in found and pattern.search(str(label)):
                found.append(flag)
    return found


def _who(username: Any, subject: list[str]) -> str:
    """Whose account a card is, for telling apart two cards of one site: the username on
    it, else the identifier that was looked up."""
    name = _text(username, 100).lstrip("@").casefold()
    if name:
        return name
    if subject:
        entity_type, _, value = subject[0].partition(":")
        return value.casefold() if entity_type in ("username", "telegram_username") else subject[0]
    return ""


def _first(mapping: dict, *keys) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def card(kind: str, paths: list[str], title: Any, **fields) -> dict[str, Any]:
    """One card as a reader returns it (build_cards adds what every card has)."""
    return {"kind": kind, "paths": paths, "title": _text(title, 120) or CARD_KIND_ONE[kind], **fields}


# ---------------------------------------------------------------------------
# Readers: one per module. (result, method, subject keys) -> [card]
# ---------------------------------------------------------------------------

def read_username(result: dict, method: str, subject: list[str]) -> list[dict[str, Any]]:
    from services.investigations.graph import profile_picture   # graph imports this module

    root = str(result.get("username") or "")
    cards = []
    for i, site in enumerate(result.get("results") or []):
        if not isinstance(site, dict) or not site.get("url"):
            continue
        profile = site.get("profile_data") if isinstance(site.get("profile_data"), dict) else {}
        searched = str(site.get("searched") or root)
        name = _first(profile, "fullname", "full_name", "name", "display_name", "displayName", "title")
        facts = facts_from([(k, v) for k, v in profile.items()
                            if k.lower() not in PICTURE_KEYS and k.lower() not in ("url", "extracted_from")])
        found = {
            "key": f"account:{site_id(host(site['url']) or site.get('site_name'))}:{searched.casefold()}",
            "subtitle": _text(name, 80) or f"@{searched}", "site": host(site["url"]), "url": site["url"],
            "picture": profile_picture(site), "category": _text(site.get("category"), 60) or "other",
            "facts": facts, "own": [("url", site["url"])],
        }
        if searched and searched.casefold() != root.casefold():
            found["under"] = ("username", searched)
        cards.append(card("account", [f"results[{i}]"], site.get("site_name") or host(site["url"]), **found))
    for i, box in enumerate(result.get("mailboxes") or []):
        if not isinstance(box, dict) or not box.get("email"):
            continue
        details = box.get("details") if isinstance(box.get("details"), dict) else {}
        cards.append(card(
            "account", [f"mailboxes[{i}]"], box.get("provider") or host(box["email"].rsplit("@", 1)[-1]),
            key=f"account:{site_id(box['email'].rsplit('@', 1)[-1])}:{box['email'].casefold()}",
            subtitle=_text(box["email"], 80), site=box["email"].rsplit("@", 1)[-1].lower(), category="email",
            picture=_text(details.get("picture"), 2000) or None,
            facts=facts_from([("Mailbox", "exists"), ("Name", details.get("name")),
                              ("Location", details.get("location")), ("Aliases", box.get("aliases"))])))
    for i, mention in enumerate(result.get("web_mentions") or []):
        if isinstance(mention, dict) and mention.get("url"):
            cards.append(card("mention", [f"web_mentions[{i}]"], mention.get("title") or host(mention["url"]),
                              key=f"mention:{mention['url']}", subtitle=host(mention["url"]), site=host(mention["url"]),
                              url=mention["url"], own=[("url", mention["url"])]))
    return cards


def read_oi(result: dict, method: str, subject: list[str]) -> list[dict[str, Any]]:
    cards = []
    for i, module in enumerate(result.get("modules") or []):
        if not isinstance(module, dict) or module.get("registered") is False:
            continue
        name = str(module.get("module") or module.get("slug") or "")
        fields = [(f.get("label"), f.get("value")) for f in module.get("fields") or [] if isinstance(f, dict)]
        if module.get("breach"):
            breach = module.get("name") or name
            cards.append(card(
                "breach", [f"modules[{i}]"], breach,
                key=f"breach:{site_id(module.get('domain') or breach)}:{_who(None, subject)}",
                subtitle=_text(module.get("domain"), 80) or name, site=host(module.get("domain")) or None,
                date=day(module.get("created")),
                facts=facts_from([("Breached", module.get("created")), ("Website", module.get("website")),
                                  *fields]),
                flags=flags_of([label for label, _ in fields] + [str(v) for _, v in fields])))
            continue
        site = host(module.get("domain") or module.get("website") or "") or None
        username = module.get("username")
        cards.append(card(
            "account", [f"modules[{i}]"], name[:1].upper() + name[1:],
            key=f"account:{site_id(site or name)}:{_who(username, subject)}",
            subtitle=_text(module.get("name") or (f"@{username}" if username else ""), 80) or None,
            site=site, url=_text(module.get("profile_url"), 2000) or None,
            picture=_text(module.get("picture"), 2000) or None,
            category=_text(module.get("category"), 60) or "other",
            date=day(module.get("created")) or day(module.get("last_seen")),
            facts=facts_from([("Name", module.get("name")), ("Username", username), ("Created", module.get("created")),
                              ("Last seen", module.get("last_seen")), ("Location", module.get("location")),
                              ("Bio", module.get("bio")), ("Gender", module.get("gender")), ("Age", module.get("age")),
                              ("Email", module.get("email")), ("Phone", module.get("phone")),
                              ("Account ID", module.get("account_id")), ("Website", module.get("website")), *fields]),
            own=[("url", module.get("profile_url"))]))
    return cards


def _profile_part(profile: dict, name: str) -> dict:
    """GHunt's {"PROFILE": {...}} (or its first container)."""
    part = profile.get(name)
    if not isinstance(part, dict):
        return {}
    inner = part.get("PROFILE") or next(iter(part.values()), None)
    return inner if isinstance(inner, dict) else {}


def read_ghunt(result: dict, method: str, subject: list[str]) -> list[dict[str, Any]]:
    container = result.get("PROFILE_CONTAINER")
    if isinstance(container, dict):
        profile = container.get("profile") if isinstance(container.get("profile"), dict) else {}
        gaia = _text(profile.get("personId"), 40)
        photo = _profile_part(profile, "profilePhotos")
        maps = container.get("maps") if isinstance(container.get("maps"), dict) else {}
        guide = maps.get("profile") if isinstance(maps.get("profile"), dict) else {}
        stats = maps.get("stats") if isinstance(maps.get("stats"), dict) else {}
        edited = _profile_part(profile, "sourceIds").get("lastUpdated")
        events = (((container.get("calendar") or {}).get("events") or {}).get("items")
                  if isinstance(container.get("calendar"), dict) else None)
        fullname = _profile_part(profile, "names").get("fullname") or guide.get("name")
        return [card(
            "account", ["PROFILE_CONTAINER"], "Google", key=f"account:google:{gaia or _who(None, subject)}",
            subtitle=_text(fullname, 80) or _text(_profile_part(profile, "emails").get("value"), 80) or None,
            site="google.com", category="google",
            picture=None if photo.get("isDefault") else (_text(photo.get("url"), 2000) or None), date=day(edited),
            facts=facts_from([("Name", fullname), ("Gaia ID", gaia), ("Profile edited", edited),
                              ("Account type", _profile_part(profile, "profileInfos").get("userTypes")),
                              ("Apps", _profile_part(profile, "inAppReachability").get("apps")),
                              ("Local Guide", guide.get("local_guide")), ("Guide points", guide.get("local_guide_points")),
                              *[(f"Maps {k.lower()}", v) for k, v in stats.items() if v],
                              ("Calendar events", len(events) if isinstance(events, list) and events else None)]),
            own=[("gaia_id", gaia)])]
    if method.endswith("geolocate") and (result.get("latitude") or result.get("address")):
        place = result.get("pretty_address") or result.get("address") or f"{result.get('latitude')}, {result.get('longitude')}"
        return [card("place", [""], place, key=f"place:{_text(place, 200).casefold()}", subtitle="Wi-Fi location",
                     facts=facts_from([("Address", result.get("address")), ("Latitude", result.get("latitude")),
                                       ("Longitude", result.get("longitude")), ("Accuracy", result.get("accuracy"))]))]
    cards = []
    for i, user in enumerate(result.get("users") or []):
        if isinstance(user, dict):
            cards.append(card("person", [f"users[{i}]"], user.get("name") or user.get("email_address") or "Drive user",
                              key=f"person:google:{user.get('gaia_id') or user.get('email_address')}",
                              subtitle=_text(user.get("role"), 40) or None, relation="on the file",
                              facts=facts_from([("Email", user.get("email_address")), ("Gaia ID", user.get("gaia_id")),
                                                ("Role", user.get("role"))])))
    for kind in ("sites", "packages"):
        for key, info in (result.get(kind) or {}).items() if isinstance(result.get(kind), dict) else ():
            asset = (info or {}).get("asset") if isinstance(info, dict) else None
            name = (asset or {}).get("site") or (asset or {}).get("package_name") or key
            cards.append(card("mention", [f"{kind}.{key}"], name, key=f"mention:{name}", subtitle="linked by Google",
                              site=host(name) or None, relation="linked"))
    return cards


def read_gitfive(result: dict, method: str, subject: list[str]) -> list[dict[str, Any]]:
    username = result.get("username") or _who(None, subject)
    return [card(
        "account", [""], "GitHub", key=f"account:github:{str(username).casefold()}",
        subtitle=_text(result.get("name"), 80) or f"@{username}", site="github.com", category="coding",
        url=f"https://github.com/{username}", picture=None if result.get("is_default_avatar") else
        (_text(result.get("avatar_url"), 2000) or None), date=day(result.get("created_at")),
        facts=facts_from([("Name", result.get("name")), ("Company", result.get("company")),
                          ("Location", result.get("location")), ("Bio", result.get("bio")), ("Blog", result.get("blog")),
                          ("Twitter", result.get("twitter")), ("Created", result.get("created_at")),
                          ("Updated", result.get("updated_at")), ("Followers", result.get("nb_followers")),
                          ("Following", result.get("nb_following")), ("Public repos", result.get("nb_public_repos")),
                          ("Other names", result.get("fullnames")), ("SSH keys", len(result.get("ssh_keys") or []) or None),
                          ("Organisations", [o.get("name") or o.get("handle") for o in result.get("orgs") or []
                                             if isinstance(o, dict)])]),
        own=[("url", f"https://github.com/{username}")])]


def _telegram_user(user: dict, path: str, relation: Optional[str] = None) -> dict[str, Any]:
    name = " ".join(_text(user.get(k), 60) for k in ("first_name", "last_name") if _text(user.get(k), 60)) \
        or _text(user.get("name"), 80)
    found = {
        "key": f"account:telegram:{user.get('id') or user.get('user_id') or str(user.get('username') or '').casefold()}",
        "subtitle": name or (f"@{user['username']}" if user.get("username") else None), "site": "telegram.org",
        "category": "messaging",
        "facts": facts_from([("Name", name), ("Username", f"@{user['username']}" if user.get("username") else None),
                             ("ID", user.get("id") or user.get("user_id")), ("Premium", user.get("has_premium")),
                             ("Bot", user.get("is_bot") or None), ("Active", user.get("is_active")),
                             ("Common groups", user.get("common_groups")), ("Admin", user.get("is_admin") or None)]),
        "own": [("telegram_id", user.get("id") or user.get("user_id"))],
    }
    if relation:
        found["relation"] = relation
    return card("person" if relation else "account", [path], "Telegram", **found)


def _group_messages(messages: list, base: str) -> list[dict[str, Any]]:
    """Messages as one card per chat they were written in."""
    chats: dict[str, dict[str, Any]] = {}
    for i, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        group = message.get("group") if isinstance(message.get("group"), dict) else {}
        chat_id = str(group.get("id") or group.get("title") or "?")
        entry = chats.setdefault(chat_id, {"group": group, "paths": [], "texts": [], "dates": []})
        entry["paths"].append(f"{base}[{i}]")
        if message.get("text") and len(entry["texts"]) < 3:
            entry["texts"].append(message["text"])
        if day(message.get("date")):
            entry["dates"].append(day(message.get("date")))
    cards = []
    for chat_id, entry in chats.items():
        group, dates = entry["group"], sorted(entry["dates"])
        link = group.get("link") or (f"https://t.me/{group['username']}" if group.get("username") else None)
        cards.append(card(
            "mention", entry["paths"], group.get("title") or "Telegram chat", key=f"mention:telegram:{chat_id}",
            subtitle=f"{len(entry['paths'])} message{'s' if len(entry['paths']) != 1 else ''}", site="telegram.org",
            url=link, date=dates[-1] if dates else None, relation="wrote in",
            facts=facts_from([("Chat", group.get("title")), ("Chat @", group.get("username")),
                              ("Messages", len(entry["paths"])),
                              ("Dates", f"{dates[0]} – {dates[-1]}" if len(dates) > 1 else (dates[0] if dates else None)),
                              *[("Message", text) for text in entry["texts"]]])))
    return cards


def read_funstat(result: Any, method: str, subject: list[str]) -> list[dict[str, Any]]:
    if method == "lookup_user" and isinstance(result, list):
        return [_telegram_user(u, f"[{i}]") for i, u in enumerate(result) if isinstance(u, dict)]
    if not isinstance(result, (dict, list)):
        return []
    if method in ("stats", "stats_min") and isinstance(result, dict):
        chat = result.get("favorite_chat") if isinstance(result.get("favorite_chat"), dict) else {}
        return [card("account", [""], "Telegram", key="@parent", facts=facts_from([
            ("First message", result.get("first_msg_date")), ("Last message", result.get("last_msg_date")),
            ("Messages", result.get("total_msg_count")), ("Groups", result.get("total_groups")),
            ("Admin in", result.get("adm_in_groups")), ("Names used", result.get("names_count")),
            ("Usernames used", result.get("usernames_count")), ("Language", result.get("lang_code")),
            ("Favourite chat", chat.get("title"))]))]
    if method == "tme_profile" and isinstance(result, dict) and result.get("exists") is not False:
        return [card("account", [""], "Telegram", key="@parent", picture=_text(result.get("avatar_url"), 2000) or None,
                     facts=facts_from([("Bio", result.get("bio")), ("t.me name", result.get("name"))]))]
    if method in ("names_history", "usernames_history", "names_and_usernames_history") and isinstance(result, list):
        history = [f"{_text(h.get('value') or h.get('name'), 80)} ({day(h.get('date_time')) or '?'})"
                   for h in result if isinstance(h, dict)]
        return [card("account", [""], "Telegram", key="@parent", facts=facts_from([("History", history)]))]
    if method in ("messages", "all_messages") and isinstance(result, dict):
        return _group_messages(result.get("messages") or [], "messages")
    if method == "search_text" and isinstance(result, dict):
        return _group_messages(result.get("results") or [], "results")
    if method == "groups" and isinstance(result, list):
        cards = []
        for i, entry in enumerate(result):
            chat = entry.get("chat") if isinstance(entry, dict) and isinstance(entry.get("chat"), dict) else None
            if chat:
                cards.append(card("mention", [f"[{i}]"], chat.get("title") or "Telegram chat",
                                  key=f"mention:telegram:{chat.get('id') or chat.get('title')}",
                                  subtitle=f"{entry.get('messages_count') or 0} messages", site="telegram.org",
                                  url=f"https://t.me/{chat['username']}" if chat.get("username") else None,
                                  relation="member of", flags=["admin"] if entry.get("is_admin") else [],
                                  facts=facts_from([("Messages", entry.get("messages_count")),
                                                    ("Admin", entry.get("is_admin") or None),
                                                    ("Left", entry.get("is_left") or None)])))
        return cards
    if method == "common_groups_stat" and isinstance(result, list):
        return [_telegram_user(u, f"[{i}]", "shares groups") for i, u in enumerate(result) if isinstance(u, dict)]
    if method == "group_members" and isinstance(result, list):
        return [_telegram_user(u, f"[{i}]", "member") for i, u in enumerate(result) if isinstance(u, dict)]
    return []


def read_vk_profile(result: dict, method: str, subject: list[str]) -> list[dict[str, Any]]:
    entries = [e for e in result.get("entries") or [] if isinstance(e, dict)]
    if not entries:
        return []
    latest = max(entries, key=lambda e: str(e.get("year_month") or ""))
    vk_id = next((e.get("vk_id") for e in reversed(entries) if e.get("vk_id")), None)
    names = list(dict.fromkeys(_text(e.get("full_name"), 80) for e in entries if _text(e.get("full_name"), 80)))
    cities = list(dict.fromkeys(_text(e.get("city"), 80) for e in entries if _text(e.get("city"), 80)))
    return [card(
        "account", [""], "VK", key=f"account:vk:{vk_id or _who(None, subject)}",
        subtitle=_text(latest.get("full_name"), 80) or None, site="vk.com", category="social",
        url=_text(latest.get("url"), 2000) or None, picture=_text(latest.get("avatar"), 2000) or None,
        date=day(latest.get("last_visit")) or day(latest.get("last_login")),
        facts=facts_from([("Name", latest.get("full_name")), ("Birth date", latest.get("birth_date")),
                          ("City", latest.get("city")), ("Country", latest.get("country")),
                          ("Hometown", latest.get("hometown")), ("Last visit", latest.get("last_visit")),
                          ("Last login", latest.get("last_login")), ("Device", latest.get("device")),
                          ("Followers", latest.get("followers")), ("University", latest.get("university")),
                          ("Snapshots", len(entries)), ("Names used", names if len(names) > 1 else None),
                          ("Cities", cities if len(cities) > 1 else None)]),
        own=[("vk", vk_id), ("url", latest.get("url"))])]


def read_face_search(result: dict, method: str, subject: list[str]) -> list[dict[str, Any]]:
    return [card("person", [f"results[{i}]"], "VK", key=f"account:vk:{r.get('vk_id') or i}",
                 subtitle=_text(r.get("name"), 80) or None, site="vk.com", picture=_text(r.get("image_url"), 2000) or None,
                 relation="face match", facts=facts_from([("Name", r.get("name")), ("City", r.get("city")),
                                                          ("Similarity", f"{r['similarity_rate']}%"
                                                           if r.get("similarity_rate") is not None else None)]),
                 own=[("vk", r.get("vk_id"))])
            for i, r in enumerate(result.get("results") or []) if isinstance(r, dict)]


def _contact_card(contact: dict, path: str, domain: str, roles: Any = None) -> Optional[dict[str, Any]]:
    from services.whois_service import PRIVACY_RE

    who = _first(contact, "name", "organization", "registrant", "email")
    # a privacy service's details say nothing about who registered it
    if not who or contact.get("privacy") or (PRIVACY_RE.search(str(who))
                                             and PRIVACY_RE.search(str(contact.get("email") or "privacy"))):
        return None
    place = ", ".join(_text(contact.get(k), 80) for k in ("street", "city", "state", "postalCode", "country")
                      if _text(contact.get(k), 80))
    return card("registration", [path], who, key=f"registration:{domain}:{_text(who, 120).casefold()}",
                subtitle=_text(roles, 80) or "registrant", relation="registered by",
                date=day(contact.get("first_seen")),
                facts=facts_from([("Name", contact.get("name") or contact.get("registrant")),
                                  ("Organisation", contact.get("organization") or contact.get("org")),
                                  ("Email", contact.get("email")), ("Phone", contact.get("telephone")),
                                  ("Address", place), ("Country", contact.get("country")),
                                  ("Registrar", contact.get("registrar")), ("Created", contact.get("creation_date")),
                                  ("Expires", contact.get("expiration_date")), ("First seen", contact.get("first_seen")),
                                  ("Last seen", contact.get("last_seen"))]))


def read_whois(result: dict, method: str, subject: list[str]) -> list[dict[str, Any]]:
    domain = str(result.get("domain") or _who(None, subject))
    analysis = result.get("analysis") if isinstance(result.get("analysis"), dict) else {}
    cards = [c for i, contact in enumerate(analysis.get("contacts") or []) if isinstance(contact, dict)
             for c in [_contact_card(contact, f"analysis.contacts[{i}]", domain, contact.get("roles"))] if c]
    if not analysis and isinstance(result, dict) and (result.get("registrant") or result.get("registrar")):
        found = _contact_card(result, "", domain)
        cards += [found] if found else []
    return cards


def read_ns(result: Any, method: str, subject: list[str]) -> list[dict[str, Any]]:
    domains = result.get("domains") if isinstance(result, dict) and isinstance(result.get("domains"), dict) else {}
    cards = []
    for domain, info in domains.items():
        if not isinstance(info, dict) or info.get("error"):
            continue
        path = f"domains.{domain}"
        if method == "whois_analysis":
            found = _contact_card(info, path, domain)
        else:
            found = card("network", [path], info.get("title") or domain, key=f"network:site:{domain}",
                         subtitle=domain, site=domain, url=_text(info.get("final_url") or info.get("url"), 2000) or None,
                         relation="website", facts=facts_from([
                             ("Title", info.get("title")), ("Status", info.get("status")), ("Server", info.get("server")),
                             ("Technologies", info.get("tech")), ("IPs", info.get("ips")), ("CDN", info.get("cdn")),
                             ("Certificate issuer", (info.get("cert") or {}).get("issuer")
                              if isinstance(info.get("cert"), dict) else None)]))
        if found:
            found["under"] = ("domain", domain)
            cards.append(found)
    return cards


def read_dns_recon(result: dict, method: str, subject: list[str]) -> list[dict[str, Any]]:
    cards = []
    whois = result.get("whois_info") if isinstance(result.get("whois_info"), dict) else {}
    if whois and not whois.get("error"):
        found = _contact_card({**whois, "name": whois.get("registrant") or whois.get("org")}, "whois_info",
                              str(result.get("domain") or ""))
        cards += [found] if found else []
    for i, hosting in enumerate(result.get("hosting") or []):
        if isinstance(hosting, dict):
            cards.append(card("network", [f"hosting[{i}]"], hosting.get("as_name") or hosting.get("asn") or "Hosting",
                              key=f"network:asn:{hosting.get('asn') or hosting.get('as_name')}:{hosting.get('ip')}",
                              subtitle=_text(hosting.get("ip"), 60) or None, relation="hosted at",
                              facts=facts_from([("ASN", hosting.get("asn")), ("Prefix", hosting.get("prefix")),
                                                ("Country", hosting.get("country")), ("Hosts", hosting.get("hosts"))])))
    return cards


def read_ip(result: dict, method: str, subject: list[str]) -> list[dict[str, Any]]:
    basic = result.get("basic_info") if isinstance(result.get("basic_info"), dict) else {}
    abuse = result.get("abuse_info") if isinstance(result.get("abuse_info"), dict) else {}
    shodan = result.get("shodan_info") if isinstance(result.get("shodan_info"), dict) else {}
    if not basic and not abuse and not shodan:
        return []
    place = ", ".join(_text(basic.get(k), 60) for k in ("city", "region", "country") if _text(basic.get(k), 60))
    return [card(
        "network", [""], basic.get("org") or abuse.get("isp") or "IP address", key=f"network:ip:{result.get('ip')}",
        subtitle=place or None, relation="network", flags=["tor"] if abuse.get("isTor") else [],
        facts=facts_from([("Location", place), ("Organisation", basic.get("org")), ("ISP", abuse.get("isp")),
                          ("Hostname", basic.get("hostname")), ("Reverse DNS", result.get("reverse_dns")),
                          ("Usage", abuse.get("usageType")), ("Abuse score", abuse.get("abuseConfidenceScore")),
                          ("Reports", abuse.get("totalReports")), ("Tor", abuse.get("isTor") or None),
                          ("Open ports", shodan.get("ports")), ("Vulnerabilities", shodan.get("vulns"))]))]


def read_phone(result: dict, method: str, subject: list[str]) -> list[dict[str, Any]]:
    if not isinstance(result, dict) or not (result.get("carrier") or result.get("location") or result.get("region")):
        return []
    return [card("network", [""], result.get("carrier") or "Phone number", key=f"network:phone:{_who(None, subject)}",
                 subtitle=" · ".join(_text(result.get(k), 40) for k in ("line_type", "location") if result.get(k)) or None,
                 relation="carrier",
                 facts=facts_from([("Carrier", result.get("carrier")), ("Line type", result.get("line_type")),
                                   ("Location", result.get("location")), ("Region", result.get("region")),
                                   ("Time zones", result.get("timezones")), ("Valid", result.get("valid")),
                                   ("Note", result.get("note"))]))]


def read_hlr(result: dict, method: str, subject: list[str]) -> list[dict[str, Any]]:
    cards = []
    for i, row in enumerate(result.get("results") or []):
        if isinstance(row, dict) and row.get("status") == "OK":
            found = card("network", [f"results[{i}]"], row.get("operator") or "Network", relation="network now",
                         key=f"network:hlr:{row.get('phone')}", subtitle=_text(row.get("region"), 60) or None,
                         facts=facts_from([("Operator", row.get("operator")), ("Region", row.get("region")),
                                           ("MCC", row.get("mcc")), ("MNC", row.get("mnc")), ("IMSI", row.get("imsi"))]))
            if row.get("phone"):
                found["under"] = ("phone", row["phone"] if str(row["phone"]).startswith("+") else f"+{row['phone']}")
            cards.append(found)
    return cards


def read_cavalier(result: dict, method: str, subject: list[str]) -> list[dict[str, Any]]:
    cards = []
    key = "stealers" if isinstance(result.get("stealers"), list) else "data"
    for i, stealer in enumerate(result.get(key) or []):
        if not isinstance(stealer, dict):
            continue
        credentials = stealer.get("credentials") if isinstance(stealer.get("credentials"), list) else []
        cards.append(card(
            "breach", [f"{key}[{i}]"], stealer.get("stealer_family") or "Infostealer",
            key=f"breach:infostealer:{stealer.get('computer_name')}:{day(stealer.get('date_compromised'))}",
            subtitle=_text(stealer.get("computer_name"), 80) or None, date=day(stealer.get("date_compromised")),
            category="infostealer", flags=["password"] if stealer.get("top_passwords") or credentials else [],
            facts=facts_from([("Compromised", stealer.get("date_compromised")), ("Computer", stealer.get("computer_name")),
                              ("System", stealer.get("operating_system")), ("IP", stealer.get("ip")),
                              ("Malware path", stealer.get("malware_path")), ("Antivirus", stealer.get("antiviruses")),
                              ("Logins", stealer.get("top_logins")), ("Passwords", stealer.get("top_passwords")),
                              ("Credentials", len(credentials) or None)])))
    return cards


def read_web_search(result: dict, method: str, subject: list[str]) -> list[dict[str, Any]]:
    return [card("mention", [f"results[{i}]"], r.get("title") or host(r.get("url")), key=f"mention:{r['url']}",
                 subtitle=host(r["url"]), site=host(r["url"]), url=r["url"], own=[("url", r["url"])],
                 facts=facts_from([("Snippet", r.get("snippet")), ("Engine", r.get("engine")), ("Search", r.get("dork"))]))
            for i, r in enumerate(result.get("results") or []) if isinstance(r, dict) and r.get("url")]


def read_sharetrace(result: dict, method: str, subject: list[str]) -> list[dict[str, Any]]:
    listed = isinstance(result.get("results"), list)
    rows = result["results"] if listed else [result]
    cards = []
    for i, row in enumerate(rows):
        data = row.get("data") if isinstance(row, dict) and isinstance(row.get("data"), dict) else None
        if not data:
            continue
        platform = str(row.get("platform") or "Link")
        username = data.get("username")
        cards.append(card(
            "account", [f"results[{i}]" if listed else ""],
            platform[:1].upper() + platform[1:], key=f"account:{site_id(platform)}:{_who(username, subject)}",
            subtitle=_text(data.get("nickname") or (f"@{username}" if username else ""), 80) or None,
            picture=_text(data.get("avatar_url"), 2000) or None, relation="shared the link",
            date=day(data.get("shared_at")), category="social",
            facts=facts_from([("Username", username), ("Nickname", data.get("nickname")), ("Bio", data.get("signature")),
                              ("Country", data.get("country")), ("Device", data.get("device")),
                              ("Shared", data.get("shared_at")), ("Followers", data.get("follower_count")),
                              ("Private", data.get("private_account"))])))
    return cards


def read_doxbin(result: Any, method: str, subject: list[str]) -> list[dict[str, Any]]:
    rows = result if isinstance(result, list) else []
    return [card("account", [f"[{i}]"], "Doxbin", key=f"account:doxbin:{row.get('profile_url') or i}",
                 subtitle=_text(", ".join(map(str, row.get("username") or []))
                                if isinstance(row.get("username"), list) else row.get("username"), 80) or None,
                 site="doxbin.com", url=_text(row.get("profile_url"), 2000) or None, category="forum",
                 own=[("url", row.get("profile_url"))])
            for i, row in enumerate(rows) if isinstance(row, dict)]


def read_manual(result: dict, method: str, subject: list[str]) -> list[dict[str, Any]]:
    files = [f.get("name") for f in result.get("files") or [] if isinstance(f, dict)]
    return [card("document", [""], result.get("title") or "Added by hand", key=None,
                 subtitle=_text(result.get("source"), 80) or None, url=_text(result.get("url"), 2000) or None,
                 date=day(result.get("date")), relation="added",
                 facts=facts_from([("Source", result.get("source")), ("Date", result.get("date")),
                                   ("Files", files), ("Text", result.get("text"))]))]


def _plugin_kind(plugin_id: str, labels: list[str]) -> str:
    try:
        from services.pluginkit import registry
        plugin = registry.get(plugin_id)
        kind = getattr(plugin.manifest, "graph", None) if plugin and plugin.manifest else None
    except Exception:   # a broken plugin folder never stops a result from being saved
        kind = None
    if kind:
        return kind
    low = [label.lower() for label in labels]
    if any(label in BREACH_NAME_LABELS for label in low) or any("password" in label for label in low):
        return "breach"
    return "record"


def read_plugin(result: dict, method: str, subject: list[str]) -> list[dict[str, Any]]:
    """Plugins return cards already: items[] with a title, fields and the identifiers on it."""
    cards = []
    plugin = str(result.get("plugin") or "")
    for i, item in enumerate(result.get("items") or []):
        if not isinstance(item, dict):
            continue
        fields = [(f[0], f[1]) for f in item.get("fields") or [] if isinstance(f, (list, tuple)) and len(f) == 2]
        labels = [str(label) for label, _ in fields]
        kind = _plugin_kind(plugin, labels)
        title, subtitle = _text(item.get("title"), 120), _text(item.get("subtitle"), 80)
        site = _text(item.get("site"), 200).lower() or None
        if kind == "breach":
            source = next((_text(v, 120) for label, v in fields if label.lower() in BREACH_NAME_LABELS and _text(v, 120)),
                          "")
            breach_name = host(source) if source.startswith("http") else source
            key = f"breach:{site_id(breach_name or site or plugin)}:{_who(None, subject)}"
            # under the breach's name: whose record it is (a name, else a login), not the plugin's
            who = next((_text(v, 80) for label, v in fields if WHO_LABELS.match(str(label)) and _text(v, 80)), "")
            plugin_name = str(result.get("name") or plugin)
            title, subtitle = (breach_name or plugin_name), who or next(
                (t for t in (title, subtitle) if t and t != breach_name and t != plugin_name), "")
        elif kind == "account":
            # the same account as the username search's when its address ends in the username
            url = _text(item.get("url"), 2000)
            name = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1].lstrip("@") if url else ""
            key = f"account:{site_id(host(url) or site or plugin)}:{name.casefold() or _who(None, subject)}"
        else:
            key = f"{kind}:{site_id(site or plugin)}:{item.get('url') or title or i}"
        cards.append(card(kind if kind in CARD_KINDS else "record", [f"items[{i}]"], title or result.get("name") or plugin,
                          key=key, subtitle=subtitle or None, site=site, url=_text(item.get("url"), 2000) or None,
                          picture=_text(item.get("image"), 2000) or None,
                          category=_text(item.get("category"), 60) or None,
                          date=next((day(v) for label, v in fields
                                     if re.search(r"date|created|posted|breach|joined", label, re.I) and day(v)), None),
                          facts=facts_from(fields), flags=flags_of(labels) if kind == "breach" else [],
                          own=[("url", item.get("url"))], optional=True))
    return cards


READERS = {
    "username": read_username, "oi": read_oi, "ghunt": read_ghunt, "gitfive": read_gitfive, "funstat": read_funstat,
    "vk_profile": read_vk_profile, "face_search": read_face_search, "whois": read_whois, "ns": read_ns,
    "dns_recon": read_dns_recon, "ip": read_ip, "phone": read_phone, "hlr": read_hlr, "cavalier": read_cavalier,
    "web_search": read_web_search, "sharetrace": read_sharetrace, "doxbin": read_doxbin, "manual": read_manual,
}


# ---------------------------------------------------------------------------
# A saved result -> its cards
# ---------------------------------------------------------------------------

def _prefixes(path: str):
    """``path`` and every path above it: results[3].profile_data.email -> results[3].profile_data,
    results[3], results, "". """
    yield path
    for i in range(len(path) - 1, 0, -1):
        if path[i] in ".[" and path[i - 1] != ".":
            yield path[:i]
    yield ""


def _read(service: str, result: Any, method: str, subject: list[str]) -> list[dict[str, Any]]:
    if isinstance(result, dict) and result.get("kind") == "plugin_result":
        return read_plugin(result, method, subject)
    reader = READERS.get(service)
    if reader is None or result is None:
        return []
    if not isinstance(result, (dict, list)) or (isinstance(result, list) and service not in ("funstat", "doxbin")):
        return []
    try:
        return reader(result, method, subject)
    except (AttributeError, TypeError, ValueError, KeyError):   # an answer shaped unlike the others
        return []


def build_cards(record: dict[str, Any]) -> list[dict[str, Any]]:
    """The cards of one saved result and its follow-ups. Each card lists the identifiers in
    its record (``exposed``) and the ones that are the card itself (``own``: an account's
    address or id), as entity keys; ``subject`` is what the lookup searched."""
    out: list[dict[str, Any]] = []
    parent_card: Optional[dict[str, Any]] = None
    parts = [(None, record)] + [(c.get("child_id"), c) for c in record.get("children") or []]
    for child_id, part in parts:
        service, method = part.get("service_name") or "", part.get("method_name") or ""
        result = part.get("result")
        subject = [e.key for e in entities_from_parameters(part.get("parameters") or {}, service)]
        # what was searched, and the domain of a searched email (found again in every record)
        known = set(subject) | {f"domain:{key.rsplit('@', 1)[1]}" for key in subject if key.startswith("email:")}
        specs = _read(service, result, method, subject)
        if not specs:
            continue
        everywhere: list[tuple[str, str]] = []
        extract_entities(result, service, everywhere=everywhere)
        by_path: dict[str, list[int]] = {}
        for index, spec in enumerate(specs):
            for path in spec["paths"]:
                by_path.setdefault(path, []).append(index)
        exposed: list[dict[str, None]] = [{} for _ in specs]
        whole = by_path.get("", [])
        claimed = set()
        for key, path in everywhere:
            for prefix in _prefixes(path):
                if prefix and prefix in by_path:
                    for index in by_path[prefix]:
                        exposed[index][key] = None
                    claimed.add(key)
                    break
        # a card for the whole answer gets what no record in it claimed
        for key, _ in everywhere:
            if key not in claimed:
                for index in whole:
                    exposed[index][key] = None
        for index, spec in enumerate(specs):
            own = [e.key for t, v in spec.pop("own", []) if v for e in [make_entity(t, v, typed=True)] if e]
            under = spec.pop("under", None)
            under_entity = make_entity(under[0], under[1], typed=True) if under else None
            keys = [k for k in exposed[index] if k not in known]
            if spec.pop("optional", False) and not (keys or spec.get("url") or spec.get("picture") or spec.get("facts")):
                continue    # a plugin's card about the answer itself (quota, paging), not a record
            found = {k: v for k, v in spec.items() if v not in (None, "", [])}
            found.update(service=service, method=method, timestamp=part.get("timestamp") or record.get("timestamp"),
                         subject=subject, exposed=keys, own=[k for k in own if k in exposed[index] or k in keys],
                         paths=spec["paths"][:50])
            if child_id:
                found["child_id"] = child_id
            if under_entity:
                found["under"] = under_entity.key
            found["traits"] = traits_of(found.get("facts") or [])
            if found.get("key") == "@parent":
                if parent_card is None:
                    continue
                # a follow-up that adds to the card it follows (a Telegram user's stats)
                found["key"] = parent_card["key"]
            if not found.get("key"):
                found["key"] = f"{found['kind']}:{record.get('result_id')}:{child_id or ''}:{index}"
            out.append(found)
            if child_id is None and parent_card is None and found["kind"] in ("account", "person"):
                parent_card = found
    return out


# ---------------------------------------------------------------------------
# cards.json
# ---------------------------------------------------------------------------

class CardsMixin:
    def _cards_file(self, investigation_id):
        return self._inv_dir(investigation_id) / "cards.json"

    def _load_cards(self, investigation_id) -> dict[str, list[dict[str, Any]]]:
        cards = _read_json(self._cards_file(investigation_id), {})
        return cards if isinstance(cards, dict) else {}

    def _save_cards(self, investigation_id, cards: dict[str, list[dict[str, Any]]]) -> None:
        _write_json_atomic(self._cards_file(investigation_id), cards, compact=True)

    def _update_cards(self, investigation_id, records: list[dict[str, Any]] = (), removed=()) -> None:
        """Rebuild the cards of ``records`` and drop those of the ``removed`` result ids."""
        cards = self._load_cards(investigation_id)
        for result_id in removed:
            cards.pop(result_id, None)
        for record in records:
            built = build_cards(record)
            if built:
                cards[record["result_id"]] = built
            else:
                cards.pop(record["result_id"], None)
        self._save_cards(investigation_id, cards)

    def _cards_snapshot(self, investigation_id) -> dict[str, Any]:
        """cards.json, parsed once per version of the file (as _entities_snapshot)."""
        path = self._cards_file(investigation_id)
        try:
            stat = path.stat()
        except FileNotFoundError:
            return {"raw": {}, "version": None}
        version = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
        cached = _CARD_CACHE.get(str(path))
        if cached is None or cached[0] != version:
            cached = _CARD_CACHE[str(path)] = (version, {"raw": self._load_cards(investigation_id), "version": version})
        return cached[1]
