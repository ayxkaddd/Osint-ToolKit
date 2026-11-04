"""Dated events inside results, for the investigation's timeline.

The results list is ordered by when a lookup ran. This finds when things
*happened*: an account was created, a domain changed owner, an infection
leaked a login, a name was changed, messages were posted.

Dates are found by key (``created_at``, ``creation_date``, ``lastSeen``,
``date``...) and only kept when the value parses as a plausible date. Keys
that record when a module fetched something (``checked_at``) are skipped.
Many dates under the same list (every message of a chat) become one series
with a count and a first/last date instead of thousands of rows.
"""
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Optional

from services.entities import SERVICE_SKIP_KEYS, SKIP_KEY_RE

# Words that make a key a date (after camelCase and separators are split)
DATE_WORDS = {
    "date", "time", "datetime", "timestamp", "created", "creation", "updated", "modified", "edited",
    "edit", "registered", "registration", "joined", "seen", "birth", "birthday", "born", "dob",
    "expires", "expiry", "expiration", "expired", "compromised", "leaked", "breach", "breached",
    "published", "posted", "uploaded", "since", "online", "changed", "year",
}
# Last word that makes a key a date: created_at, registered_on, lastSeenTs
DATE_SUFFIXES = {"at", "on", "ts"}
# When a module fetched or computed something, not when it happened
RETRIEVAL_WORDS = {"checked", "fetched", "retrieved", "scanned", "requested", "cached", "generated",
                   "queried", "crawled", "indexed", "scan", "query", "search", "response", "request"}
# Durations and other numbers that look like dates by name
NOT_DATE_WORDS = {"seconds", "secs", "ms", "millis", "duration", "elapsed", "took", "timeout", "zone",
                  "timezone", "timezones", "format", "count", "name", "names", "type", "id"}

# Fields that say what a dated entry is about (a site, a name, a domain), looked for in
# the entry and the two objects around it; then identifiers in the entry itself
SUBJECT_KEYS = ("site", "platform", "name", "title", "service", "module", "source", "domain", "registrar",
                "event", "action", "label", "category")
IDENTIFIER_KEYS = ("username", "login", "email", "phone", "first_name", "type", "url")

SERIES_MIN = 20          # more dates than this under one list become one series
MAX_EVENTS_PER_PART = 500
MAX_STRINGS = 50_000
MIN_YEAR = 1900
MIN_EPOCH = datetime(1990, 1, 1, tzinfo=timezone.utc).timestamp()   # numbers before this are not dates
FUTURE_YEARS = 20         # expiry dates can be years ahead

ISO_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?)?"
                    r"\s*(Z|UTC|GMT|[+-]\d{2}:?\d{2})?$", re.I)
MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")
YEAR_RE = re.compile(r"^(\d{4})$")
DOTTED_RE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})(?:[ ,]+(\d{1,2}):(\d{2})(?::(\d{2}))?)?$")
DIGITS_RE = re.compile(r"^\d{9,13}(\.\d+)?$")
TEXT_FORMATS = ("%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%d %B %Y", "%b %Y", "%B %Y", "%d-%b-%Y",
                "%Y/%m/%d", "%Y/%m/%d %H:%M:%S", "%Y.%m.%d", "%Y%m%d")


def _words(key: str) -> list[str]:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key)
    return [w for w in re.split(r"[^a-z0-9]+", spaced.lower()) if w]


def is_date_key(key: str) -> bool:
    words = _words(key)
    if not words or set(words) & (RETRIEVAL_WORDS | NOT_DATE_WORDS):
        return False
    return bool(set(words) & DATE_WORDS) or (len(words) > 1 and words[-1] in DATE_SUFFIXES)


def humanize(key: str) -> str:
    text = " ".join(_words(key))
    return text[:1].upper() + text[1:]


def _plausible(moment: datetime, min_year: int = MIN_YEAR) -> bool:
    return min_year <= moment.year <= datetime.now().year + FUTURE_YEARS


def _from_epoch(number: float) -> Optional[datetime]:
    for scale in (1, 1000):
        seconds = number / scale
        if MIN_EPOCH <= seconds <= MIN_EPOCH + (datetime.now().year - 1990 + FUTURE_YEARS) * 366 * 86400:
            return datetime.fromtimestamp(seconds, tz=timezone.utc).replace(tzinfo=None)
    return None


