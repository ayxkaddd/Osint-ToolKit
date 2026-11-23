"""plugin.yaml: the models it is read into and the checks on it."""
import json
from typing import TYPE_CHECKING, Any, Literal, Optional, Union
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from services.entities import ENTITY_TYPES
from .constants import FILTERS, KEY_RE, MAX_ITEMS, RESOURCES_PATH, TEMPLATE_RE

if TYPE_CHECKING:
    from .registry import Plugin


Scalar = Union[str, int, float, bool]


class SettingSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = ""
    secret: bool = False
    required: bool = True
    help: str = ""


class RequestSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    method: Literal["GET", "POST"] = "GET"
    url: str
    query: dict[str, Scalar] = {}
    headers: dict[str, Scalar] = {}
    json_body: Any = Field(None, alias="json")
    form: dict[str, Scalar] = {}
    timeout: float = Field(30, ge=1, le=300)
    empty_status: list[int] = [404]

    @field_validator("url")
    @classmethod
    def literal_host(cls, url: str) -> str:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.netloc or "{" in parts.netloc:
            raise ValueError("url must start with http(s)://host/ and the host can't contain {placeholders}")
        return url


class ResponseSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["json", "text"] = "json"
    root: str = ""
    items: Optional[str] = None
    limit: int = Field(200, ge=1, le=MAX_ITEMS)
    unique: Optional[str] = None
    title: str = ""
    subtitle: str = ""
    url: str = ""
    image: str = ""
    site: str = ""
    category: str = ""
    fields: Optional[dict[str, str]] = None
    entities: dict[str, Union[str, list[str]]] = {}
    # Work the cards out from every answer (APIs whose answers change shape). What is
    # set above still wins: title, link...; fields and entities are added to the detected ones.
    auto: bool = False

    @field_validator("entities")
    @classmethod
    def known_types(cls, entities):
        unknown = [t for t in entities if t not in ENTITY_TYPES]
        if unknown:
            raise ValueError(f"unknown identifier type {', '.join(unknown)} (known: {', '.join(ENTITY_TYPES)})")
        return entities


class ActionSpec(BaseModel):
    """One of several lookups of a no-code plugin (requests:), e.g. Hunter's email
    verifier and domain search: each has its own inputs, request and cards."""
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    name: str = Field(min_length=1, max_length=80)
    accepts: list[str] = Field(min_length=1)
    request: RequestSpec
    response: ResponseSpec = Field(default_factory=lambda: ResponseSpec())

    @field_validator("accepts")
    @classmethod
    def known_accepts(cls, accepts):
        unknown = [t for t in accepts if t not in ENTITY_TYPES]
        if unknown:
            raise ValueError(f"unknown identifier type {', '.join(unknown)} (known: {', '.join(ENTITY_TYPES)})")
        return list(dict.fromkeys(accepts))


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Optional[str] = None
    name: str = Field(min_length=1, max_length=80)
    description: str = ""
    icon: str = Field("puzzle", pattern=r"^[a-z0-9-]{1,40}$")   # lucide icon name
    site: str = ""                                               # domain: card icon
    placeholder: str = ""
    cost: Literal["free", "paid"] = "free"
    cost_note: str = ""
    speed: Literal["fast", "medium", "slow"] = "fast"
    concurrency: int = Field(2, ge=1, le=5)
    timeout: float = Field(120, ge=5, le=1800)                   # Python plugins: the whole run
    accepts: list[str] = []              # with requests: defaults to what its lookups accept
    settings: dict[str, SettingSpec] = {}
    request: Optional[RequestSpec] = None
    request_by_type: dict[str, RequestSpec] = {}
    response: ResponseSpec = Field(default_factory=lambda: ResponseSpec())
    requests: list[ActionSpec] = []      # several lookups instead of request:/response:

    @field_validator("accepts")
    @classmethod
    def known_accepts(cls, accepts):
        unknown = [t for t in accepts if t not in ENTITY_TYPES]
        if unknown:
            raise ValueError(f"unknown identifier type {', '.join(unknown)} (known: {', '.join(ENTITY_TYPES)})")
        return list(dict.fromkeys(accepts))

    @field_validator("settings")
    @classmethod
    def setting_names(cls, settings):
        bad = [k for k in settings if not KEY_RE.match(k)]
        if bad:
            raise ValueError(f"setting names must be UPPER_CASE: {', '.join(bad)}")
        return settings

    @model_validator(mode="after")
    def by_type_accepted(self):
        if self.requests:
            if self.request or self.request_by_type:
                raise ValueError("use either request: (one lookup) or requests: (several), not both")
            ids = [a.id for a in self.requests]
            if len(set(ids)) != len(ids):
                raise ValueError("every lookup in requests: needs a different id")
            self.accepts = list(dict.fromkeys(self.accepts + [t for a in self.requests for t in a.accepts]))
        if not self.accepts:
            raise ValueError("accepts: what the plugin looks up (email, username, domain, ...)")
        extra = [t for t in self.request_by_type if t not in self.accepts]
        if extra:
            raise ValueError(f"request_by_type has {', '.join(extra)}, which is not in accepts")
        return self


