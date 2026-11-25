"""Clues in a found profile that lead to more accounts ("follow the clues").

A profile that links to an account on a site we know (``x.com/moon_dev``), or names its
owner's username on a service (``twitter_username``), is a strong clue: the username
search follows it by itself. A different username in the profile's own fields, or an
@handle in its bio, is weak: it is suggested, not followed, unless a second profile
names it too.
"""
import ast
import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Optional
from urllib.parse import urlsplit

from services.entities import NOISE_USERNAMES, NOT_OWNER_PREFIXES

ACCOUNT = "{account}"
ACCOUNT_PART = r"([^/?#&=\s]+)"
PLACEHOLDER = "zzaccountzz"   # lowercase: hosts are compared lowercased

# Hosts that are another name for a site's host
HOST_ALIASES = {"twitter.com": "x.com", "mobile.twitter.com": "x.com", "telegram.me": "t.me",
                "telegram.dog": "t.me", "instagr.am": "instagram.com", "fb.com": "facebook.com",
                "m.facebook.com": "facebook.com", "youtu.be": "youtube.com"}
HOST_PREFIXES = ("www.", "m.", "mobile.")

# Usernames that are pages, not people (twitter.com/intent, t.me/share, github.com/settings ...)
GENERIC = {"about", "account", "accounts", "admin", "api", "app", "apps", "blog", "c", "channel", "contact",
           "discover", "download", "explore", "feed", "groups", "hashtag", "help", "home", "i", "intent",
           "login", "logout", "me", "messages", "new", "none", "null", "official", "p", "pages", "people",
           "photo", "photos", "privacy", "profile", "search", "settings", "share", "signin", "signup", "status",
           "terms", "u", "undefined", "user", "users", "watch", "web", "www"} | NOISE_USERNAMES

# Fields of a profile that hold links to other places
LINK_KEYS = {"links", "link", "urls", "url", "website", "websites", "site", "homepage", "blog", "social_links",
             "sociallinks", "bio_links", "linked_social", "social_accounts", "external_url", "sameas", "same_as"}
LINK_SUFFIXES = ("_url", "_urls", "_link", "_links")
PICTURE_KEY = re.compile(r"image|avatar|photo|picture|banner|icon|logo|cover|thumb|gravatar|feed|api", re.I)
# The profile's own username fields: a different value there is a weak clue
OWN_USERNAME_KEYS = {"username", "user_name", "usernames", "known_usernames", "login", "screen_name",
                     "nickname", "nick", "handle", "alternatename", "alternate_name"}
# "<service>_username": the owner's username on that service
SERVICE_USERNAME = re.compile(r"^([a-z0-9]+)_(username|screen_name|handle|login|nickname)$")
SERVICE_SITES = {"twitter": "X", "x": "X", "github": "GitHub (User)", "instagram": "Instagram",
                 "telegram": "Telegram", "tiktok": "TikTok", "reddit": "Reddit", "twitch": "Twitch",
                 "facebook": "Facebook", "youtube": "YouTube User2", "steam": "Steam", "medium": "Medium",
                 "gitlab": "GitLab", "pinterest": "Pinterest", "soundcloud": "SoundCloud", "keybase": "Keybase"}
BIO_KEYS = {"bio", "about", "description", "summary", "status", "signature", "headline"}
BIO_HANDLE = re.compile(r"(?<![\w.@/])@([A-Za-z0-9_][A-Za-z0-9_.]{1,29})(?![\w@]|\.[A-Za-z])")
URL_IN_TEXT = re.compile(r"(?:https?://)?(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?::\d+)?/[^\s,'\"<>()\[\]]*", re.I)


@dataclass
class Clue:
    value: str                  # the username it leads to
    kind: str                   # "link" (a link to an account) or "username" (a field naming one)
    strength: str               # "strong" (followed) or "weak" (suggested)
    field: str                  # the profile field it was in
    link: Optional[str] = None  # the link as the profile had it
    site: Optional[str] = None  # the site it names, when known

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


