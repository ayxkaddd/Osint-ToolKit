"""Running a plugin: the input check, its HTTP requests or plugin.py, and the event stream."""
import asyncio
import dataclasses
import inspect
import json
import re
from dataclasses import dataclass
from typing import Any, Optional
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from urllib.parse import urlsplit

import httpx

from plugins.sdk import Context, PluginError, Settings
from services.entities import ENTITY_TYPES, detect, make_entity
from .constants import EMAIL_INPUT_RE, USER_AGENT, logger
from .manifest import RequestSpec, Scalar
from .registry import Action, Plugin, get
from .results import _cap_raw, _snippet, redact, split_output
from .templates import build_items, render


class RunRefused(Exception):
    """The run can't start (unknown plugin, bad input, not set up)."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


@dataclass
class PreparedRun:
    plugin: Plugin
    value: str
    type: str
    items: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    data: Any = None
    raw: Any = None
    note: Optional[str] = None
    stream: Optional[AsyncGenerator[tuple[str, Any], None]] = None
    actions: Optional[list[str]] = None    # only these lookups (requests: plugins)
    warnings: list[str] = dataclasses.field(default_factory=list)
    lookups: list[dict[str, Any]] = dataclasses.field(default_factory=list)   # what each of several did


def _check_input(plugin: Plugin, value: str, kind: Optional[str]) -> tuple[str, str]:
    assert plugin.manifest is not None
    accepts = plugin.manifest.accepts
    value = (value or "").strip()
    if not value:
        raise RunRefused(400, "Enter something to look up")
    if not kind:
        if len(accepts) == 1:
            kind = accepts[0]
        else:
            kind = next((e.type for e in detect(value) if e.type in accepts), None)
            if not kind:
                raise RunRefused(400, f"Choose what '{value}' is: {', '.join(ENTITY_TYPES[t] for t in accepts)}")
    if kind not in accepts:
        raise RunRefused(400, f"{plugin.name} doesn't look up {ENTITY_TYPES.get(kind, kind)}")
    entity = make_entity(kind, value, typed=True)
    if entity:
        value = entity.value
    # Phones without a country code and free-form VK/text values: only the shape is checked
    elif ((kind == "email" and not EMAIL_INPUT_RE.match(value)) or (kind == "phone" and not re.search(r"\d{5}", value))
          or (kind not in ("text", "phone") and re.search(r"\s", value))):
        raise RunRefused(400, f"'{value}' doesn't look like {ENTITY_TYPES[kind].lower()}")
    return value, kind


def _client(plugin: Plugin, timeout: float) -> httpx.AsyncClient:
    hosts = set(plugin.hosts())

    async def same_hosts(request: httpx.Request):
        # Plugins that aren't reviewed may only talk to the hosts in their manifest (redirects too)
        if request.url.host not in hosts:
            raise PluginError(f"Blocked a request to {request.url.host}: only {', '.join(sorted(hosts))} "
                              "is allowed until the plugin is reviewed")

    hooks = {"request": [same_hosts]} if plugin.kind == "yaml" and not plugin.trusted else {}
    return httpx.AsyncClient(timeout=httpx.Timeout(timeout), follow_redirects=True,
                             headers={"User-Agent": USER_AGENT}, event_hooks=hooks)


async def send_request(plugin: Plugin, value: str, kind: str, spec: RequestSpec) -> httpx.Response:
    """Render and send one of a no-code plugin's requests (also used by the plugin builder)."""
    settings = plugin.settings_values()

    def request_lookup(empty: list[str]) -> Callable[[str], Any]:
        def lookup(name: str) -> Any:
            if name == "value":
                return value
            if name == "type":
                return kind
            setting = settings.get(name[9:]) or ""
            if not setting:
                empty.append(name[9:])
            return setting
        return lookup

    def render_map(entries: dict[str, Scalar]) -> dict[str, str]:
        out = {}
        for key, template in entries.items():
            empty: list[str] = []
            text = render(str(template).lower() if isinstance(template, bool) else str(template), request_lookup(empty))
            if not empty:   # entries using an unset optional setting are left out
                out[key] = text
        return out

    def render_json(body: Any) -> Any:
        if isinstance(body, str):
            return render(body, request_lookup([]))
        if isinstance(body, dict):
            return {k: render_json(v) for k, v in body.items()}
        if isinstance(body, list):
            return [render_json(v) for v in body]
        return body

    empty: list[str] = []
    url = render(spec.url, request_lookup(empty), quote_values=True)
    if empty:
        raise RunRefused(400, f"{empty[0]} is not set - add it in Settings")
    host = urlsplit(url).hostname or url
    kwargs: dict[str, Any] = {"params": render_map(spec.query), "headers": render_map(spec.headers)}
    if spec.json_body is not None:
        kwargs["json"] = render_json(spec.json_body)
    elif spec.form:
        kwargs["data"] = render_map(spec.form)
    try:
        async with _client(plugin, spec.timeout) as client:
            return await client.request(spec.method, url, **kwargs)
    except httpx.TimeoutException:
        raise PluginError(f"{host} did not answer within {spec.timeout:g} s") from None
    except httpx.HTTPError as e:
        raise PluginError(f"Request to {host} failed: {e.__class__.__name__}: {e}") from e


