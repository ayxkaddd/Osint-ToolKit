"""The investigation graph: identifiers and the lookups that connect them.

Built on the server so the browser only draws what is open. Node ids are stable
across rebuilds (saved positions and hidden marks refer to them):

    e:<entity key>                  an identifier, one per case however many lookups found it
    r:<result_id>[:<child_id>]      one lookup (a result, or a follow-up attached to one); runs of the
                                    same module on the same identifiers are one lookup, under the first run
    g:<lookup id>:<group key>       a lookup's findings of one type (or site category), folded
    more:<group id>:<offset>        the rest of an opened group, past the first page

Edges run identifier -> lookup (searched), lookup -> identifier or group (found),
group -> identifier (member) and lookup -> follow-up lookup (followup).
"""
import math
import re
import threading
from datetime import datetime
from typing import Annotated, Any, Literal, Optional
from urllib.parse import urljoin, urlparse
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from services.entities import ENTITY_TYPES, NOISE_DOMAINS, NOISE_EMAIL_LOCALS, Entity, is_noise
from .constants import GRAPH_INLINE_MAX, GRAPH_NODE_BUDGET, GRAPH_VERSION, MANUAL_SERVICE, NOTE_IMAGE_NAME
from .storage import _GRAPH_CACHE, _SHARED_CACHE, _STORE_LOCK, _read_json, _write_json_atomic

TRIAGE_RANK = {"confirmed": 0, "important": 1, None: 2, "false_positive": 3}

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
    types: list[Name] = Field(default_factory=list, max_length=40)
    modules: list[Name] = Field(default_factory=list, max_length=200)
    triage: list[Name] = Field(default_factory=list, max_length=5)
    date_from: Optional[Name] = None
    date_to: Optional[Name] = None
    shared_only: bool = False
    noise: bool = False


