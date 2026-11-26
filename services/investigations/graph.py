"""The investigation graph: what was looked up, what each lookup found about it, and
what that exposed.

Built on the server so the browser only draws what is open. Lookups are not drawn: the
cards (cards.py) sit between identifiers, an account or a breach record under the
identifier it was found for, the identifiers in that record under the card. Node ids are
stable across rebuilds (saved positions and hidden marks refer to them):

    e:<entity key>                  an identifier, one per case however many lookups found it
    c:<card key>                    a card: an account, a breach record, a registration... (the same
                                    thing found by several lookups is one card)
    f:<kind>:<hash>                 a fact two cards share (a password, an address, a birth date, a city)
    g:<owner id>:<group key>        the children of one kind folded under a node ("Accounts · social")
    more:<group id>:<offset>        the rest of an opened group, past the first page

Edges run identifier -> card ("card": account, in breach...), card -> identifier ("exposes"),
card -> shared fact ("fact"), node -> group ("found"), group -> member ("member"), and from
a lookup's identifier to what it found that no card holds ("found"). Each node hangs under
one parent (``home``); its other links are cross links.
"""
import hashlib
import math
from itertools import pairwise
import re
import threading
from datetime import datetime
from typing import Annotated, Any, Literal, Optional
from urllib.parse import urljoin, urlparse
from uuid import UUID
from xml.etree import ElementTree

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from services.entities import ENTITY_TYPES, NOISE_DOMAINS, NOISE_EMAIL_LOCALS, Entity, is_noise
from .cards import CARD_KINDS, TRAIT_NAMES
from .constants import (GRAPH_GROUPS_MAX, GRAPH_INLINE_MAX, GRAPH_NODE_BUDGET, GRAPH_TOP, GRAPH_VERSION, MANUAL_SERVICE,
                        NOTE_IMAGE_NAME)
from .images import process_note_image
from .storage import _GRAPH_CACHE, _SHARED_CACHE, _STORE_LOCK, _read_json, _write_json_atomic

TRIAGE_RANK = {"confirmed": 0, "important": 1, None: 2, "false_positive": 3}

# The order of a node's cards: accounts first, mentions last
CARD_ORDER = {"account": 0, "person": 1, "breach": 2, "registration": 3, "network": 4, "place": 5, "document": 6,
              "record": 7, "mention": 8}

# What the link from an identifier to its card says
RELATIONS = {"account": "account", "breach": "in breach", "person": "linked", "registration": "registration",
             "network": "network", "place": "place", "mention": "mentioned", "document": "document",
             "record": "found"}

# Facts on cards that say where someone is (the summary's places)
PLACE_LABEL = re.compile(r"^(location|city|town|hometown|address|address street|country|region|place|locality)$", re.I)

GRAPH_CACHE_MAX = 8

# Where username search finds a profile's picture, and the stand-ins sites show when
# there is none (both as in static/js/services/username.js)
PICTURE_FIELDS = ("profileImageUrl", "profile_image_url", "profilePic", "profile_pic", "image", "avatar",
                  "avatar_static", "avatar_url", "icon_img", "logo", "logoUrl", "pic_url", "photo", "photo_url",
                  "picture")
DEFAULT_PICTURE = re.compile(r"default[_-]?(avatar|profile|user|photo|image|pic)|(avatar|profile|user)[_-]?default"
                             r"|/defaults?/|no[_-]?(avatar|photo|image)|placeholder|blank[_-]?(avatar|profile)", re.I)

# Requests run in threads; the cache's order changes on every read
_GRAPH_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# The saved view (graph.json): what the analyst moved, opened, hid and added
# ---------------------------------------------------------------------------
# Things the analyst can add besides identifiers
MANUAL_NODE_TYPES = ("person", "organisation", "location", "event", "note", "image")