def parse_response(response: httpx.Response, format: str) -> Any:
    """JSON answer, or {text, lines} for format: text. Raises ValueError for bad JSON."""
    if format == "json":
        return response.json()
    text = response.text
    return {"text": text, "lines": [line.strip() for line in text.splitlines() if line.strip()]}


async def _run_action(plugin: Plugin, action: Action, value: str, kind: str) -> tuple[list[dict[str, Any]], Any]:
    """One lookup: (cards, answer). Cards are [] when the answer means "nothing found"."""
    response = await send_request(plugin, value, kind, action.request)
    host = response.request.url.host
    if response.status_code in action.request.empty_status:
        return [], None
    if response.status_code >= 400:
        raise PluginError(f"{host} answered HTTP {response.status_code}: {_snippet(response.text)}")
    try:
        data = parse_response(response, action.response.format)
    except ValueError:
        raise PluginError(f"{host} did not answer with JSON: {_snippet(response.text)}") from None
    return build_items(plugin, data, value, kind, action.response), data


async def _run_yaml(run: PreparedRun) -> None:
    """Run the lookups for the input type at the same time. With several, one failing
    is a warning next to the others' cards; all failing is an error."""
    plugin = run.plugin
    actions = plugin.actions(run.type)
    if run.actions:
        actions = [a for a in actions if a.id in run.actions] or actions
    if len(actions) == 1:
        run.items, run.raw = await _run_action(plugin, actions[0], run.value, run.type)
        if plugin.manifest and plugin.manifest.requests:   # say which lookup found them
            for item in run.items:
                item["action"] = actions[0].name
        if run.raw is None:
            run.note = "Nothing found"
        return
    results = await asyncio.gather(*(_run_action(plugin, a, run.value, run.type) for a in actions),
                                   return_exceptions=True)
    errors, raw = [], {}
    for action, result in zip(actions, results, strict=True):
        if isinstance(result, BaseException):
            if not isinstance(result, (PluginError, RunRefused)):
                logger.warning("Plugin %s, %s failed", plugin.id, action.id, exc_info=result)
            errors.append(f"{action.name}: {getattr(result, 'detail', None) or result}")
            run.lookups.append({"name": action.name, "status": "failed"})
            continue
        items, data = result
        for item in items:
            item["action"] = action.name
        run.items += items
        raw[action.id] = data
        run.lookups.append({"name": action.name, "status": "found" if items else "nothing", "count": len(items)})
    if len(errors) == len(actions):
        raise PluginError("; ".join(errors))
    run.warnings = errors
    run.raw = raw


def _plugin_failure(plugin: Plugin, e: BaseException) -> PluginError:
    if isinstance(e, PluginError):
        return e
    if isinstance(e, httpx.TimeoutException):
        return PluginError(f"A request timed out ({e.request.url.host if e.request else 'unknown host'})")
    if isinstance(e, httpx.HTTPStatusError):
        return PluginError(f"{e.request.url.host} answered HTTP {e.response.status_code}: {_snippet(e.response.text)}")
    if isinstance(e, httpx.HTTPError):
        return PluginError(f"Request failed: {e.__class__.__name__}: {e}")
    logger.error("Plugin %s failed", plugin.id, exc_info=e)
    return PluginError(f"plugin.py failed: {e.__class__.__name__}: {e}")