class GraphState(_Strict):
    """graph.json. Node ids are the graph's (e:..., r:..., g:..., m:...); ids that are no
    longer in the graph are kept, so a deleted and re-run lookup comes back as it was."""
    positions: dict[NodeId, tuple[float, float]] = Field(default_factory=dict)
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
        shared_index = self._shared_index()
        try:
            stat = self._index_file(investigation_id).stat()
            index_version = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
        except FileNotFoundError:
            index_version = None
        cache_key = (str(UUID(str(investigation_id))), noise)
        version = (GRAPH_VERSION, snapshot["version"], index_version, _SHARED_CACHE["versions"])
        with _GRAPH_LOCK:
            cached = _GRAPH_CACHE.get(cache_key)
            if cached and cached[0] == version:
                _GRAPH_CACHE.move_to_end(cache_key)
                return cached[1]
        model = self._build_graph_model(investigation_id, snapshot["raw"], shared_index, noise)
        with _GRAPH_LOCK:
            _GRAPH_CACHE[cache_key] = (version, model)
            while len(_GRAPH_CACHE) > GRAPH_CACHE_MAX:
                _GRAPH_CACHE.popitem(last=False)
        return model

    def _build_graph_model(self, investigation_id: UUID, raw: dict[str, Any],
                           shared_index: dict[str, list[dict[str, Any]]], noise: bool) -> dict[str, Any]:
        here = str(investigation_id)
        runs: dict[str, dict[str, Any]] = {}     # each saved lookup: a result, or a follow-up attached to one
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
        # Running a module again on the same identifiers is one lookup with several runs,
        # under the id of its first run; the latest run stands for it (pivots attach to it)
        merged: dict[str, str] = {}              # run id -> lookup id
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

        entities: dict[str, dict[str, Any]] = {}
        paths: dict[tuple[str, str], tuple[str, str]] = {}   # (lookup id, entity key) -> (run id, where found)
        left_out = {"noise": 0, "false_positive": 0}
        for key, entity in raw.items():
            searched_in, found_in = [], []
            for src in entity.get("sources") or []:
                run_id = _lookup_id(src.get("result_id"), src.get("child_id"))
                if run_id not in merged:
                    continue
                if src.get("role") == "searched":
                    searched_in.append(merged[run_id])
                else:
                    found_in.append(merged[run_id])
                    paths[(merged[run_id], key)] = (run_id, src.get("path") or "")
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
            shared = sum(1 for place in shared_index.get(key, []) if place["investigation_id"] != here)
            found_by = len(found_in)
            entities[key] = {"entity": entity, "searched_in": searched_in, "found_in": found_in, "shared": shared,
                             "found_by": found_by,
                             "order": (TRIAGE_RANK.get(entity.get("status"), 2), -found_by,
                                       entity.get("type") or "", entity.get("value") or "")}
            for lookup_id in searched_in:
                lookups[lookup_id]["searched"].append(key)
            for lookup_id in found_in:
                lookups[lookup_id]["found"].append(key)

        # Always shown, wherever they were found: what was typed or looked up (the chain
        # of pivots runs through them) and what the analyst marked confirmed or important
        must = {key for key, info in entities.items()
                if info["entity"].get("status") in ("confirmed", "important") or info["searched_in"]
                or not info["found_in"]}
        # Shown outside their groups while the node budget allows, the most connected first
        extra = sorted((key for key, info in entities.items()
                        if key not in must and (info["found_by"] > 1 or info["shared"])),
                       key=lambda k: (-entities[k]["found_by"], -entities[k]["shared"], entities[k]["order"]))

        sites = self._found_sites(investigation_id, [runs[run_id] for run_id, _ in paths.values()])
        images: dict[str, str] = {}
        group_of: dict[tuple[str, str], tuple[str, str]] = {}   # (lookup id, entity key) -> (group key, label)
        for lookup in lookups.values():
            lookup["found"].sort(key=lambda k: entities[k]["order"])
            for key in lookup["found"]:
                entity_type = entities[key]["entity"].get("type")
                run_id, path = paths[(lookup["id"], key)]
                category, picture = sites.get(run_id, {}).get(path, (None, None))
                if picture:
                    images.setdefault(key, picture)
                group_of[(lookup["id"], key)] = (f"category:{category}", f"Accounts · {category}") \
                    if category is not None else (f"type:{entity_type}", ENTITY_TYPES.get(entity_type, "Other"))

        # Depth from the roots (what was typed, and lookups that searched nothing)
        children: dict[str, list[str]] = {}
        for lookup in lookups.values():
            if lookup["parent"] and not lookup["searched"]:
                children.setdefault(lookup["parent"], []).append(lookup["id"])
        roots = [f"e:{key}" for key, info in entities.items() if not info["found_in"]]
        roots += [lid for lid, lookup in lookups.items() if not lookup["searched"] and not lookup["parent"]]
        depth: dict[str, int] = {}

        def walk(seeds: list[str], start: int):
            frontier = [s for s in seeds if s not in depth]
            for seed in frontier:
                depth[seed] = start
            while frontier:
                following = []
                for node in frontier:
                    if node.startswith("e:"):
                        nexts = entities[node[2:]]["searched_in"]
                    else:
                        nexts = [f"e:{k}" for k in lookups[node]["found"]] + children.get(node, [])
                    for nxt in nexts:
                        if nxt not in depth:
                            depth[nxt] = depth[node] + 1
                            following.append(nxt)
                frontier = following

        walk(roots, 0)
        # Loops with no way in (A found B, B found A): start from the earliest lookup
        for lookup in sorted(lookups.values(), key=lambda lk: lk["timestamp"] or ""):
            if lookup["id"] not in depth:
                walk([f"e:{k}" for k in lookup["searched"]] or [lookup["id"]], 0)

        return {"lookups": lookups, "entities": entities, "must": must, "extra": extra, "group_of": group_of,
                "depth": depth, "children": children, "left_out": left_out, "runs": merged, "images": images,
                "views": {}}

    def _found_sites(self, investigation_id: UUID,
                     runs: list[dict[str, Any]]) -> dict[str, dict[str, tuple[str, Optional[str]]]]:
        """{run id: {path of a found site's url: (its category, the profile's picture)}}
        for the username searches among ``runs``."""
        found: dict[str, dict[str, tuple[str, Optional[str]]]] = {}
        by_result: dict[str, dict[str, dict[str, Any]]] = {}
        for run in runs:
            if run["service"] == "username":
                by_result.setdefault(run["result_id"], {})[run["id"]] = run
        for result_id, wanted in by_result.items():
            record = self.get_result(investigation_id, result_id) or {}
            parts = {None: record, **{c.get("child_id"): c for c in record.get("children") or []}}
            for run in wanted.values():
                result = (parts.get(run["child_id"]) or {}).get("result")
                sites = result.get("results") if isinstance(result, dict) else None
                if not isinstance(sites, list):
                    continue
                found[run["id"]] = {
                    f"results[{i}].url": (str(site.get("category") or "other").strip()[:60] or "other",
                                          profile_picture(site))
                    for i, site in enumerate(sites) if isinstance(site, dict)}
        return found

    # -- what is sent to the browser --

    @staticmethod
    def _identifier_node(model: dict[str, Any], key: str) -> dict[str, Any]:
        info = model["entities"][key]
        entity = info["entity"]
        return {
            "id": f"e:{key}", "kind": "identifier", "key": key, "type": entity.get("type"),
            "value": entity.get("value"), "display": entity.get("display") or entity.get("value"),
            "status": entity.get("status"), "note": entity.get("note"),
            "first_seen": entity.get("first_seen"), "last_seen": entity.get("last_seen"),
            "found_by": info["found_by"], "searched_by": len(info["searched_in"]),
            "shared": info["shared"], "root": not info["found_in"], "image": model["images"].get(key),
        }

    @staticmethod
    def _lookup_node(model: dict[str, Any], lookup_id: str, shown: int) -> dict[str, Any]:
        lookup = model["lookups"][lookup_id]
        return {
            "id": lookup_id, "kind": "lookup", "result_id": lookup["result_id"], "child_id": lookup["child_id"],
            "service": lookup["service"], "method": lookup["method"], "target": lookup["target"],
            "summary": lookup["summary"], "timestamp": lookup["timestamp"], "triage": lookup["triage"],
            "partial": lookup["partial"], "found": len(lookup["found"]),
            # newest first; result_id, child_id and timestamp above are the latest run's
            "runs": lookup["runs"], "rerun": len(lookup["runs"]) > 1,
            "hidden": len(lookup["found"]) - shown,
            "root": not lookup["searched"] and not lookup["parent"],
        }

    @staticmethod
    def _group_node(group: dict[str, Any]) -> dict[str, Any]:
        return {"id": group["id"], "kind": "group", "lookup": group["lookup"], "key": group["key"],
                "label": group["label"], "count": len(group["members"])}

    @staticmethod
    def _open_children(model: dict[str, Any], lookup: dict[str, Any], pinned: set,
                       groups: dict[str, dict[str, Any]]) -> list[tuple[str, str]]:
        """What an opened lookup shows besides the identifiers shown anyway:
        [(kind, id)] - each finding when there are few, else a group per type (or
        site category), with a group of one shown as its identifier. Adds the groups to ``groups``."""
        if len(lookup["found"]) <= GRAPH_INLINE_MAX:
            return [("identifier", key) for key in lookup["found"] if key not in pinned]
        found: dict[str, dict[str, Any]] = {}
        for key in lookup["found"]:
            if key not in pinned:
                group_key, label = model["group_of"][(lookup["id"], key)]
                found.setdefault(group_key, {"id": f"g:{lookup['id']}:{group_key}", "lookup": lookup["id"],
                                             "key": group_key, "label": label, "members": []})["members"].append(key)
        children = []
        for group in found.values():
            if len(group["members"]) > 1:
                groups[group["id"]] = group
                children.append(("group", group["id"]))
            else:
                children.append(("identifier", group["members"][0]))
        return children

    def _graph_view(self, model: dict[str, Any], budget: int) -> dict[str, Any]:
        """Which identifiers are shown on their own and which lookups are open, within
        ``budget`` nodes: what must be shown, then the most connected identifiers while
        there is room, then the deepest (then biggest) lookups close."""
        view = model["views"].get(budget)
        if view is not None:
            return view
        lookups, must = model["lookups"], model["must"]
        base = len(lookups) + len(must)
        room = budget - base - sum(len(self._open_children(model, lookup, must, {})) for lookup in lookups.values())
        pinned = must | set(model["extra"][:max(0, room)])

        groups: dict[str, dict[str, Any]] = {}
        opened = {lid: self._open_children(model, lookup, pinned, groups) for lid, lookup in lookups.items()}
        total = len(lookups) + len(pinned) + sum(len(c) for c in opened.values())
        for lid in sorted(opened, key=lambda lid: (-model["depth"].get(lid, 0), -len(opened[lid]))):
            if total <= budget:
                break
            total -= len(opened[lid])
            opened[lid] = []
        view = model["views"][budget] = {"pinned": pinned, "opened": opened, "groups": groups}
        return view

    def get_graph(self, investigation_id: UUID, noise: bool = False,
                  budget: int = GRAPH_NODE_BUDGET) -> dict[str, Any]:
        """The first view: roots, every lookup, the identifiers that matter and the
        rest folded into groups. Past ``budget`` nodes the deepest lookups stay closed."""
        model = self._graph_model(investigation_id, noise)
        view = self._graph_view(model, budget)
        lookups, pinned, opened = model["lookups"], view["pinned"], view["opened"]

        nodes: dict[str, dict[str, Any]] = {}
        edges: dict[str, dict[str, Any]] = {}
        for key in pinned:
            nodes[f"e:{key}"] = self._identifier_node(model, key)
        for lid, lookup in lookups.items():
            shown = sum(1 for k in lookup["found"] if k in pinned)
            for kind, child in opened[lid]:
                if kind == "group":
                    nodes[child] = self._group_node(view["groups"][child])
                    edges[f"{lid}>{child}"] = _edge(lid, child, "found", lookup)
                else:
                    nodes[f"e:{child}"] = self._identifier_node(model, child)
                    edges[f"{lid}>e:{child}"] = _edge(lid, f"e:{child}", "found", lookup)
                    shown += 1
            node = self._lookup_node(model, lid, shown)
            node["open"] = bool(opened[lid]) or not node["hidden"]
            nodes[lid] = node
            for key in lookup["searched"]:
                edges[f"e:{key}>{lid}"] = _edge(f"e:{key}", lid, "searched", lookup)
            for key in lookup["found"]:
                if key in pinned:
                    edges[f"{lid}>e:{key}"] = _edge(lid, f"e:{key}", "found", lookup)
            if lookup["parent"] and not lookup["searched"]:
                edges[f"{lookup['parent']}>{lid}"] = _edge(lookup["parent"], lid, "followup", lookup)

        identifiers = sum(1 for n in nodes.values() if n["kind"] == "identifier")
        per_type: dict[str, int] = {}
        for info in model["entities"].values():
            entity_type = info["entity"].get("type")
            per_type[entity_type] = per_type.get(entity_type, 0) + 1
        return {
            "nodes": list(nodes.values()),
            "edges": list(edges.values()),
            "state": self.get_graph_state(investigation_id),
            "stats": {
                "nodes": len(nodes), "edges": len(edges), "budget": budget, "over_budget": len(nodes) > budget,
                "identifiers": len(model["entities"]), "lookups": len(lookups),
                "groups": sum(1 for n in nodes.values() if n["kind"] == "group"),
                "shown": identifiers, "folded": len(model["entities"]) - identifiers,
                "noise": model["left_out"]["noise"], "false_positive": model["left_out"]["false_positive"],
                "types": per_type,
            },
        }

    def graph_node_details(self, investigation_id: UUID, node_id: str,
                           noise: bool = False) -> Optional[dict[str, Any]]:
        """One node for the side panel, with the lookups around it: for an identifier,
        the lookups that found it and that looked it up, and the other cases it is in;
        for a group, its lookup."""
        model = self._graph_model(investigation_id, noise)
        lookups = model["lookups"]
        node_id = model["runs"].get(node_id, node_id)

        def lookup_node(lookup_id):
            lookup = lookups[lookup_id]
            return self._lookup_node(model, lookup_id, sum(1 for k in lookup["found"] if k in model["must"]))

        if node_id.startswith("e:") and node_id[2:] in model["entities"]:
            key = node_id[2:]
            info = model["entities"][key]
            return {"node": self._identifier_node(model, key),
                    "found_in": [lookup_node(lid) for lid in info["found_in"]],
                    "searched_in": [lookup_node(lid) for lid in info["searched_in"]],
                    "elsewhere": self.investigations_with([key], exclude=investigation_id).get(key, [])}
        if node_id in lookups:
            lookup = lookups[node_id]
            return {"node": lookup_node(node_id), "parent": lookup_node(lookup["parent"]) if lookup["parent"] else None}
        if node_id.startswith("g:"):
            group = self._graph_view(model, GRAPH_NODE_BUDGET)["groups"].get(node_id)
            if group:
                return {"node": self._group_node(group), "lookup": lookup_node(group["lookup"])}
        return None

    def expand_graph_node(self, investigation_id: UUID, node_id: str, offset: int = 0, limit: int = 40,
                          noise: bool = False, budget: int = GRAPH_NODE_BUDGET) -> Optional[dict[str, Any]]:
        """The children of one lookup, group or identifier, a page at a time, most
        relevant first (triaged, then found by more lookups, then by type and value).
        None when the node isn't in the graph."""
        model = self._graph_model(investigation_id, noise)
        view = self._graph_view(model, budget)
        lookups, pinned, groups = model["lookups"], view["pinned"], view["groups"]
        if node_id.startswith("more:"):
            node_id, _, at = node_id[5:].rpartition(":")
            offset = int(at) if at.isdigit() else offset
        node_id = model["runs"].get(node_id, node_id)     # any run of a lookup opens the lookup

        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        if node_id in lookups:
            lookup = lookups[node_id]
            children = [("identifier", k) for k in lookup["found"] if k in pinned] \
                + self._open_children(model, lookup, pinned, {})
            children += [("lookup", lid) for lid in model["children"].get(node_id, [])]
        elif node_id in groups:
            lookup = lookups[groups[node_id]["lookup"]]
            children = [("identifier", k) for k in groups[node_id]["members"]]
        elif node_id.startswith("e:") and node_id[2:] in model["entities"]:
            info = model["entities"][node_id[2:]]
            lookup = None
            children = [("lookup", lid) for lid in info["searched_in"]]
        else:
            return None

        page = children[offset:offset + limit]
        for kind, child in page:
            if kind == "group":
                nodes.append(self._group_node(groups[child]))
                edges.append(_edge(node_id, child, "found", lookup))
            elif kind == "lookup":
                child_lookup = lookups[child]
                shown = sum(1 for k in child_lookup["found"] if k in pinned)
                nodes.append(self._lookup_node(model, child, shown))
                edges.append(_edge(node_id, child, "followup" if node_id in lookups else "searched", child_lookup))
            else:
                nodes.append(self._identifier_node(model, child))
                edges.append(_edge(node_id, f"e:{child}", "member" if node_id in groups else "found", lookup))
        rest = len(children) - offset - len(page)
        if rest > 0:
            more_id = f"more:{node_id}:{offset + len(page)}"
            nodes.append({"id": more_id, "kind": "more", "parent": node_id, "offset": offset + len(page),
                          "count": rest})
            edges.append(_edge(node_id, more_id, "more"))
        return {"node": node_id, "offset": offset, "total": len(children), "nodes": nodes, "edges": edges}
