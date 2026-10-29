# utils/investigation_decorator.py
"""``@save_investigation`` - record a route's output in the active investigation.

Usage::

    @router.get("/search")
    @save_investigation(service_name="ns", method_name="lookup_ns")
    async def search(...): ...

* Plain results (dicts, lists, Pydantic models, JSONResponse) are saved after the
  handler returns. ``store=`` can shrink the result before it is written.
* Streaming responses (SSE / NDJSON) are *teed*: every chunk reaches the client
  immediately and a copy is collected; when the stream finishes (or the client
  disconnects - saved as ``partial``) the copy is parsed into events and
  ``stream_reducer=`` turns them into the stored result.
* The investigation is taken from an ``investigation_id`` query param / form
  field / ``X-Investigation-ID`` header when it names an existing investigation,
  otherwise the current investigation. Nothing is saved when there is none.
* ``parent_result_id`` (query param or ``X-Parent-Result-ID`` header) attaches
  the result to an earlier one, so follow-up lookups stay grouped.
* ``service_name`` may be a function of the route's arguments (plugins save under
  their own id).
* The response carries ``X-Investigation-Result-ID`` so the client can group
  later follow-ups under this result.
"""
import asyncio
import dataclasses
import enum
import inspect
import json
import logging
from functools import wraps
from typing import Any, Callable, Optional, Union
from uuid import UUID

import anyio
from fastapi import UploadFile
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

from services.investigation_service import InvestigationService, _new_result_id
from utils.stream_reducers import parse_stream

logger = logging.getLogger(__name__)
investigation_service = InvestigationService()

RESULT_ID_HEADER = "X-Investigation-Result-ID"
_REQUEST_PARAM = "_investigation_request"
_RESPONSE_PARAM = "_investigation_response"
_SKIP_PARAMS = {"investigation_id", "parent_result_id", "request", "response", "background_tasks",
                _REQUEST_PARAM, _RESPONSE_PARAM}
_SECRET_PARAM_HINTS = ("password", "token", "secret", "api_key", "auth_key", "apikey")
# Keys stripped from stored *results* (API credentials echoed back by services)
_SECRET_RESULT_KEYS = {"api_key", "apikey", "apiKey", "access_token", "auth_token", "psw", "secret"}