def _validation_message(error: ValidationError) -> str:
    parts = []
    for e in error.errors()[:4]:
        where = ".".join(str(p) for p in e.get("loc", ()))
        msg = str(e.get("msg") or "").removeprefix("Value error, ")
        parts.append(f"{where}: {msg}" if where else msg)
    return "; ".join(parts)


def builtin_setting_keys() -> set:
    """API keys / paths of the built-in modules (resources.json)."""
    try:
        modules = json.loads(RESOURCES_PATH.read_text()).get("modules", [])
    except (OSError, json.JSONDecodeError):
        return set()
    return {key.upper() for module in modules for key in (module.get("settings") or {})}


def _templates(manifest: Manifest) -> tuple[list[str], list[str]]:
    """(request templates, response templates) for checking placeholders."""
    request, response = [], []
    specs = [manifest.request, *manifest.request_by_type.values(), *(a.request for a in manifest.requests)]
    for spec in specs:
        if not spec:
            continue
        request.append(spec.url)
        request += [str(v) for part in (spec.query, spec.headers, spec.form) for v in part.values()]
        request += [s for s in _strings(spec.json_body)]
    for r in [manifest.response, *(a.response for a in manifest.requests)]:
        response += [r.title, r.subtitle, r.url, r.image, r.site, r.category]
        response += [v for v in (r.fields or {}).values() if "{" in v]
    return request, response


def _strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def _check_manifest(plugin: "Plugin", manifest: Manifest) -> None:
    if plugin.kind == "python" and (manifest.request or manifest.request_by_type or manifest.requests):
        raise ValueError("has both plugin.py and a request: section - use one of them")
    if plugin.kind == "yaml" and not manifest.request and not manifest.requests \
            and set(manifest.accepts) - set(manifest.request_by_type):
        raise ValueError("needs a request: section (no-code plugin) or a plugin.py (Python plugin)")
    prefix = plugin.id.upper() + "_"
    builtin = builtin_setting_keys()
    for key in manifest.settings:
        if not key.startswith(prefix) and key not in builtin:
            raise ValueError(f"setting {key} must start with {prefix} (or be the key of a built-in module)")
    request, response = _templates(manifest)
    for text in request + response:
        for _name, filters in TEMPLATE_RE.findall(text):
            unknown = [f for f in filters.split("|") if f and f not in FILTERS]
            if unknown:
                raise ValueError(f"unknown filter |{unknown[0]} in {text!r} (known: {', '.join(FILTERS)})")
    for text in request:
        for name, _ in TEMPLATE_RE.findall(text):
            if name in ("value", "type"):
                continue
            if name.startswith("settings.") and name[9:] in manifest.settings:
                continue
            raise ValueError(f"{{{name}}} in {text!r}: requests can use {{value}}, {{type}} and "
                             f"{{settings.NAME}} for settings declared in settings:")