NodeId = Annotated[str, StringConstraints(min_length=1, max_length=1000)]
Label = Annotated[str, StringConstraints(max_length=200)]
Name = Annotated[str, StringConstraints(max_length=100)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GraphManualNode(_Strict):
    id: str = Field(pattern=r"^m:[0-9a-f]{32}$")
    type: str
    label: str = Field(min_length=1, max_length=200)
    note: str = Field("", max_length=5000)
    url: Optional[str] = Field(None, max_length=2000)
    image: Optional[str] = Field(None, max_length=60)      # a note image (POST .../note-images)
    color: Optional[str] = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")

    @field_validator("type")
    @classmethod
    def _known_type(cls, value: str) -> str:
        if value not in ENTITY_TYPES and value not in MANUAL_NODE_TYPES:
            raise ValueError("unknown node type")
        return value

    @field_validator("url")
    @classmethod
    def _web_link(cls, value: Optional[str]) -> Optional[str]:
        value = (value or "").strip()
        if value and not re.match(r"https?://\S+$", value, re.I):
            raise ValueError("the link must start with http:// or https://")
        return value or None

    @field_validator("image")
    @classmethod
    def _note_image(cls, value: Optional[str]) -> Optional[str]:
        if value and not NOTE_IMAGE_NAME.fullmatch(value):
            raise ValueError("not an uploaded image")
        return value or None


class GraphManualEdge(_Strict):
    id: str = Field(pattern=r"^l:[0-9a-f]{32}$")
    source: NodeId
    target: NodeId
    label: Label = ""


class GraphViewport(_Strict):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    zoom: float = Field(ge=0.01, le=10)
    x: float = Field(ge=-1e8, le=1e8)
    y: float = Field(ge=-1e8, le=1e8)


class GraphFilters(_Strict):
    kinds: list[Name] = Field(default_factory=list, max_length=20)
    types: list[Name] = Field(default_factory=list, max_length=40)
    modules: list[Name] = Field(default_factory=list, max_length=200)
    triage: list[Name] = Field(default_factory=list, max_length=5)
    date_from: Optional[Name] = None
    date_to: Optional[Name] = None
    shared_only: bool = False
    leaked: bool = False
    linked: bool = False
    noise: bool = False


class GraphState(_Strict):
    """graph.json. Node ids are the graph's (e:..., r:..., g:..., m:...); ids that are no
    longer in the graph are kept, so a deleted and re-run lookup comes back as it was.
    ``positions``: where each node was drawn; ``pinned``: the ones the analyst moved
    (tidying up leaves them). A view saved before ``pinned`` existed has only moved nodes
    in ``positions``."""
    positions: dict[NodeId, tuple[float, float]] = Field(default_factory=dict)
    pinned: Optional[list[NodeId]] = Field(None, max_length=5000)
    # the browser's layout the positions were made for; older positions are dropped once
    version: Optional[int] = Field(None, ge=0, le=1000)
    expanded: list[NodeId] = Field(default_factory=list, max_length=5000)
    collapsed: list[NodeId] = Field(default_factory=list, max_length=5000)
    hidden: list[NodeId] = Field(default_factory=list, max_length=5000)
    removed: list[NodeId] = Field(default_factory=list, max_length=5000)
    manual_nodes: list[GraphManualNode] = Field(default_factory=list, max_length=1000)
    manual_edges: list[GraphManualEdge] = Field(default_factory=list, max_length=2000)
    viewport: Optional[GraphViewport] = None
    filters: Optional[GraphFilters] = None
    layout: Literal["tree", "web"] = "tree"

    @field_validator("positions")
    @classmethod
    def _positions(cls, value: dict[str, tuple[float, float]]) -> dict[str, tuple[float, float]]:
        if len(value) > 5000:
            raise ValueError("at most 5000 positions")
        if not all(math.isfinite(c) and abs(c) <= 1e7 for point in value.values() for c in point):
            raise ValueError("positions must be numbers")
        return {node: (round(x), round(y)) for node, (x, y) in value.items()}


def _noise_domain(host: str) -> bool:
    return host in NOISE_DOMAINS or any(host.endswith("." + d) for d in NOISE_DOMAINS)


def graph_noise(entity: dict[str, Any]) -> bool:
    """Boilerplate found in results (abuse@ addresses, CDN hosts, mail providers):
    folded out of the graph unless asked for. What was searched is never noise."""
    entity_type, value = entity.get("type"), str(entity.get("value") or "")
    if entity_type == "email":
        local, _, domain = value.partition("@")
        return any(noise in local for noise in NOISE_EMAIL_LOCALS) or _noise_domain(domain)
    if entity_type == "domain" and _noise_domain(value):
        return True
    if entity_type == "url":
        return _noise_domain((urlparse(value).hostname or "").lower())
    return is_noise(Entity(entity_type, value))


def profile_picture(site: dict[str, Any]) -> Optional[str]:
    """The picture of a profile a username search found (as the username page finds it),
    unless it is the site's stand-in for no picture."""
    profile = site.get("profile_data")
    if not isinstance(profile, dict):
        return None
    for field in PICTURE_FIELDS:
        value = profile.get(field)
        if isinstance(value, dict):
            value = value.get("url")
        if isinstance(value, str) and value.strip():
            picture = urljoin(str(site.get("url") or ""), value.strip())
            if urlparse(picture).scheme in ("http", "https") and not DEFAULT_PICTURE.search(picture):
                return picture[:2000]
            return None
    return None


def _card_id(key: str) -> str:
    return f"c:{key}" if len(key) <= 300 else f"c:{hashlib.sha256(key.encode()).hexdigest()[:40]}"


def _lookup_id(result_id: str, child_id: Optional[str] = None) -> str:
    return f"r:{result_id}:{child_id}" if child_id else f"r:{result_id}"


def _edge(source: str, target: str, kind: str, lookup: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    edge = {"id": f"{source}>{target}", "source": source, "target": target, "kind": kind}
    if lookup:
        edge.update(service=lookup["service"], method=lookup["method"], timestamp=lookup["timestamp"])
    return edge


class GraphMixin:
    def _graph_file(self, investigation_id):
        return self._inv_dir(investigation_id) / "graph.json"

    def get_graph_state(self, investigation_id: UUID) -> dict[str, Any]:
        """The saved view (positions, hidden and removed nodes, what the analyst added)."""
        state = _read_json(self._graph_file(investigation_id), {})
        return state if isinstance(state, dict) else {}

    def save_graph_state(self, investigation_id: UUID, state: GraphState) -> dict[str, Any]:
        saved = {**state.model_dump(mode="json", exclude_none=True), "updated_at": datetime.now().isoformat()}
        with _STORE_LOCK:
            _write_json_atomic(self._graph_file(investigation_id), saved, compact=True)
        return saved

    # -- the model: everything about the case's graph, rebuilt when its files change --

    def _graph_model(self, investigation_id: UUID, noise: bool = False) -> dict[str, Any]:
        snapshot = self._entities_snapshot(investigation_id)
        cards = self._cards_snapshot(investigation_id)
        shared_index = self._shared_index()
        try:
            stat = self._index_file(investigation_id).stat()
            index_version = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
        except FileNotFoundError:
            index_version = None
        cache_key = (str(UUID(str(investigation_id))), noise)
        version = (GRAPH_VERSION, snapshot["version"], cards["version"], index_version, _SHARED_CACHE["versions"])
        with _GRAPH_LOCK:
            cached = _GRAPH_CACHE.get(cache_key)
            if cached and cached[0] == version:
                _GRAPH_CACHE.move_to_end(cache_key)
                return cached[1]
        model = self._build_graph_model(investigation_id, snapshot["raw"], cards["raw"], shared_index, noise)
        with _GRAPH_LOCK:
            _GRAPH_CACHE[cache_key] = (version, model)
            while len(_GRAPH_CACHE) > GRAPH_CACHE_MAX:
                _GRAPH_CACHE.popitem(last=False)
        return model

    def _graph_lookups(self, investigation_id: UUID, raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
        """Every saved lookup (a result, or a follow-up attached to one). Running a module
        again on the same identifiers is one lookup with several runs, under the id of its
        first run; the latest run stands for it. Returns (lookups, {run id: lookup id})."""
        runs: dict[str, dict[str, Any]] = {}
        for result_id, entry in self._load_index(investigation_id).items():
            run_id = _lookup_id(result_id)
            runs[run_id] = {
                "id": run_id, "result_id": result_id, "child_id": None, "parent": None,
                "service": entry.get("service_name") or "", "method": entry.get("method_name") or "",
                "target": entry.get("target"), "summary": entry.get("summary"),
                "timestamp": entry.get("timestamp"), "triage": (entry.get("triage") or {}).get("status"),
                "partial": bool(entry.get("partial")),
            }
            for child in entry.get("children") or []:
                if child.get("child_id"):
                    child_run = _lookup_id(result_id, child["child_id"])
                    runs[child_run] = {
                        **runs[run_id], "id": child_run, "child_id": child["child_id"],
                        "parent": run_id, "service": child.get("service_name") or "",
                        "method": child.get("method_name") or "", "target": child.get("target"),
                        "summary": child.get("summary"), "timestamp": child.get("timestamp"),
                        "triage": None, "partial": False,
                    }
        run_searched: dict[str, set] = {}
        for key, entity in raw.items():
            for src in entity.get("sources") or []:
                if src.get("role") == "searched":
                    run_searched.setdefault(_lookup_id(src.get("result_id"), src.get("child_id")), set()).add(key)
        merged: dict[str, str] = {}
        lookups: dict[str, dict[str, Any]] = {}
        firsts: dict[tuple, str] = {}
        for run in sorted(runs.values(), key=lambda r: (r["parent"] is not None, r["timestamp"] or "")):
            parent = merged.get(run["parent"]) if run["parent"] else None
            searched = frozenset(run_searched.get(run["id"], ()))
            signature = (run["service"], run["method"], searched or (str(run["target"]), parent),
                         run["id"] if run["service"] == MANUAL_SERVICE else None)
            lookup_id = merged[run["id"]] = firsts.setdefault(signature, run["id"])
            if lookup_id == run["id"]:
                lookups[lookup_id] = {**run, "parent": parent, "runs": [], "searched": [], "found": []}
            lookup = lookups[lookup_id]
            lookup["runs"].insert(0, {k: run[k] for k in ("result_id", "child_id", "timestamp", "partial")})
            lookup.update({k: run[k] for k in ("result_id", "child_id", "target", "summary", "timestamp",
                                               "triage", "partial")})
        return lookups, merged

    def _build_graph_model(self, investigation_id: UUID, raw: dict[str, Any], raw_cards: dict[str, Any],
                           shared_index: dict[str, list[dict[str, Any]]], noise: bool) -> dict[str, Any]:
        here = str(investigation_id)
        lookups, merged = self._graph_lookups(investigation_id, raw)

        # -- identifiers --
        entities: dict[str, dict[str, Any]] = {}
        left_out = {"noise": 0, "false_positive": 0}
        for key, entity in raw.items():
            searched_in, found_in = [], []
            for src in entity.get("sources") or []:
                run_id = _lookup_id(src.get("result_id"), src.get("child_id"))
                if run_id in merged:
                    (searched_in if src.get("role") == "searched" else found_in).append(merged[run_id])
            searched_in, found_in = list(dict.fromkeys(searched_in)), list(dict.fromkeys(found_in))
            # Identifiers whose results were all deleted stay only when triaged or noted
            if not searched_in and not found_in and not (entity.get("status") or entity.get("note")):
                continue
            if not noise:
                if entity.get("status") == "false_positive":
                    left_out["false_positive"] += 1
                    continue
                if not searched_in and graph_noise(entity):
                    left_out["noise"] += 1
                    continue
            entities[key] = {"entity": entity, "searched_in": searched_in, "found_in": found_in, "cards": [],
                             "shared": sum(1 for p in shared_index.get(key, []) if p["investigation_id"] != here)}
            for lookup_id in searched_in:
                lookups[lookup_id]["searched"].append(key)
            for lookup_id in found_in:
                lookups[lookup_id]["found"].append(key)

        # -- cards: the same thing found by several lookups is one card --
        cards: dict[str, dict[str, Any]] = {}
        sectioned: dict[str, tuple[str, list[dict[str, Any]]]] = {}   # lookup id -> (run time, its sections)
        for result_id, built in raw_cards.items():
            for found in built if isinstance(built, list) else []:
                lookup_id = merged.get(_lookup_id(result_id, found.get("child_id")))
                if lookup_id is None or not found.get("key"):
                    continue
                if found.get("kind") == "section":
                    # the latest run's sections stand for the lookup
                    when = found.get("timestamp") or ""
                    if lookup_id not in sectioned or sectioned[lookup_id][0] < when:
                        sectioned[lookup_id] = (when, [])
                    if sectioned[lookup_id][0] == when:
                        sectioned[lookup_id][1].append(found)
                    continue
                card_id = _card_id(found["key"])
                card = cards.get(card_id)
                if card is None:
                    card = cards[card_id] = {
                        "id": card_id, "key": found["key"], "kind": found.get("kind") or "record",
                        "title": found.get("title") or "", "relation": found.get("relation"),
                        "facts": [], "flags": [], "traits": {}, "subject": [], "exposed": [], "own": [],
                        "under": None, "lookups": [], "runs": [], "first": found.get("timestamp") or "",
                    }
                for field in ("subtitle", "site", "url", "picture", "category", "date"):
                    if found.get(field) and not card.get(field):
                        card[field] = found[field]
                seen = {(label, value) for label, value in card["facts"]}
                card["facts"] += [f for f in found.get("facts") or [] if (f[0], f[1]) not in seen][:max(0, 40 - len(card["facts"]))]
                card["flags"] += [f for f in found.get("flags") or [] if f not in card["flags"]]
                for kind, ident, shown in found.get("traits") or []:
                    card["traits"].setdefault((kind, ident), shown)
                for field in ("subject", "exposed", "own"):
                    card[field] += [k for k in found.get(field) or [] if k in entities and k not in card[field]]
                if not card["under"] and found.get("under") in entities:
                    card["under"] = found["under"]
                if lookup_id not in card["lookups"]:
                    card["lookups"].append(lookup_id)
                card["runs"].append({"result_id": result_id, "child_id": found.get("child_id"),
                                     "service": found.get("service"), "method": found.get("method"),
                                     "timestamp": found.get("timestamp")})
                card["first"] = min(card["first"], found.get("timestamp") or card["first"])
        order = sorted(cards, key=lambda cid: (cards[cid]["first"], cid))

        # An identifier that is the card itself (an account's address, a Google account's
        # Gaia ID) is drawn as the card, unless it was looked up or assessed
        alias: dict[str, str] = {}
        for card_id in order:
            for key in cards[card_id]["own"]:
                info = entities[key]
                if key not in alias and not info["searched_in"] and not info["entity"].get("status") \
                        and not info["entity"].get("note"):
                    alias[key] = card_id
        for card_id in order:
            card = cards[card_id]
            # what it hangs under is not in it too (the domain a WHOIS record is about)
            card["exposed"] = [k for k in card["exposed"] if alias.get(k) != card_id and k != card["under"]
                               and k not in card["subject"]]
            for key in card["exposed"] + card["own"]:
                if card_id not in entities[key]["cards"]:
                    entities[key]["cards"].append(card_id)

        def node_of(key: str) -> str:
            return alias.get(key) or f"e:{key}"

        # -- the tree: what each node hangs under --
        parent: dict[str, Optional[str]] = {}
        via: dict[str, str] = {}                 # identifier node -> the lookup that found it (no card did)

        origins: dict[str, str] = {}

        def origin(lookup_id: str) -> str:
            """Where what a lookup found hangs: what it looked up, or, for a lookup that looked
            up no identifier (a text search, something added by hand), the lookup itself."""
            if lookup_id not in origins:
                node = next((node_of(k) for k in lookups[lookup_id]["searched"]), None)
                if node is None:
                    node = lookup_id
                    parent.setdefault(lookup_id, None)
                origins[lookup_id] = node
            return origins[lookup_id]

        for card_id in order:
            card = cards[card_id]
            owners = [node_of(k) for k in ([card["under"]] if card["under"] else []) + card["subject"]]
            owners.append(origin(card["lookups"][0]))
            parent[card_id] = next((o for o in owners if o != card_id), None)
        for key, info in entities.items():
            if key in alias:
                continue
            node = f"e:{key}"
            homes = [cid for cid in info["cards"] if key in cards[cid]["exposed"]]
            if homes:
                parent[node] = min(homes, key=lambda cid: (cards[cid]["first"], cid))
                continue
            parent[node] = None
            # found by lookups no card of which holds it: under what that lookup searched
            for lookup_id in sorted(info["found_in"], key=lambda lid: lookups[lid]["runs"][-1]["timestamp"] or ""):
                owner = origin(lookup_id)
                if owner != node:
                    via[node] = lookup_id
                    parent[node] = owner
                    break
        for lookup_id, lookup in lookups.items():      # for the links from a second finder (_links)
            origins.setdefault(lookup_id, next((node_of(k) for k in lookup["searched"]), lookup_id))
        # never a loop (A's card exposes B, B's card exposes A): what was looked up first is a root
        for start in list(parent):
            seen, node = [start], parent.get(start)
            while node is not None and node not in seen:
                seen.append(node)
                node = parent.get(node)
            if node is not None:
                loop = seen[seen.index(node):]
                searched = [n for n in loop if n.startswith("e:") and entities[n[2:]]["searched_in"]]
                identifiers = [n for n in loop if n.startswith("e:")]
                cut = min(searched or identifiers or loop, key=lambda n: self._node_time(n, entities, cards, lookups))
                parent[cut] = None

        # -- facts two records share: a password, an address, a birth date, a city --
        fact_cards: dict[tuple[str, str], list[str]] = {}
        for card_id in order:
            for trait in cards[card_id]["traits"]:
                fact_cards.setdefault(trait, []).append(card_id)
        facts: dict[str, dict[str, Any]] = {}
        for (kind, ident), owners in fact_cards.items():
            if len(owners) > 1:
                fact_id = f"f:{kind}:{ident}"
                facts[fact_id] = {"id": fact_id, "kind": kind, "shown": cards[owners[0]]["traits"][(kind, ident)],
                                  "cards": owners}
                parent[fact_id] = owners[0]

        # a lookup's results in the sections of its page (DNS recon, NS): a node each under what it
        # looked up ("g:<owner>:section:<lookup>:<key>", folded at first), what is in it under it
        sections: dict[str, dict[str, Any]] = {}
        for lookup_id, (_, rows) in sectioned.items():
            owner = origins.get(lookup_id)
            for row in sorted(rows, key=lambda r: r.get("order", 0)):
                section_id = f"g:{owner}:section:{lookup_id}:{row['key']}"
                nodes = [_card_id(k) for k in row.get("cards") or []] + [node_of(k) for k in row.get("members") or []
                                                                         if k in entities]
                members = [n for n in dict.fromkeys(nodes) if n in parent and parent[n] == owner]
                if not members or owner not in parent:
                    continue
                sections[section_id] = {"owner": owner, "lookup": lookup_id, "row": row}
                parent[section_id] = owner
                for node in members:
                    parent[node] = section_id

        children: dict[Optional[str], list[str]] = {}
        for node, owner in parent.items():
            children.setdefault(owner, []).append(node)

        # -- what matters: drawn whatever the budget, with the way to it --
        must, extra = set(), []
        for key, info in entities.items():
            if key in alias:
                continue
            entity = info["entity"]
            if info["searched_in"] or entity.get("status") in ("confirmed", "important") or entity.get("note") \
                    or parent.get(f"e:{key}") is None:
                must.add(f"e:{key}")
            elif len(info["cards"]) > 1 or info["shared"]:
                # what links records or cases: drawn while the budget allows, the most linked first
                extra.append(f"e:{key}")
        must.update(node for node, owner in parent.items() if owner is None and not node.startswith("e:"))
        must = self._with_ancestors(must, parent)
        extra.sort(key=lambda n: (-len(entities[n[2:]]["cards"]), -entities[n[2:]]["shared"], n))

        model = {"lookups": lookups, "runs": merged, "entities": entities, "cards": cards, "facts": facts,
                 "alias": alias, "parent": parent, "children": children, "via": via, "origins": origins,
                 "sections": sections,
                 "must": must, "extra": extra,
                 "left_out": left_out, "views": {}}
        for kids in children.values():
            kids.sort(key=lambda n: self._sibling_order(model, n))
        model["rank"] = {node: i for kids in children.values() for i, node in enumerate(kids)}
        return model

    @staticmethod
    def _with_ancestors(nodes: set, parent: dict[str, Optional[str]]) -> set:
        out = set(nodes)
        for node in nodes:
            up = parent.get(node)
            while up is not None and up not in out:
                out.add(up)
                up = parent.get(up)
        return out

    @staticmethod
    def _node_time(node: str, entities, cards, lookups) -> str:
        if node.startswith("c:"):
            return cards[node]["first"]
        if node.startswith("e:"):
            return entities[node[2:]]["entity"].get("first_seen") or ""
        if node in lookups:
            return lookups[node]["runs"][-1]["timestamp"] or ""
        return ""

    @staticmethod
    def _sibling_order(model: dict[str, Any], node: str) -> tuple:
        """A node's place among its siblings: cards (accounts, breaches...) by how much they say,
        identifiers by assessment and how often they were found, then shared facts."""
        if node in model["sections"]:
            return (0, -1, int(model["sections"][node]["row"].get("order") or 0), 0, "", node)
        if node.startswith("c:"):
            card = model["cards"][node]
            leads = sum(1 for k in card["exposed"] if f"e:{k}" in model["must"])
            richness = bool(card.get("picture")) + bool(card.get("subtitle")) + (len(card["facts"]) > 2) \
                + ("password" in card["flags"]) + len(card["lookups"]) - 1
            return (0, CARD_ORDER.get(card["kind"], 9), -leads, -richness, card["title"].casefold(), node)
        if node.startswith("e:"):
            info = model["entities"][node[2:]]
            entity = info["entity"]
            return (1, TRIAGE_RANK.get(entity.get("status"), 2), -len(model["children"].get(node, [])),
                    -len(info["cards"]) - len(info["found_in"]), entity.get("type") or "", entity.get("value") or "")
        if node in model["lookups"]:
            return (3, model["lookups"][node]["runs"][-1]["timestamp"] or "", node)
        return (2, node)

    # -- which children are drawn: one by one, or folded into groups --

    def _group_key(self, model: dict[str, Any], node: str) -> tuple[str, str]:
        if node.startswith("c:"):
            card = model["cards"][node]
            if card["kind"] == "account" and card.get("category"):
                return f"card:account:{card['category']}", f"Accounts · {card['category']}"
            return f"card:{card['kind']}", CARD_KINDS.get(card["kind"], "Records")
        if node.startswith("f:"):
            return "facts", "Shared facts"
        entity_type = model["entities"][node[2:]]["entity"].get("type")
        if node in model["via"]:
            return f"lookup:{model['via'][node]}", ENTITY_TYPES.get(entity_type, "Other")
        return f"type:{entity_type}", ENTITY_TYPES.get(entity_type, "Other")

    @staticmethod
    def _notable(model: dict[str, Any], node: str) -> bool:
        """A record worth seeing before opening its group: one with a picture or a name, a
        breach that leaked a password, or one that links to other records."""
        if not node.startswith("c:"):
            return False
        card = model["cards"][node]
        named = bool(card.get("subtitle")) and not str(card["subtitle"]).startswith("@")
        return bool(card.get("picture")) or ("password" in card["flags"]) or len(card["lookups"]) > 1 \
            or any(len(model["entities"][k]["cards"]) > 1 for k in card["exposed"]) \
            or (named and len(card["facts"]) >= 3)

    def _folded_children(self, model: dict[str, Any], owner: str, shown: set,
                         groups: dict[str, dict[str, Any]]) -> list[tuple[str, str]]:
        """The children of ``owner`` not in ``shown``: [(kind, id)], each one when there are
        few, else the most telling records and a group per kind of card or type of
        identifier (a group of one is shown as it is). Adds the groups to ``groups``."""
        kids = [n for n in model["children"].get(owner, []) if n not in shown]
        # a section's results are listed as they are (a page at a time when opened)
        if owner in model["sections"]:
            return [("node", n) for n in kids]
        # sections are groups already: always shown as they are, the others grouped beside them
        out: list[tuple[str, str]] = [("node", n) for n in kids if n in model["sections"]]
        kids = [n for n in kids if n not in model["sections"]]
        if len(kids) <= GRAPH_INLINE_MAX:
            return out + [("node", n) for n in kids]
        top = [n for n in kids if self._notable(model, n)][:GRAPH_TOP]
        keys = {n: self._group_key(model, n) for n in kids if n not in top}
        # many kinds of site: one group of accounts (its records ordered, the best first)
        categories = {key for key, _ in keys.values() if key.startswith("card:account:")}
        if len(categories) > GRAPH_GROUPS_MAX:
            keys = {n: ("card:account", "Accounts") if key.startswith("card:account:") else (key, label)
                    for n, (key, label) in keys.items()}
        found: dict[str, dict[str, Any]] = {}
        for node, (key, label) in keys.items():
            found.setdefault(key, {"id": f"g:{owner}:{key}", "owner": owner, "key": key, "label": label,
                                   "members": []})["members"].append(node)
        out += [("node", n) for n in top]
        for group in found.values():
            if len(group["members"]) > 1:
                groups[group["id"]] = group
                out.append(("group", group["id"]))
            else:
                out.append(("node", group["members"][0]))
        return out

    def _graph_view(self, model: dict[str, Any], budget: int) -> dict[str, Any]:
        """What the first view draws within ``budget`` nodes: what must be drawn, then, from the
        roots down, every node opened while its children fit."""
        view = model["views"].get(budget)
        if view is not None:
            return view
        must = model["must"]
        # then what links records or cases, with the way to it, while there is room for half the budget
        for node in model["extra"]:
            if len(must) >= budget // 2:
                break
            must = self._with_ancestors(must | {node}, model["parent"])
        drawn = set(must)
        groups: dict[str, dict[str, Any]] = {}
        closed: set = set()
        frontier = [n for n in model["children"].get(None, []) if n in drawn]
        while frontier:
            following = []
            for node in frontier:
                if not model["children"].get(node):
                    continue
                if node in model["sections"]:
                    # folded at first: the analyst opens the sections they want
                    closed.add(node)
                    following += [n for n in model["children"][node] if n in drawn]
                    continue
                entries = self._folded_children(model, node, must, {})
                if len(drawn) + len(entries) <= budget:
                    entries = self._folded_children(model, node, must, groups)
                    drawn.update(child for kind, child in entries if kind == "node")
                    drawn.update(child for kind, child in entries if kind == "group")
                else:
                    closed.add(node)
                following += [n for n in model["children"][node] if n in drawn]
            frontier = following
        view = model["views"][budget] = {"drawn": drawn, "groups": groups, "closed": closed, "pinned": must}
        return view

    # -- what is sent to the browser --

    @staticmethod
    def _identifier_node(model: dict[str, Any], key: str) -> dict[str, Any]:
        info = model["entities"][key]
        entity = info["entity"]
        node = f"e:{key}"
        return {
            "id": node, "kind": "identifier", "key": key, "type": entity.get("type"),
            "value": entity.get("value"), "display": entity.get("display") or entity.get("value"),
            "status": entity.get("status"), "note": entity.get("note"),
            "first_seen": entity.get("first_seen"), "last_seen": entity.get("last_seen"),
            "found_by": len(info["found_in"]), "searched_by": len(info["searched_in"]), "cards": len(info["cards"]),
            "shared": info["shared"], "root": model["parent"].get(node) is None,
            # a username or email shows the picture of its first account
            "image": next((model["cards"][c].get("picture") for c in model["children"].get(node, [])
                           if c.startswith("c:") and model["cards"][c].get("picture")
                           and model["cards"][c]["kind"] == "account"), None)
            if entity.get("type") in ("username", "email", "telegram_username") else None,
            "home": model["parent"].get(node), "rank": model["rank"].get(node, 0),
            "children": len(model["children"].get(node, [])),
            # in two records, or in other cases too
            "linked": len(info["cards"]) > 1 or bool(info["shared"]),
        }

    @staticmethod
    def _card_node(model: dict[str, Any], card_id: str, full: bool = False) -> dict[str, Any]:
        card = model["cards"][card_id]
        lookups = model["lookups"]
        node = {
            "id": card_id, "kind": "card", "card": card["kind"], "title": card["title"],
            "subtitle": card.get("subtitle"), "site": card.get("site"), "url": card.get("url"),
            "picture": card.get("picture"), "category": card.get("category"), "date": card.get("date"),
            "flags": card["flags"], "facts": card["facts"] if full else card["facts"][:4],
            "relation": card.get("relation") or RELATIONS.get(card["kind"], "found"),
            "services": list(dict.fromkeys(lookups[lid]["service"] for lid in card["lookups"])),
            "result_ids": list(dict.fromkeys(r["result_id"] for r in card["runs"])),
            "found_by": len(card["lookups"]), "exposed": len(card["exposed"]), "shares": sum(
                1 for (kind, ident) in card["traits"] if f"f:{kind}:{ident}" in model["facts"]),
            "own": [model["entities"][k]["entity"].get("type") + ":" + str(model["entities"][k]["entity"].get("value"))
                    for k in card["own"]][:5],
            "first_seen": card["first"], "home": model["parent"].get(card_id), "rank": model["rank"].get(card_id, 0),
            "root": model["parent"].get(card_id) is None, "children": len(model["children"].get(card_id, [])),
        }
        # found by two lookups, sharing a fact with another record, or holding what another holds
        node["linked"] = node["found_by"] > 1 or node["shares"] > 0 or any(
            len(model["entities"][k]["cards"]) > 1 for k in card["exposed"])
        if full:
            node["runs"] = sorted(card["runs"], key=lambda r: r["timestamp"] or "", reverse=True)
            node["traits"] = [{"kind": kind, "shown": shown, "id": f"f:{kind}:{ident}",
                               "shared": f"f:{kind}:{ident}" in model["facts"]}
                              for (kind, ident), shown in card["traits"].items()]
        return node

    @staticmethod
    def _fact_node(model: dict[str, Any], fact_id: str) -> dict[str, Any]:
        fact = model["facts"][fact_id]
        return {"id": fact_id, "kind": "fact", "fact": fact["kind"], "label": fact["shown"],
                "name": TRAIT_NAMES.get(fact["kind"], fact["kind"]), "count": len(fact["cards"]),
                "home": model["parent"].get(fact_id), "rank": model["rank"].get(fact_id, 0)}

    def _group_node(self, model: dict[str, Any], group: dict[str, Any]) -> dict[str, Any]:
        node = {"id": group["id"], "kind": "group", "owner": group["owner"], "key": group["key"],
                "label": group["label"], "count": len(group["members"]), "rank": 10_000 + len(group["key"])}
        if group["key"].startswith("card:"):
            node["card"] = group["key"].split(":")[1]
            node["pictures"] = [p for p in (model["cards"][m].get("picture") for m in group["members"]) if p][:3]
        elif group["key"].startswith("lookup:"):
            lookup = model["lookups"][group["key"][7:]]
            node.update(service=lookup["service"], method=lookup["method"])
            node["type"] = model["entities"][group["members"][0][2:]]["entity"].get("type")
        elif group["key"].startswith("type:"):
            node["type"] = group["key"][5:]
        return node

    @staticmethod
    def _section_node(model: dict[str, Any], section_id: str) -> dict[str, Any]:
        """A section of a lookup's page (DNS recon's "Hosting", an NS same-owner group): a group
        that is a node of the tree."""
        section = model["sections"][section_id]
        row = section["row"]
        members = model["children"].get(section_id, [])
        node = {"id": section_id, "kind": "group", "section": True, "owner": section["owner"],
                "key": f"section:{section['lookup']}:{row['key']}", "label": row.get("label") or "Results",
                "count": len(members), "service": row.get("service"), "method": row.get("method"),
                "home": section["owner"], "rank": model["rank"].get(section_id, 0)}
        node.update({k: row[k] for k in ("reasons", "confidence") if row.get(k)})
        kinds = {model["cards"][m]["kind"] for m in members if m.startswith("c:")}
        if len(kinds) == 1 and all(m.startswith("c:") for m in members):
            node["card"] = kinds.pop()
        elif members and members[0].startswith("e:"):
            node["type"] = model["entities"][members[0][2:]]["entity"].get("type")
        return node

    def _node(self, model: dict[str, Any], node: str, full: bool = False) -> dict[str, Any]:
        if node in model["sections"]:
            return self._section_node(model, node)
        if node.startswith("c:"):
            return self._card_node(model, node, full)
        if node.startswith("f:"):
            return self._fact_node(model, node)
        if node in model["lookups"]:
            # a lookup that looked up no identifier: what it found starts from it
            return {**self._lookup_node(model, node), "root": True, "home": None, "rank": model["rank"].get(node, 0),
                    "children": len(model["children"].get(node, []))}
        return self._identifier_node(model, node[2:])

    def _tree_edge(self, model: dict[str, Any], source: str, target: str) -> dict[str, Any]:
        """The link from a node to one of its children, saying what it is."""
        if target in model["sections"]:
            return _edge(source, target, "found")      # the section's name is on it
        if source in model["sections"] and not target.startswith("c:"):
            return _edge(source, target, "member", model["lookups"].get(model["sections"][source]["lookup"]))
        if target.startswith("c:"):
            card = model["cards"][target]
            edge = _edge(source, target, "card")
            edge["label"] = card.get("relation") or RELATIONS.get(card["kind"], "found")
            edge["card"] = card["kind"]
        elif target.startswith("f:"):
            edge = _edge(source, target, "fact")
            edge["label"] = TRAIT_NAMES.get(model["facts"][target]["kind"], "")
        elif source.startswith("c:"):
            edge = _edge(source, target, "exposes")
            card = model["cards"][source]
            if card["kind"] == "account" and model["entities"][target[2:]]["entity"].get("type") == "username":
                edge["label"] = "named in profile"
        else:
            lookup = model["lookups"].get(model["via"].get(target, ""))
            edge = _edge(source, target, "found", lookup)
        return edge

    def _links(self, model: dict[str, Any], nodes: set, among: Optional[set] = None) -> list[dict[str, Any]]:
        """The links of ``nodes`` with each other (or with ``among``): each node's to its parent,
        and the others (a card that another identifier searched too, an identifier two records
        hold, a shared fact)."""
        parent = model["parent"]
        among = nodes if among is None else among | nodes
        edges: dict[str, dict[str, Any]] = {}

        def add(edge):
            edges.setdefault(edge["id"], edge)

        for node in nodes:
            owner = parent.get(node)
            if owner is not None and owner in among:
                add(self._tree_edge(model, owner, node))
            if node.startswith("e:"):
                key = node[2:]
                info = model["entities"][key]
                for card_id in info["cards"]:
                    if card_id != owner and card_id in among and key in model["cards"][card_id]["exposed"]:
                        add({**self._tree_edge(model, card_id, node), "cross": True})
                # found by another lookup too, which no card of holds it: from what that one searched
                # (not from what a section it is in hangs under: the section is the way to it)
                held = model["sections"].get(owner, {}).get("owner")
                for lookup_id in info["found_in"]:
                    source = model["origins"].get(lookup_id)
                    if source and source not in (owner, node, held) and source in among \
                            and not any(lookup_id in model["cards"][c]["lookups"] for c in info["cards"]):
                        add({**_edge(source, node, "found", model["lookups"][lookup_id]), "cross": True})
            elif node.startswith("f:"):
                for card_id in model["facts"][node]["cards"]:
                    if card_id != owner and card_id in among:
                        add({**self._tree_edge(model, card_id, node), "cross": True})
            if node.startswith("c:"):
                card = model["cards"][node]
                # (a card found for a username a profile named hangs under that one only)
                for key in card["subject"] if not card["under"] else []:
                    other = model["alias"].get(key) or f"e:{key}"
                    if other != owner and other in among and other != node:
                        add({**self._tree_edge(model, other, node), "cross": True})
                for key in card["exposed"]:
                    target = model["alias"].get(key) or f"e:{key}"
                    if target != node and target in among and parent.get(target) != node:
                        add({**self._tree_edge(model, node, target), "cross": True})
                for kind, ident in card["traits"]:
                    fact = f"f:{kind}:{ident}"
                    if fact in among and parent.get(fact) != node:
                        add({**self._tree_edge(model, node, fact), "cross": True})
        return list(edges.values())

    def get_graph(self, investigation_id: UUID, noise: bool = False,
                  budget: int = GRAPH_NODE_BUDGET) -> dict[str, Any]:
        """The first view: what was looked up, the cards (accounts, breaches...) under it and
        what each exposed, the rest folded into groups. Past ``budget`` nodes the deepest
        branches stay closed."""
        model = self._graph_model(investigation_id, noise)
        view = self._graph_view(model, budget)
        drawn, groups = view["drawn"], view["groups"]
        nodes: dict[str, dict[str, Any]] = {}
        for node in drawn:
            if node.startswith("g:") and node not in model["sections"]:
                nodes[node] = self._group_node(model, groups[node])
            else:
                data = self._node(model, node)
                kids = model["children"].get(node, [])
                shown = sum(1 for k in kids if k in drawn) + sum(
                    len(g["members"]) for g in groups.values() if g["owner"] == node)
                data["hidden"] = len(kids) - shown
                data["open"] = not data["hidden"] and bool(kids)
                nodes[node] = data
        edges = self._links(model, {n for n in drawn if not n.startswith("g:") or n in model["sections"]})
        edges += [{**_edge(g["owner"], gid, "found"), "label": g["label"]} for gid, g in groups.items()
                  if g["owner"] in drawn]
        return {"nodes": list(nodes.values()), "edges": edges,
                "state": self._moved_links(model, self.get_graph_state(investigation_id)),
                "stats": self._graph_stats(model, nodes)}

    @staticmethod
    def _moved_links(model: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        """Links the analyst drew to a lookup, which is no longer drawn, go to what it looked
        up (saved so when the view is saved next)."""
        for edge in state.get("manual_edges") or []:
            for end in ("source", "target"):
                node = edge.get(end)
                if isinstance(node, str) and node.startswith("r:") and node not in model["parent"]:
                    lookup = model["runs"].get(node, node)
                    edge[end] = model["origins"].get(lookup, node)
        return state

    def _graph_stats(self, model: dict[str, Any], nodes: dict[str, dict[str, Any]]) -> dict[str, Any]:
        per_type: dict[str, int] = {}
        for info in model["entities"].values():
            entity_type = info["entity"].get("type")
            per_type[entity_type] = per_type.get(entity_type, 0) + 1
        per_kind: dict[str, int] = {}
        for card in model["cards"].values():
            per_kind[card["kind"]] = per_kind.get(card["kind"], 0) + 1
        return {
            "nodes": len(nodes), "budget": GRAPH_NODE_BUDGET,
            "identifiers": len(model["entities"]), "cards": len(model["cards"]), "lookups": len(model["lookups"]),
            "shown": sum(1 for n in nodes.values() if n["kind"] == "identifier"),
            "cards_shown": sum(1 for n in nodes.values() if n["kind"] == "card"),
            "groups": sum(1 for n in nodes.values() if n["kind"] == "group"),
            "noise": model["left_out"]["noise"], "false_positive": model["left_out"]["false_positive"],
            "types": per_type, "kinds": per_kind,
        }

    def _lookup_node(self, model: dict[str, Any], lookup_id: str) -> dict[str, Any]:
        """A lookup, for the side panel (lookups are not drawn: cards say who found them)."""
        lookup = model["lookups"][lookup_id]
        return {
            "id": lookup_id, "kind": "lookup", "result_id": lookup["result_id"], "child_id": lookup["child_id"],
            "service": lookup["service"], "method": lookup["method"], "target": lookup["target"],
            "summary": lookup["summary"], "timestamp": lookup["timestamp"], "triage": lookup["triage"],
            "partial": lookup["partial"], "found": len(lookup["found"]),
            # newest first; result_id, child_id and timestamp above are the latest run's
            "runs": lookup["runs"], "rerun": len(lookup["runs"]) > 1,
        }

    def _short(self, model: dict[str, Any], node: str) -> dict[str, Any]:
        """A node as a line in a list (the side panel, the summary)."""
        if node.startswith("c:"):
            card = model["cards"][node]
            return {"id": node, "kind": "card", "card": card["kind"], "title": card["title"],
                    "subtitle": card.get("subtitle"), "date": card.get("date"), "flags": card["flags"],
                    "picture": card.get("picture"), "site": card.get("site")}
        if node in model["lookups"]:
            return self._lookup_node(model, node)
        if node.startswith("f:"):
            return self._fact_node(model, node)
        entity = model["entities"][node[2:]]["entity"]
        return {"id": node, "kind": "identifier", "type": entity.get("type"), "value": entity.get("value"),
                "display": entity.get("display") or entity.get("value"), "status": entity.get("status")}

    def graph_node_details(self, investigation_id: UUID, node_id: str,
                           noise: bool = False) -> Optional[dict[str, Any]]:
        """One node for the side panel: an identifier with its cards and the lookups that found
        or looked it up; a card with every fact, what it exposes and its runs; a shared fact
        with its cards; a group with its owner."""
        model = self._graph_model(investigation_id, noise)
        lookups = model["lookups"]
        node_id = model["runs"].get(node_id, node_id)
        if node_id.startswith("e:") and node_id[2:] in model["alias"]:
            node_id = model["alias"][node_id[2:]]
        if node_id.startswith("e:") and node_id[2:] in model["entities"]:
            key = node_id[2:]
            info = model["entities"][key]
            return {"node": self._identifier_node(model, key),
                    "cards": [self._short(model, c) for c in info["cards"]],
                    "found_in": [self._lookup_node(model, lid) for lid in info["found_in"]],
                    "searched_in": [self._lookup_node(model, lid) for lid in info["searched_in"]],
                    "elsewhere": self.investigations_with([key], exclude=investigation_id).get(key, [])}
        if node_id in model["cards"]:
            card = model["cards"][node_id]
            keys = card["own"] + card["exposed"]
            elsewhere = self.investigations_with(card["own"], exclude=investigation_id) if card["own"] else {}
            return {"node": self._card_node(model, node_id, full=True),
                    "subject": [self._short(model, model["alias"].get(k) or f"e:{k}") for k in card["subject"]],
                    "exposed": [self._short(model, f"e:{k}") for k in card["exposed"]],
                    "identifiers": [{"type": model["entities"][k]["entity"].get("type"),
                                     "value": model["entities"][k]["entity"].get("value")} for k in keys],
                    "lookups": [self._lookup_node(model, lid) for lid in card["lookups"]],
                    "elsewhere": next(iter(elsewhere.values()), [])}
        if node_id in model["sections"]:
            members = model["children"].get(node_id, [])
            return {"node": self._section_node(model, node_id),
                    "members": [self._short(model, m) for m in members[:12]],
                    "owner": self._short(model, model["sections"][node_id]["owner"]),
                    "lookup": self._lookup_node(model, model["sections"][node_id]["lookup"])}
        if node_id in model["facts"]:
            fact = model["facts"][node_id]
            return {"node": self._fact_node(model, node_id), "cards": [self._short(model, c) for c in fact["cards"]]}
        if node_id in lookups:
            lookup = lookups[node_id]
            return {"node": self._lookup_node(model, node_id),
                    "parent": self._lookup_node(model, lookup["parent"]) if lookup["parent"] else None}
        if node_id.startswith("g:"):
            group = self._graph_view(model, GRAPH_NODE_BUDGET)["groups"].get(node_id) or self._group_of(model, node_id)
            if group:
                return {"node": self._group_node(model, group),
                        "members": [self._short(model, m) for m in group["members"][:12]],
                        "owner": self._short(model, group["owner"]) if group["owner"] in model["parent"] else None}
        return None

    def _group_of(self, model: dict[str, Any], group_id: str) -> Optional[dict[str, Any]]:
        """A group opened after the first view (its owner was closed in it)."""
        owner = next((o for o in model["children"] if o and group_id.startswith(f"g:{o}:")), None)
        if owner is None:
            return None
        groups: dict[str, dict[str, Any]] = {}
        self._folded_children(model, owner, self._graph_view(model, GRAPH_NODE_BUDGET)["pinned"], groups)
        return groups.get(group_id)

    # -- finding a node, wherever it is folded --

    def _reveal_steps(self, model: dict[str, Any], node: str) -> list[dict[str, Any]]:
        """What to open, from the top, to reach ``node``: [{"open": id} | {"group": id, "offset": n}]."""
        chain = [node]
        while model["parent"].get(chain[-1]) is not None and len(chain) < 200:
            chain.append(model["parent"][chain[-1]])
        chain.reverse()
        pinned = self._graph_view(model, GRAPH_NODE_BUDGET)["pinned"]
        steps = []
        for owner, child in pairwise(chain):
            steps.append({"open": owner})
            if child in pinned:
                continue
            groups: dict[str, dict[str, Any]] = {}
            for kind, entry in self._folded_children(model, owner, pinned, groups):
                if kind == "group" and child in groups[entry]["members"]:
                    steps.append({"group": entry, "offset": groups[entry]["members"].index(child)})
        return steps

    def reveal_graph_node(self, investigation_id: UUID, node_id: str, noise: bool = False) -> Optional[dict[str, Any]]:
        model = self._graph_model(investigation_id, noise)
        if node_id.startswith("e:") and node_id[2:] in model["alias"]:
            node_id = model["alias"][node_id[2:]]
        if node_id not in model["parent"]:
            return None
        return {"id": node_id, "steps": self._reveal_steps(model, node_id)}

    def search_graph(self, investigation_id: UUID, query: str, noise: bool = False, limit: int = 30,
                     budget: int = GRAPH_NODE_BUDGET) -> dict[str, Any]:
        """Identifiers and cards with ``query`` in them (a value, a card's title or facts),
        wherever they are folded, with what to open to reach each (``steps``)."""
        model = self._graph_model(investigation_id, noise)
        drawn = self._graph_view(model, budget)["drawn"]
        needle = query.strip().lower()
        if len(needle) < 2:
            return {"matches": [], "total": 0}
        found = []
        for key, info in model["entities"].items():
            if key not in model["alias"] and needle in \
                    f"{info['entity'].get('value') or ''} {info['entity'].get('display') or ''}".lower():
                found.append((0, self._sibling_order(model, f"e:{key}"), f"e:{key}"))
        for card_id, card in model["cards"].items():
            text = " ".join([card["title"], str(card.get("subtitle") or ""), str(card.get("url") or "")]
                            + [str(v) for _, v in card["facts"]]).lower()
            if needle in text:
                found.append((1, self._sibling_order(model, card_id), card_id))
        found.sort()
        matches = []
        for _, _, node in found[:limit]:
            match = self._short(model, node)
            match["steps"] = [] if node in drawn else self._reveal_steps(model, node)
            matches.append(match)
        return {"matches": matches, "total": len(found)}

    # -- what we know: the case at a glance --

    def graph_summary(self, investigation_id: UUID, noise: bool = False) -> dict[str, Any]:
        """Everything the cards and identifiers say, counted: names, photos, places, contacts,
        accounts per category, breaches (and how many leaked a password), the dates."""
        model = self._graph_model(investigation_id, noise)
        entities, cards = model["entities"], model["cards"]

        def ranked(entity_type: str, limit: int = 12) -> list[dict[str, Any]]:
            rows = []
            for key, info in entities.items():
                entity = info["entity"]
                if entity.get("type") == entity_type:
                    rows.append({"id": model["alias"].get(key) or f"e:{key}", "type": entity_type, "value": entity.get("value"),
                                 "display": entity.get("display") or entity.get("value"),
                                 "sources": len(info["cards"]) or len(info["found_in"]),
                                 "searched": bool(info["searched_in"]), "status": entity.get("status")})
            rows.sort(key=lambda r: (TRIAGE_RANK.get(r["status"], 2), not r["searched"], -r["sources"],
                                     str(r["value"])))
            return rows[:limit]

        places: dict[str, dict[str, Any]] = {}
        for card_id, card in cards.items():
            for label, value in card["facts"]:
                # a place has a name ("RU" or "()" says too little)
                if PLACE_LABEL.search(label) and len(re.findall(r"\w", value)) >= 3 and not re.fullmatch(r"[\d\s.,:-]+", value):
                    place = places.setdefault(value.casefold(), {"value": value, "cards": []})
                    if card_id not in place["cards"]:
                        place["cards"].append(card_id)
        photos = [{"id": cid, "url": card["picture"], "title": card["title"], "subtitle": card.get("subtitle")}
                  for cid, card in sorted(cards.items(), key=lambda c: self._sibling_order(model, c[0]))
                  if card.get("picture") and card["kind"] in ("account", "person")]
        accounts: dict[str, int] = {}
        breaches = []
        for card_id, card in cards.items():
            if card["kind"] == "account":
                category = card.get("category") or "other"
                accounts[category] = accounts.get(category, 0) + 1
            elif card["kind"] == "breach":
                breaches.append({**self._short(model, card_id)})
        breaches.sort(key=lambda b: (b["date"] or "", b["title"]), reverse=True)
        dates = sorted(d for d in (card.get("date") for card in cards.values()) if d)
        kinds: dict[str, int] = {}
        for card in cards.values():
            kinds[card["kind"]] = kinds.get(card["kind"], 0) + 1
        return {
            "names": ranked("name"), "emails": ranked("email"), "phones": ranked("phone"),
            "usernames": ranked("username") + ranked("telegram_username", 6), "domains": ranked("domain", 8),
            "photos": photos[:12],
            "places": sorted(({"value": p["value"], "count": len(p["cards"]), "id": p["cards"][0]}
                              for p in places.values()), key=lambda p: (-p["count"], p["value"]))[:10],
            "accounts": dict(sorted(accounts.items(), key=lambda a: -a[1])),
            "breaches": {"count": len(breaches), "passwords": sum(1 for b in breaches if "password" in b["flags"]),
                         "latest": breaches[:8]},
            "shared_facts": [{**self._fact_node(model, fid), "cards": len(f["cards"])}
                             for fid, f in sorted(model["facts"].items(), key=lambda f: -len(f[1]["cards"]))][:8],
            "dates": {"first": dates[0] if dates else None, "last": dates[-1] if dates else None},
            "counts": {"identifiers": len(entities), "cards": len(cards), "lookups": len(model["lookups"]),
                       "kinds": kinds},
        }

    # -- exporting and the picture of the graph --

    def export_graph(self, investigation_id: UUID, noise: bool = False) -> dict[str, Any]:
        """The whole graph, nothing folded: every identifier, card and shared fact, the links
        between them, and what the analyst added."""
        model = self._graph_model(investigation_id, noise)
        every = set(model["parent"])
        nodes = [self._node(model, node, full=True) for node in every]
        edges = self._links(model, every)
        state = self.get_graph_state(investigation_id)
        ids = {n["id"] for n in nodes}
        for manual in state.get("manual_nodes") or []:
            nodes.append({**manual, "kind": "manual"})
            ids.add(manual["id"])
        edges += [{**e, "kind": "manual"} for e in state.get("manual_edges") or []
                  if e.get("source") in ids and e.get("target") in ids]
        return {"nodes": nodes, "edges": edges}

    def expand_graph_node(self, investigation_id: UUID, node_id: str, offset: int = 0, limit: int = 40,
                          noise: bool = False, budget: int = GRAPH_NODE_BUDGET) -> Optional[dict[str, Any]]:
        """The children of one identifier, card or group, a page at a time, most relevant
        first. None when the node isn't in the graph."""
        model = self._graph_model(investigation_id, noise)
        view = self._graph_view(model, budget)
        if node_id.startswith("more:"):
            node_id, _, at = node_id[5:].rpartition(":")
            offset = int(at) if at.isdigit() else offset
        node_id = model["runs"].get(node_id, node_id)
        if node_id.startswith("e:") and node_id[2:] in model["alias"]:
            node_id = model["alias"][node_id[2:]]

        pinned = view["pinned"]
        groups: dict[str, dict[str, Any]] = {}
        group = None
        if node_id in model["parent"]:
            kids = model["children"].get(node_id, [])
            entries = [("node", k) for k in kids if k in pinned] \
                + self._folded_children(model, node_id, pinned, groups)
        elif node_id.startswith("g:"):
            group = view["groups"].get(node_id) or self._group_of(model, node_id)
            if group is None:
                return None
            entries = [("node", m) for m in group["members"]]
        else:
            return None

        page = entries[offset:offset + limit]
        nodes: list[dict[str, Any]] = []
        shown = set()
        for kind, child in page:
            if kind == "group":
                nodes.append(self._group_node(model, groups[child]))
                continue
            data = self._node(model, child)
            kids = model["children"].get(child, [])
            data["hidden"] = sum(1 for k in kids if k not in pinned)
            data["open"] = not data["hidden"] and bool(kids)
            nodes.append(data)
            shown.add(child)
        edges = self._links(model, shown, among=set(model["parent"]))
        if group:
            # in a group, its members hang under it
            edges = [e for e in edges if not (e["source"] == group["owner"] and e["target"] in shown)]
            edges += [{**self._tree_edge(model, group["owner"], m), "id": f"{node_id}>{m}", "source": node_id,
                       "kind": "member"} for m in shown]
        edges += [{**_edge(node_id, child, "found"), "label": groups[child]["label"]}
                  for kind, child in page if kind == "group"]
        rest = len(entries) - offset - len(page)
        if rest > 0:
            more_id = f"more:{node_id}:{offset + len(page)}"
            nodes.append({"id": more_id, "kind": "more", "parent": node_id, "offset": offset + len(page),
                          "count": rest, "rank": 1_000_000})
            edges.append(_edge(node_id, more_id, "more"))
        return {"node": node_id, "offset": offset, "total": len(entries), "nodes": nodes, "edges": edges}

    def export_graph_gexf(self, investigation_id: UUID, noise: bool = False) -> str:
        """The whole graph as GEXF 1.3 (opens in Gephi)."""
        graph = self.export_graph(investigation_id, noise)
        name = (self.get_investigation_info(investigation_id) or {}).get("name") or "Investigation"
        def clean(value) -> str:
            # XML can't hold most control characters, even escaped
            return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]", "", str(value))

        root = ElementTree.Element("gexf", {"xmlns": "http://gexf.net/1.3", "version": "1.3"})
        meta = ElementTree.SubElement(root, "meta", {"lastmodifieddate": datetime.now().strftime("%Y-%m-%d")})
        ElementTree.SubElement(meta, "creator").text = "OSINT Toolkit"
        ElementTree.SubElement(meta, "description").text = clean(name)
        body = ElementTree.SubElement(root, "graph", {"defaultedgetype": "directed", "mode": "static"})
        fields = ("kind", "type", "card", "subtitle", "status", "url", "date", "first_seen")
        declared = ElementTree.SubElement(body, "attributes", {"class": "node"})
        for field in fields:
            ElementTree.SubElement(declared, "attribute", {"id": field, "title": field, "type": "string"})
        nodes = ElementTree.SubElement(body, "nodes")
        for node in graph["nodes"]:
            label = node.get("display") or node.get("value") or node.get("title") or node.get("label") or node.get("id")
            element = ElementTree.SubElement(nodes, "node", {"id": clean(node["id"]), "label": clean(label or node["id"])})
            values = ElementTree.SubElement(element, "attvalues")
            for field in fields:
                if node.get(field) not in (None, "") and not isinstance(node.get(field), (list, dict)):
                    ElementTree.SubElement(values, "attvalue", {"for": field, "value": clean(node[field])})
        edges = ElementTree.SubElement(body, "edges")
        for index, edge in enumerate(graph["edges"]):
            ElementTree.SubElement(edges, "edge", {"id": str(index), "source": clean(edge["source"]),
                                                   "target": clean(edge["target"]),
                                                   "label": clean(edge.get("label") or edge.get("kind") or "")})
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + ElementTree.tostring(root, encoding="unicode")

    def _graph_image_file(self, investigation_id):
        return self._inv_dir(investigation_id) / "graph.webp"

    def save_graph_image(self, investigation_id: UUID, data: bytes) -> None:
        """The graph as the analyst left it, for the case report. Decoded and stored again,
        so only pixels are kept."""
        image = process_note_image(data)
        path = self._graph_image_file(investigation_id)
        tmp = path.with_suffix(".webp.tmp")
        tmp.write_bytes(image)
        tmp.replace(path)

    def graph_image(self, investigation_id: UUID) -> Optional[bytes]:
        try:
            return self._graph_image_file(investigation_id).read_bytes()
        except FileNotFoundError:
            return None