def plausible_username(value: str) -> bool:
    """A username, not a sentence, a link, an email, an id number or a page name."""
    if not isinstance(value, str) or not 2 <= len(value) <= 40:
        return False
    if re.search(r"\s|/|\\|://|^www\.|^https?", value, re.I) or ("@" in value and "." in value):
        return False
    if value.isdigit() or value.casefold() in GENERIC:
        return False
    return bool(re.fullmatch(r"[\w.\-]+", value))


def _host(netloc: str) -> str:
    host = netloc.lower().split("@")[-1].split(":")[0]
    host = HOST_ALIASES.get(host, host)
    for prefix in HOST_PREFIXES:
        if host.startswith(prefix):
            host = host[len(prefix):]
    return HOST_ALIASES.get(host, host)


class SiteLinks:
    """Links to profiles -> (site name, username), from each site's profile URL."""

    def __init__(self, sites: Iterable[dict]):
        self.by_host: dict[str, list[tuple[re.Pattern, str]]] = {}
        self.wildcard: list[tuple[re.Pattern, str]] = []   # {account}.example.com
        self.names: dict[str, dict] = {}
        for site in sites:
            self.names[site.get("name", "")] = site
            template = site.get("uri_pretty") or site.get("uri_check") or ""
            if ACCOUNT not in template or "archive.org" in template or "/api/" in template:
                continue
            parts = urlsplit(template.replace(ACCOUNT, PLACEHOLDER))
            if PLACEHOLDER in parts.query or PLACEHOLDER in parts.fragment:
                continue   # a search page, not a profile
            host = _host(parts.netloc)
            path = re.escape(parts.path.rstrip("/")).replace(PLACEHOLDER, ACCOUNT_PART) + "/?"
            name = site.get("name", "")
            if PLACEHOLDER in host:
                pattern = re.compile(re.escape(host).replace(PLACEHOLDER, ACCOUNT_PART) + "\n" + path, re.I)
                self.wildcard.append((pattern, name))
            elif PLACEHOLDER in parts.path:
                self.by_host.setdefault(host, []).append((re.compile(path, re.I), name))

    def site(self, name: Optional[str]) -> Optional[dict]:
        return self.names.get(name or "")

    def match(self, url: str) -> Optional[tuple[str, str]]:
        """(site name, username) when the link is a profile on a site we check."""
        if "://" not in url:
            url = "https://" + url.lstrip("/")
        try:
            parts = urlsplit(url.strip())
        except ValueError:
            return None
        host, path = _host(parts.netloc), parts.path.rstrip("/")
        for pattern, name in self.by_host.get(host, []):
            found = pattern.fullmatch(path)
            if found:
                return name, found.group(1)
        for pattern, name in self.wildcard:
            found = pattern.fullmatch(f"{host}\n{path}")
            if found:
                return name, found.group(1)
        return None


def _values(value: Any) -> list[str]:
    """The plain values in a field: socid_extractor writes lists as "['a', 'b']"."""
    if isinstance(value, (list, tuple, set)):
        return [v for item in value for v in _values(item)]
    if isinstance(value, dict):
        return [v for item in value.values() for v in _values(item)]
    if not isinstance(value, (str, int)):
        return []
    text = str(value).strip()
    if text.startswith(("[", "{")):
        try:
            return _values(ast.literal_eval(text))
        except (ValueError, SyntaxError):
            pass
    return [text] if text else []


def _fields(profile: dict, prefix: str = "", depth: int = 0):
    """(field name, value) for every field, nested ones two levels down."""
    for key, value in profile.items():
        key = str(key)
        if isinstance(value, dict) and depth < 2 and not any(k in key.lower() for k in ("image", "avatar")):
            yield from _fields(value, f"{prefix}{key}.", depth + 1)
        else:
            yield f"{prefix}{key}", value