async def _python_stream(plugin: Plugin, agen, client: httpx.AsyncClient, timeout: float):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    try:
        while True:
            try:
                out = await asyncio.wait_for(agen.__anext__(), max(deadline - loop.time(), 0.01))
            except StopAsyncIteration:
                break
            except asyncio.TimeoutError:
                raise PluginError(f"Stopped after {timeout:g} s (timeout: in plugin.yaml)") from None
            except Exception as e:
                raise _plugin_failure(plugin, e) from e
            items, data = split_output(out, plugin)
            for item in items:
                yield "item", item
            if data is not None:
                yield "data", data
    finally:
        try:
            await agen.aclose()
        finally:
            await client.aclose()


async def _run_python(run: PreparedRun) -> None:
    plugin = run.plugin
    assert plugin.manifest is not None and plugin.run is not None
    timeout = plugin.manifest.timeout
    client = httpx.AsyncClient(timeout=httpx.Timeout(30), follow_redirects=True, headers={"User-Agent": USER_AGENT})
    ctx = Context(plugin.id, run.value, run.type, Settings(plugin.settings_values()), client, plugin.log)
    if inspect.isasyncgenfunction(plugin.run):
        run.stream = _python_stream(plugin, plugin.run(run.value, run.type, ctx), client, timeout)
        return
    try:
        if inspect.iscoroutinefunction(plugin.run):
            result = await asyncio.wait_for(plugin.run(run.value, run.type, ctx), timeout)
        else:
            result = await asyncio.wait_for(asyncio.to_thread(plugin.run, run.value, run.type, ctx), timeout)
    except asyncio.TimeoutError:
        raise PluginError(f"Stopped after {timeout:g} s (timeout: in plugin.yaml)") from None
    except Exception as e:
        raise _plugin_failure(plugin, e) from e
    finally:
        await client.aclose()
    run.items, run.data = split_output(result, plugin)


async def prepare(plugin_id: str, value: str, kind: Optional[str],
                  actions: Optional[list[str]] = None) -> PreparedRun:
    """Check the input and run the lookup (async-generator plugins start streaming
    later). Raises RunRefused, or PluginError when the lookup itself failed."""
    plugin = get(plugin_id)
    if not plugin or not plugin.manifest:
        raise RunRefused(404, plugin.error if plugin and plugin.error else f"No plugin '{plugin_id}'")
    blocked = plugin.blocked()
    if blocked:
        raise RunRefused(403, blocked)
    value, kind = _check_input(plugin, value, kind)
    missing = plugin.missing_settings()
    if missing:
        raise RunRefused(400, f"{', '.join(missing)} {'is' if len(missing) == 1 else 'are'} not set - add it in Settings")
    run = PreparedRun(plugin, value, kind, actions=actions or None)
    try:
        if plugin.kind == "python":
            await _run_python(run)
        else:
            await _run_yaml(run)
    except PluginError as e:
        raise PluginError(redact(str(e), plugin.secret_values())) from None
    return run


async def events(run: PreparedRun) -> AsyncIterator[str]:
    """NDJSON lines: started, item..., data, error, done."""
    plugin = run.plugin
    secrets = plugin.secret_values()

    def line(event: dict[str, Any]) -> str:
        return json.dumps(redact(event, secrets), ensure_ascii=False, default=str) + "\n"

    yield line({"event": "started", "plugin": plugin.id, "name": plugin.name, "value": run.value, "type": run.type})
    count = len(run.items)
    for item in run.items:
        yield line({"event": "item", "item": item})
    has_data = run.data is not None
    if has_data:
        yield line({"event": "data", "data": run.data})
    for warning in run.warnings:
        yield line({"event": "warning", "detail": warning})
    error = None
    if run.stream is not None:
        try:
            async for kind, payload in run.stream:
                count += kind == "item"
                has_data = has_data or kind == "data"
                yield line({"event": kind, kind: payload})
        except PluginError as e:
            error = str(e)
        finally:
            await run.stream.aclose()
        if error:
            yield line({"event": "error", "detail": error})
    note = run.note or ("Nothing found" if not count and not has_data and not error else None)
    yield line({"event": "done", "count": count, "completed": error is None, "note": note,
                "lookups": run.lookups or None, "raw": _cap_raw(run.raw)})
