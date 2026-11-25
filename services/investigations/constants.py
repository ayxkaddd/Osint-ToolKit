"""Limits, versions and names shared by the investigation modules."""
import re


# Bump when the index entry format / summary logic changes
INDEX_VERSION = 8

TRIAGE_STATUSES = {None, "confirmed", "important", "false_positive"}

# Bump when extract_events changes, so cached timelines are rebuilt (on next view)
EVENTS_VERSION = 2

# Bump when the graph model changes, so cached graphs are rebuilt
GRAPH_VERSION = 3

# Nodes in a graph's first view; past it the deepest lookups stay closed
GRAPH_NODE_BUDGET = 300

# A lookup's findings shown one by one; more are folded into groups
GRAPH_INLINE_MAX = 8

# Results added by hand (data from sites and tools without an API)
MANUAL_SERVICE = "manual"

MANUAL_FILES_MAX = 20

MANUAL_FILE_MAX_UPLOAD = 50 * 1024 * 1024

MANUAL_TEXT_MAX = 1024 * 1024

# Text files up to this size are read too, so their identifiers and dates are found
MANUAL_FILE_TEXT_MAX = 2 * 1024 * 1024

MANUAL_TEXT_EXTS = {"txt", "csv", "tsv", "json", "log", "md", "xml", "html", "htm"}

MANUAL_FILE_NAME = re.compile(r"[0-9a-f]{32}\.[a-z0-9]{1,10}")

# An identifier referenced in a note: [[email:a@b.c]] or [[email:a@b.c|label]]
NOTE_ENTITY_REF = re.compile(r"\[\[([a-z_]+):([^\]|\n]+)(?:\|[^\]\n]*)?\]\]")

# Comparing two runs of a lookup: values that differ every run (when, how long, request ids)
CHANGES_VOLATILE_KEYS = {"checked_at", "fetched_at", "retrieved_at", "scanned_at", "generated_at", "timestamp",
                         "response_time", "duration", "search_time_seconds", "took", "elapsed", "progress",
                         "search_id", "request_id", "completed"}

CHANGES_MAX_LEAVES = 20_000

CHANGES_MAX_PATHS = 40

CHANGES_MAX_VALUES = 30

# Google tags BuiltWith lists the websites of (as in main.js builtwithTagUrl)
BUILTWITH_TAG = re.compile(r"UA-\d{4,10}|G-[A-Z0-9]{8,12}|GTM-[A-Z0-9]{5,8}|pub-\d{14,20}")

# Already compressed: stored as they are in the export
STORED_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".zip", ".gz", ".mp4", ".mp3"}

PICTURE_MAX_SIDE = 512

PICTURE_MAX_UPLOAD = 10 * 1024 * 1024

NOTE_IMAGE_MAX_UPLOAD = 20 * 1024 * 1024

NOTE_IMAGE_MAX_PIXELS = 50_000_000

NOTE_IMAGE_MAX_SIDE = 4096

NOTE_IMAGE_FORMATS = ("PNG", "JPEG", "WEBP", "GIF", "BMP")

NOTE_IMAGE_NAME = re.compile(r"[0-9a-f]{32}\.webp")

# Old service names that were saved under a different key
SERVICE_RENAMES = {"username_search": "username"}

# Module pages ask for history by these names
SERVICE_ALIASES = {
    "username": {"username", "username_search"},
    "ns": {"ns", "ns_lookup"},
    "ns_lookup": {"ns", "ns_lookup"},
}

# Parameter names that identify what a lookup was about, in priority order
TARGET_KEYS = (
    "username", "domain", "email", "query", "phones", "phone", "ns1", "user_id",
    "gaia_id", "bssid", "drive_url", "url", "link", "links", "term", "input",
    "target", "group_id", "id", "domains", "filename", "image", "title",
)
