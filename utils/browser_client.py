"""An HTTP client that looks like a real browser to bot protection, with proxy rotation.

Cloudflare and similar services block plain HTTP libraries by their TLS and HTTP/2
fingerprint, whatever the User-Agent says. curl_cffi sends exactly what a current
Chrome sends (TLS hello, HTTP/2 settings, header order and the headers themselves),
so many of those sites answer normally. Pages with a JavaScript challenge still
need a real browser.

The browser's own headers are kept on purpose: a Firefox or Safari User-Agent on
top of Chrome's fingerprint looks forged and gets blocked more, not less. Only
headers a site specifically needs should be passed in.

Requests go through the proxy pool exactly like the httpx clients
(utils.proxy_transport.send_rotating): a fast proxy, another one, then direct.
"""
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Optional

from curl_cffi.const import CurlECode
from curl_cffi.curl import CURL_WRITEFUNC_ERROR
from curl_cffi.requests import AsyncSession
from curl_cffi.requests.exceptions import RequestException
from curl_cffi.requests.exceptions import Timeout as CurlTimeout

from utils.proxy_transport import (PROXY_CONNECT_TIMEOUT, PROXY_RETRIES, REPLAYABLE_METHODS,
                                   send_rotating)

# The newest Chrome this curl_cffi version can imitate
BROWSER = "chrome"
MAX_REDIRECTS = 20  # as httpx

# Failures that happen before the request is sent: safe to resend a body elsewhere
_CONNECT_CODES = {CurlECode.COULDNT_RESOLVE_PROXY, CurlECode.COULDNT_CONNECT,
                  CurlECode.SSL_CONNECT_ERROR, CurlECode.PROXY}
_CHARSET = re.compile(r"charset=[\"']?([\w.:-]+)", re.I)
_CURL_MESSAGE = re.compile(r"curl: \(\d+\) (.*?)(?:\. See https://curl\.se\S*.*)?$", re.S)


class RequestError(Exception):
    """The request failed (no answer). The message is short and readable."""


class RequestTimeout(RequestError):
    pass


def _connect_error(error: BaseException) -> bool:
    if not isinstance(error, RequestException):
        return False
    if error.code in _CONNECT_CODES:
        return True
    return error.code == CurlECode.OPERATION_TIMEDOUT and "Connection timed out" in str(error)


def _readable(error: RequestException) -> str:
    match = _CURL_MESSAGE.search(str(error))
    return (match.group(1) if match else str(error)).strip()


@dataclass
class _Redirect:
    status_code: int


@dataclass
class BrowserResponse:
    status_code: int
    headers: Mapping[str, Any]  # case-insensitive
    content: bytes
    url: str = ""
    history: list = field(default_factory=list)

    @property
    def text(self) -> str:
        charset = _CHARSET.search(self.headers.get("content-type", ""))
        try:
            return self.content.decode(charset.group(1) if charset else "utf-8", errors="replace")
        except LookupError:  # a charset Python doesn't know
            return self.content.decode("utf-8", errors="replace")

    @classmethod
    def from_curl(cls, response: Any, body: bytes) -> "BrowserResponse":
        # curl_cffi's own (case-insensitive) headers: values can hold any characters
        # (a WordPress header has an emoji), which httpx.Headers would refuse
        headers = response.headers
        history = [_Redirect(h["status_code"] if isinstance(h, dict) else h.status_code)
                   for h in (response.history or [])]
        return cls(status_code=response.status_code, headers=headers, content=body,
                   url=str(response.url or ""), history=history)


class BrowserClient:
    """Async client with Chrome's fingerprint. ``max_body``: read at most this many
    bytes of a body (the rest is not downloaded). ``attempt_timeout``: see
    utils.proxy_transport.RotatingProxyTransport."""

    def __init__(self, *, timeout: float = 10.0, connect_timeout: float = 5.0, max_clients: int = 30,
                 verify: bool = True, follow_redirects: bool = True, max_body: Optional[int] = None,
                 retries: int = PROXY_RETRIES, attempt_timeout: Optional[float] = None,
                 impersonate: str = BROWSER):
        self._timeout = timeout
        self._connect_timeout = connect_timeout
        self._max_body = max_body
        self._retries = retries
        self._attempt_timeout = attempt_timeout
        # max_clients is curl's own concurrency cap (default 10): keep it at the caller's width
        self._session = AsyncSession(impersonate=impersonate, max_clients=max_clients, verify=verify,
                                     allow_redirects=follow_redirects, max_redirects=MAX_REDIRECTS)

    async def __aenter__(self) -> "BrowserClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._session.close()

    async def get(self, url: str, **kwargs) -> BrowserResponse:
        return await self.request("GET", url, **kwargs)

    async def request(self, method: str, url: str, *, headers: Optional[dict] = None, json: Any = None,
                      data: Any = None, content: Any = None) -> BrowserResponse:
        """Raises RequestTimeout or RequestError when there is no answer."""
        method = method.upper()

        async def send(proxy: Optional[str]) -> BrowserResponse:
            return await self._send(method, url, headers, json, data if data is not None else content, proxy)

        try:
            return await send_rotating(send, replayable=method in REPLAYABLE_METHODS,
                                       connect_error=_connect_error, retries=self._retries,
                                       attempt_timeout=self._attempt_timeout)
        except CurlTimeout as e:
            raise RequestTimeout("Timeout") from e
        except RequestException as e:
            raise RequestError(_readable(e)) from e

    async def _send(self, method, url, headers, json, data, proxy) -> BrowserResponse:
        body = bytearray()
        cut = False

        def collect(chunk: bytes):
            nonlocal cut
            body.extend(chunk)
            if self._max_body and len(body) >= self._max_body:
                cut = True
                return CURL_WRITEFUNC_ERROR  # stop downloading: we have enough
            return len(chunk)

        connect = PROXY_CONNECT_TIMEOUT if proxy else self._connect_timeout
        try:
            response = await self._session.request(
                method, url, headers=headers, json=json, data=data, proxy=proxy,
                timeout=(connect, self._timeout), content_callback=collect)
        except RequestException as e:
            if not (cut and e.code == CurlECode.WRITE_ERROR and e.response is not None):
                raise
            response = e.response
        content = bytes(body[:self._max_body]) if self._max_body else bytes(body)
        return BrowserResponse.from_curl(response, content)