def _is_link_field(key: str) -> bool:
    short = key.rsplit(".", 1)[-1].lower()
    return (short in LINK_KEYS or short.endswith(LINK_SUFFIXES)) and not PICTURE_KEY.search(short)


GENERIC_NAME_WORDS = {"user", "users", "channel", "profile", "account", "accounts", "app", "official", "the"}


def site_own_names(site_name: str, site: Optional[dict]) -> tuple[set[str], set[str]]:
    """The ways a site names itself, lowercase letters and digits only: its name (whole and
    without words like "User": "rumbleuser", "rumble"), its domain ("castingcall", "kofi"),
    and its initials ("ccc" for Casting Call Club). (names, initials)"""
    words = [w.lower() for w in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", site_name or "")]
    names = {"".join(words), "".join(w for w in words if w not in GENERIC_NAME_WORDS)}
    for template in ((site or {}).get("uri_pretty"), (site or {}).get("uri_check")):
        if template:
            labels = _host(urlsplit(template.replace(ACCOUNT, PLACEHOLDER)).netloc).split(".")
            labels = [label for label in labels if PLACEHOLDER not in label]
            if len(labels) >= 2:
                names.add(re.sub(r"[^a-z0-9]", "", labels[-2]))
    initials = {"".join(w[0] for w in words if w not in GENERIC_NAME_WORDS)} if len(words) >= 2 else set()
    return {n for n in names if len(n) >= 3}, {i for i in initials if len(i) >= 2}


def is_site_own(value: str, own: tuple[set[str], set[str]]) -> bool:
    """A username that is the site's own (its account elsewhere, in a page's footer or the
    site's own description), not the profile owner's: "castingcallclub" on CastingCallClub,
    "rumblevideo" on Rumble, "kofi_button" on Ko-fi, "CCC"."""
    names, initials = own
    flat = re.sub(r"[^a-z0-9]", "", value.lower())
    if flat in initials:
        return True
    return any(flat == name or (len(name) >= 4 and (flat.startswith(name) or name.startswith(flat) and len(flat) >= 4))
               for name in names)


def find_clues(profile: Optional[dict], site_name: str, searched: str, links: SiteLinks) -> list[Clue]:
    """The clues in one found profile (on ``site_name``, found for ``searched``)."""
    if not isinstance(profile, dict):
        return []
    found: dict[str, Clue] = {}
    searched_key = searched.casefold().lstrip("@")
    own = site_own_names(site_name, links.site(site_name))

    def add(clue: Clue):
        clue.value = clue.value.lstrip("@").strip(".")
        key = clue.value.casefold()
        if key == searched_key or not plausible_username(clue.value) or is_site_own(clue.value, own):
            return
        if clue.site == site_name and clue.kind == "link":
            clue.strength = "weak"   # the same site: often a team, a friend, a repository owner
        old = found.get(key)
        if old is None or (old.strength == "weak" and clue.strength == "strong"):
            found[key] = clue

    for key, value in _fields(profile):
        short = key.rsplit(".", 1)[-1].lower()
        service = SERVICE_USERNAME.match(short)
        if _is_link_field(key):
            for text in _values(value):
                for link in URL_IN_TEXT.findall(text) or ([text] if "." in text else []):
                    hit = links.match(link)
                    if hit:
                        add(Clue(hit[1], "link", "strong", key, link=link, site=hit[0]))
        elif service and service.group(1) not in NOT_OWNER_PREFIXES and "email" not in short:
            for text in _values(value):
                add(Clue(text, "username", "strong", key, site=SERVICE_SITES.get(service.group(1))))
        elif short in OWN_USERNAME_KEYS:
            for text in _values(value):
                add(Clue(text, "username", "weak", key))
        elif short in BIO_KEYS:
            for text in _values(value):
                for handle in BIO_HANDLE.findall(text):
                    add(Clue(handle, "username", "weak", key))
    return list(found.values())