def _to_serializable(obj: Any, strip_secrets: bool = False) -> Any:
    """Convert arbitrary objects (Pydantic models, datetimes, bytes, uploads) to JSON-safe data."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, UploadFile):
        return {"filename": obj.filename, "content_type": obj.content_type}
    if isinstance(obj, enum.Enum):
        return _to_serializable(obj.value, strip_secrets)
    if hasattr(obj, 'model_dump') and callable(obj.model_dump):
        return _to_serializable(obj.model_dump(mode="json"), strip_secrets)
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return _to_serializable(dataclasses.asdict(obj), strip_secrets)
    if hasattr(obj, 'dict') and callable(obj.dict) and not isinstance(obj, dict):
        return _to_serializable(obj.dict(), strip_secrets)
    if isinstance(obj, dict):
        return {
            str(k): _to_serializable(v, strip_secrets) for k, v in obj.items()
            if not (strip_secrets and str(k) in _SECRET_RESULT_KEYS)
        }
    if isinstance(obj, (list, tuple, set)):
        return [_to_serializable(item, strip_secrets) for item in obj]
    if isinstance(obj, bytes):
        return f"<bytes: {len(obj)} bytes>"
    if hasattr(obj, 'isoformat') and callable(obj.isoformat):
        return obj.isoformat()
    return str(obj)


def _sanitize_params(args: tuple, kwargs: dict) -> dict:
    """Call parameters as stored with the result (secrets masked, plumbing dropped)."""
    save_kwargs = {}
    for k, v in kwargs.items():
        if k in _SKIP_PARAMS or isinstance(v, (Request, Response)):
            continue
        if any(hint in k.lower() for hint in _SECRET_PARAM_HINTS):
            save_kwargs[k] = "••••••••"
        else:
            save_kwargs[k] = _to_serializable(v)
    save_args = [_to_serializable(a) for a in args if not isinstance(a, (Request, Response))]
    return {"args": save_args, "kwargs": save_kwargs}


def _clean_id(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return None if text in ("", "null", "undefined", "None") else text


def _resolve_investigation(request: Optional[Request], kwargs: dict) -> Optional[UUID]:
    candidates = [kwargs.get("investigation_id")]
    if request is not None:
        candidates += [request.query_params.get("investigation_id"), request.headers.get("X-Investigation-ID")]
    for candidate in candidates:
        candidate = _clean_id(candidate)
        if not candidate:
            continue
        try:
            inv_id = UUID(candidate)
        except ValueError:
            continue
        if investigation_service.get_investigation_info(inv_id):
            return inv_id
    # A stale/invalid id from the client must not silently disable saving
    return investigation_service.get_current_investigation()


def _resolve_parent(request: Optional[Request], kwargs: dict) -> Optional[str]:
    parent = _clean_id(kwargs.get("parent_result_id"))
    if not parent and request is not None:
        parent = _clean_id(request.query_params.get("parent_result_id") or request.headers.get("X-Parent-Result-ID"))
    return parent


def _response_payload(result: Any) -> Any:
    if isinstance(result, Response):
        body = getattr(result, "body", b"") or b""
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return body.decode("utf-8", errors="replace")
    return _to_serializable(result)


def _save(inv_id, service_name, method_name, parameters, stored, result_id, parent_id, partial=False) -> Optional[str]:
    try:
        return investigation_service.save_investigation_result(
            investigation_id=inv_id,
            service_name=service_name,
            method_name=method_name,
            parameters=parameters,
            result=_to_serializable(stored, strip_secrets=True),
            result_id=result_id,
            parent_result_id=parent_id,
            partial=partial,
        )
    except Exception:
        logger.exception("Failed to save investigation result for %s.%s", service_name, method_name)
        return None


def _tee_stream(response: StreamingResponse, on_complete: Callable[[str, bool], None]) -> None:
    """Pass every chunk through to the client while keeping a copy for saving."""
    original = response.body_iterator

    async def tee():
        chunks = []
        completed = False
        try:
            async for chunk in original:
                chunks.append(chunk if isinstance(chunk, (bytes, bytearray)) else str(chunk).encode("utf-8"))
                yield chunk
            completed = True
        finally:
            if not completed and hasattr(original, "aclose"):
                # Client went away mid-stream: stop the producer (shielded, since
                # anyio keeps re-raising cancellation inside a cancelled scope)
                with anyio.CancelScope(shield=True):
                    try:
                        await original.aclose()
                    except Exception:
                        pass
            try:
                on_complete(b"".join(chunks).decode("utf-8", errors="replace"), completed)
            except Exception:
                logger.exception("Failed to save streamed investigation result")

    response.body_iterator = tee()


def save_investigation(
    service_name: Union[str, Callable[[dict], str]],
    method_name: Optional[str] = None,
    store: Optional[Callable[[Any], Any]] = None,
    stream_reducer: Optional[Callable[[list], Any]] = None,
    skip_if: Optional[Callable[[Any], bool]] = None,
):
    """Save the decorated route's output to the active investigation (see module doc).

    ``skip_if(result)`` returning True suppresses saving (e.g. empty lookups).
    """

    def decorator(func: Callable) -> Callable:
        used_method_name = method_name or func.__name__
        signature = inspect.signature(func)

        # Inject Request/Response so headers & query params are readable even
        # when the route itself doesn't declare them. FastAPI fills only one
        # Response parameter per endpoint, so reuse the route's own if it has one.
        def own_param(cls):
            return next((name for name, p in signature.parameters.items()
                         if isinstance(p.annotation, type) and issubclass(p.annotation, cls)), None)

        own_request = own_param(Request)
        own_response = own_param(Response)
        extra = []
        if not own_request:
            extra.append(inspect.Parameter(_REQUEST_PARAM, inspect.Parameter.KEYWORD_ONLY, annotation=Request))
        if not own_response:
            extra.append(inspect.Parameter(_RESPONSE_PARAM, inspect.Parameter.KEYWORD_ONLY, annotation=Response))
        params = list(signature.parameters.values())
        var_kw = [p for p in params if p.kind == inspect.Parameter.VAR_KEYWORD]
        params = [p for p in params if p.kind != inspect.Parameter.VAR_KEYWORD] + extra + var_kw
        new_signature = signature.replace(parameters=params)

        def before(kwargs):
            request = kwargs.get(own_request) if own_request else kwargs.pop(_REQUEST_PARAM, None)
            response = kwargs.get(own_response) if own_response else kwargs.pop(_RESPONSE_PARAM, None)
            return request, response

        def finish(result, request, response, args, kwargs, inv_id, parent_id):
            """Save (or arrange saving of) the result; returns the value to send."""
            parameters = _sanitize_params(args, kwargs)
            service = service_name(kwargs) if callable(service_name) else service_name
            result_id = _new_result_id()
            header_id = parent_id or result_id

            if isinstance(result, StreamingResponse):
                media_type = result.media_type or result.headers.get("content-type")

                def on_complete(text: str, completed: bool):
                    events = parse_stream(text, media_type)
                    if not isinstance(events, list):
                        events = [events]
                    stored = stream_reducer(events) if stream_reducer else events
                    _save(inv_id, service, used_method_name, parameters, stored,
                          result_id, parent_id, partial=not completed)

                _tee_stream(result, on_complete)
                result.headers[RESULT_ID_HEADER] = header_id
                return result, None

            payload = _response_payload(result)
            if isinstance(result, Response) and result.status_code >= 400:
                return result, None  # don't record failed lookups
            stored = store(payload) if store else payload
            if skip_if is not None and skip_if(stored):
                return result, None
            return result, (service, parameters, stored, result_id, parent_id)

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            request, response = before(kwargs)
            inv_id = _resolve_investigation(request, kwargs)
            parent_id = _resolve_parent(request, kwargs)

            result = await func(*args, **kwargs)
            if inv_id is None:
                return result

            result, pending = finish(result, request, response, args, kwargs, inv_id, parent_id)
            if pending:
                service, parameters, stored, result_id, parent_id = pending
                saved_id = await asyncio.to_thread(
                    _save, inv_id, service, used_method_name, parameters, stored, result_id, parent_id
                )
                if saved_id:
                    target = result if isinstance(result, Response) else response
                    if target is not None:
                        target.headers[RESULT_ID_HEADER] = saved_id
            return result

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            request, response = before(kwargs)
            inv_id = _resolve_investigation(request, kwargs)
            parent_id = _resolve_parent(request, kwargs)

            result = func(*args, **kwargs)
            if inv_id is None:
                return result

            result, pending = finish(result, request, response, args, kwargs, inv_id, parent_id)
            if pending:
                service, parameters, stored, result_id, parent_id = pending
                saved_id = _save(inv_id, service, used_method_name, parameters, stored, result_id, parent_id)
                if saved_id:
                    target = result if isinstance(result, Response) else response
                    if target is not None:
                        target.headers[RESULT_ID_HEADER] = saved_id
            return result

        wrapper = async_wrapper if inspect.iscoroutinefunction(func) else sync_wrapper
        wrapper.__signature__ = new_signature
        return wrapper

    return decorator