def parse_date(value: Any, key: str = "") -> Optional[tuple[str, str]]:
    """(ISO date, precision) for a value that is a date, or None.
    Precision is "time", "day", "month" or "year". Aware times are turned into UTC."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        if "year" in _words(key) and isinstance(value, int):
            return (f"{value:04d}", "year") if MIN_YEAR <= value <= datetime.now().year + FUTURE_YEARS else None
        moment = _from_epoch(float(value))
        return (moment.strftime("%Y-%m-%dT%H:%M:%S"), "time") if moment else None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not 4 <= len(text) <= 40:
        return None

    if DIGITS_RE.match(text):
        return parse_date(float(text), key)
    if m := ISO_RE.match(text):
        year, month, day = int(m[1]), int(m[2]), int(m[3])
        hour, minute, second = int(m[4] or 0), int(m[5] or 0), int(m[6] or 0)
        try:
            moment = datetime(year, month, day, hour, minute, second)
        except ValueError:
            return None
        zone = (m[7] or "").upper()
        if zone and zone not in ("Z", "UTC", "GMT"):
            sign = 1 if zone[0] == "+" else -1
            digits = zone[1:].replace(":", "")
            moment -= sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:]))
        if not _plausible(moment):
            return None
        if m[4] and (hour, minute, second) != (0, 0, 0):
            return moment.strftime("%Y-%m-%dT%H:%M:%S"), "time"
        return moment.strftime("%Y-%m-%d"), "day"
    if m := MONTH_RE.match(text):
        if 1 <= int(m[2]) <= 12 and _plausible(datetime(int(m[1]), 1, 1)):
            return text, "month"
        return None
    if m := YEAR_RE.match(text):
        words = set(_words(key))
        year_key = "year" in words or "born" in words
        return (text, "year") if year_key and MIN_YEAR <= int(m[1]) <= datetime.now().year + FUTURE_YEARS else None
    if m := DOTTED_RE.match(text):
        try:
            moment = datetime(int(m[3]), int(m[2]), int(m[1]), int(m[4] or 0), int(m[5] or 0), int(m[6] or 0))
        except ValueError:
            return None
        if not _plausible(moment):
            return None
        return (moment.strftime("%Y-%m-%dT%H:%M:%S"), "time") if m[4] else (moment.strftime("%Y-%m-%d"), "day")
    if "," in text and re.search(r"\d{1,2}:\d{2}", text):
        try:   # RFC 2822: "Tue, 05 Mar 2019 10:00:00 GMT"
            moment = parsedate_to_datetime(text)
            if moment.tzinfo:
                moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
            if _plausible(moment):
                return moment.strftime("%Y-%m-%dT%H:%M:%S"), "time"
        except (TypeError, ValueError):
            pass
    for fmt in TEXT_FORMATS:
        try:
            moment = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if not _plausible(moment):
            return None
        if "%H" in fmt:
            return moment.strftime("%Y-%m-%dT%H:%M:%S"), "time"
        return (moment.strftime("%Y-%m"), "month") if "%d" not in fmt else (moment.strftime("%Y-%m-%d"), "day")
    return None


def _context(ancestors: list[dict[str, Any]], skip: str) -> Optional[dict[str, str]]:
    """ancestors: the dict holding the date first, then the ones around it."""
    def pick(obj: dict[str, Any], keys: tuple[str, ...]) -> Optional[dict[str, str]]:
        for key in keys:
            value = obj.get(key)
            if key != skip and isinstance(value, (str, int)) and not isinstance(value, bool):
                text = str(value).strip()
                if text and len(text) <= 120 and parse_date(value, key) is None:
                    return {"key": key, "value": text}
        return None
    for obj in ancestors[:3]:
        if found := pick(obj, SUBJECT_KEYS):
            return found
    return pick(ancestors[0], IDENTIFIER_KEYS)


def _section(path: str) -> str:
    """The list or object a date sits in: "names_history[3].date" -> "Names history"."""
    parts = [p for p in re.split(r"\[\d+\]|\.", path) if p]
    return humanize(parts[-2]) if len(parts) > 1 else ""


def extract_events(result: Any, service: str = "", lookup_time: Optional[str] = None) -> list[dict[str, Any]]:
    """Dated events in one result payload, oldest first. Series (many dates
    under one list) are returned as one event with ``count`` and ``end``."""
    found: list[dict[str, Any]] = []
    strings = [0]
    skip_keys = SERVICE_SKIP_KEYS.get(service, ())
    try:
        fetched = datetime.fromisoformat(lookup_time) if lookup_time else None
    except ValueError:
        fetched = None

    def visit(value: Any, path: str, depth: int, ancestors: list[dict[str, Any]]):
        if depth > 12 or strings[0] >= MAX_STRINGS:
            return
        if isinstance(value, dict):
            ancestors = [value] + ancestors
            for k, v in value.items():
                k = str(k)
                if SKIP_KEY_RE.search(k) or k in skip_keys:
                    continue
                sub = f"{path}.{k}" if path else k
                if isinstance(v, (dict, list)):
                    visit(v, sub, depth + 1, ancestors)
                    continue
                strings[0] += 1
                if not is_date_key(k):
                    continue
                parsed = parse_date(v, k)
                if not parsed:
                    continue
                date, precision = parsed
                if fetched and precision == "time" and abs(
                        (datetime.fromisoformat(date) - fetched).total_seconds()) < 120:
                    continue   # the moment the lookup ran
                found.append({"date": date, "precision": precision, "label": humanize(k),
                              "section": _section(sub), "context": _context(ancestors, k), "path": sub})
        elif isinstance(value, list):
            for i, v in enumerate(value[:5000]):
                visit(v, f"{path}[{i}]", depth + 1, ancestors)

    visit(result, "", 0, [])

    groups: dict[str, list[dict[str, Any]]] = {}
    for event in found:
        groups.setdefault(re.sub(r"\[\d+\]", "[]", event["path"]), []).append(event)
    events: list[dict[str, Any]] = []
    for pattern, items in groups.items():
        if len(items) > SERIES_MIN and "[]" in pattern:
            items.sort(key=lambda e: e["date"])
            events.append({"date": items[0]["date"], "precision": items[0]["precision"],
                           "end": items[-1]["date"], "end_precision": items[-1]["precision"],
                           "count": len(items), "label": items[0]["label"], "section": items[0]["section"],
                           "context": None, "path": pattern})
        else:
            seen = set()
            for event in items:
                marker = (event["date"], event["label"], (event["context"] or {}).get("value"))
                if marker not in seen:
                    seen.add(marker)
                    events.append(event)
    events.sort(key=lambda e: e["date"])
    return events[:MAX_EVENTS_PER_PART]
