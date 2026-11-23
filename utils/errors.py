"""What an error tells the browser.

Exception text can carry a request URL with an API key in its query string, file
paths or other internals, and lookups save it into the investigation. Routes log
the whole error and answer with a short description of what went wrong.
"""
import asyncio
import logging
from typing import NoReturn

import httpx
from fastapi import HTTPException

logger = logging.getLogger(__name__)


def describe(exc: BaseException) -> str:
    """A short reason, without URLs, keys or paths."""
    if isinstance(exc, httpx.HTTPStatusError):
        return f"the service answered HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.TimeoutException) or isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return "no answer in time"
    if isinstance(exc, httpx.RequestError):
        try:
            host = exc.request.url.host
        except RuntimeError:  # no request attached
            host = ""
        return f"could not reach {host}" if host else "could not reach the service"
    return "unexpected error (details in the server log)"


def fail(what: str, exc: BaseException, status_code: int = 500) -> NoReturn:
    """Raise the HTTP error for a failed request: an HTTPException as it is (it already
    says what to tell the user), anything else logged and described by `describe`."""
    if isinstance(exc, HTTPException):
        raise exc
    logger.error("%s", what, exc_info=exc)
    raise HTTPException(status_code=status_code, detail=f"{what}: {describe(exc)}") from exc
