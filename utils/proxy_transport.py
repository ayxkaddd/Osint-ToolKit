"""Route httpx (and external CLI tools) through the rotating proxy pool.

The scraping services build their clients with :func:`make_async_client` instead
of ``httpx.AsyncClient(...)``. It installs :class:`RotatingProxyTransport`, which
gives each request a fast, lightly loaded proxy, tries another if that one fails
(or, with ``attempt_timeout``, is too slow), and then falls back to a direct
connection - so a poor proxy pool costs seconds per check, not the whole
timeout. When the pool is disabled or empty the transport is a plain direct
transport, i.e. exactly the previous behaviour.

See :mod:`services.proxy_pool` for how the healthy set is built and refreshed.
"""
import asyncio
import logging
import time
from typing import Optional

import httpx

from services.proxy_pool import pool

logger = logging.getLogger(__name__)

try:  # the SOCKS handshake fails with socksio's own error, which httpx doesn't wrap
    from socksio.exceptions import ProtocolError as SocksProtocolError
except ImportError:  # pragma: no cover - httpx[socks] not installed
    SocksProtocolError = httpx.ProxyError

# Errors raised before any request body is sent: safe to retry on another proxy.
CONNECT_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.ProxyError, httpx.PoolTimeout,
                  SocksProtocolError)
# Requests without a body: any failure can be retried elsewhere, and a slow
# attempt can be cut off, without sending anything twice.
REPLAYABLE_METHODS = ("GET", "HEAD", "OPTIONS")

# Per-proxy connect budget so a couple of attempts plus a direct fall-back still
# fit inside a module's own per-request timeout (e.g. username's 10s wait_for).
PROXY_CONNECT_TIMEOUT = 3.0
# Alternative proxies to try after the first before giving up and going direct.
PROXY_RETRIES = 1


class RotatingProxyTransport(httpx.AsyncBaseTransport):
    def __init__(self, *, verify=True, limits: Optional[httpx.Limits] = None,
                 retries: int = PROXY_RETRIES, attempt_timeout: Optional[float] = None):
        """``attempt_timeout``: seconds a proxy gets to answer (headers) a GET before
        the next proxy, then a direct connection, is tried. Leave None for slow
        endpoints; set it where many quick requests share a deadline (username)."""
        self._verify = verify
        self._limits = limits if limits is not None else httpx.Limits()
        self._retries = retries
        self._attempt_timeout = attempt_timeout
        self._direct = httpx.AsyncHTTPTransport(verify=verify, limits=self._limits, retries=0)
        self._by_proxy: dict[str, httpx.AsyncHTTPTransport] = {}

    def _transport_for(self, url: str) -> httpx.AsyncHTTPTransport:
        transport = self._by_proxy.get(url)
        if transport is None:
            transport = httpx.AsyncHTTPTransport(proxy=url, verify=self._verify,
                                                 limits=self._limits, retries=0)
            self._by_proxy[url] = transport
        return transport

    @staticmethod
    def _set_connect(request: httpx.Request, original, connect: float) -> None:
        timeout = dict(original or {})
        current = timeout.get("connect")
        timeout["connect"] = connect if current is None else min(current, connect)
        request.extensions["timeout"] = timeout

    @staticmethod
    def _restore(request: httpx.Request, original) -> None:
        if original is None:
            request.extensions.pop("timeout", None)
        else:
            request.extensions["timeout"] = original

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if not pool.enabled():
            return await self._direct.handle_async_request(request)

        replayable = request.method in REPLAYABLE_METHODS
        original_timeout = request.extensions.get("timeout")
        tried: set[str] = set()
        try:
            for _ in range(1 + self._retries):
                url = pool.pick(exclude=tried)
                if not url:
                    break
                tried.add(url)
                self._set_connect(request, original_timeout, PROXY_CONNECT_TIMEOUT)
                proxy = pool.acquire(url)
                start = time.monotonic()
                try:
                    attempt = self._transport_for(url).handle_async_request(request)
                    if replayable and self._attempt_timeout:
                        response = await asyncio.wait_for(attempt, self._attempt_timeout)
                    else:
                        response = await attempt
                except (asyncio.TimeoutError, *CONNECT_ERRORS):
                    pool.report(url, ok=False)
                    continue
                except asyncio.CancelledError:
                    # Cut off by the caller's own deadline: this proxy was too slow
                    pool.report(url, ok=False)
                    raise
                except Exception:  # noqa: BLE001
                    # httpx.TransportError, or a SOCKS error httpx doesn't wrap
                    # (socksio's ProtocolError "Malformed reply" from a broken proxy)
                    pool.report(url, ok=False)
                    if replayable:
                        continue
                    raise  # the body may have been sent: don't send it twice
                finally:
                    pool.release(proxy)
                pool.report(url, ok=True, latency=time.monotonic() - start)
                return response
            # No proxy answered in time (nothing was sent, or it is safe to resend)
            self._restore(request, original_timeout)
            return await self._direct.handle_async_request(request)
        finally:
            self._restore(request, original_timeout)

    async def aclose(self) -> None:
        await self._direct.aclose()
        for transport in self._by_proxy.values():
            await transport.aclose()
        self._by_proxy.clear()


def make_async_client(*, verify: bool = True, limits: Optional[httpx.Limits] = None,
                      retries: int = PROXY_RETRIES, attempt_timeout: Optional[float] = None,
                      **kwargs) -> httpx.AsyncClient:
    """An AsyncClient that rotates through the proxy pool (direct when disabled).

    ``verify`` and ``limits`` configure the underlying transports (they are
    ignored by httpx once a ``transport=`` is given), so they are consumed here;
    everything else (timeout, follow_redirects, headers, ...) goes to the client.
    See RotatingProxyTransport for ``attempt_timeout``.
    """
    transport = RotatingProxyTransport(verify=verify, limits=limits, retries=retries,
                                       attempt_timeout=attempt_timeout)
    return httpx.AsyncClient(transport=transport, **kwargs)


def proxied_get(url: str, **kwargs) -> httpx.Response:
    """Blocking GET through one healthy proxy, falling back to direct on failure.

    For the few synchronous ``httpx.get`` scrapers (run inside ``to_thread``).
    """
    if pool.enabled():
        proxy = pool.pick()
        if proxy:
            start = time.monotonic()
            try:
                response = httpx.get(url, proxy=proxy, **kwargs)
            except httpx.TransportError:
                pool.report(proxy, ok=False)
            else:
                pool.report(proxy, ok=True, latency=time.monotonic() - start)
                return response
    return httpx.get(url, **kwargs)


def cli_proxy_env() -> dict[str, str]:
    """Proxy environment for an external tool (subfinder, httpx-toolkit), or {}.

    Go-based tools honour HTTP(S)_PROXY and ALL_PROXY (incl. socks5). Merge the
    result over ``os.environ`` when spawning; empty dict means run direct.
    """
    if not pool.enabled():
        return {}
    proxy = pool.pick_for_cli()
    if not proxy:
        return {}
    if proxy.split("://", 1)[0] in ("http", "https"):
        return {"HTTP_PROXY": proxy, "HTTPS_PROXY": proxy,
                "http_proxy": proxy, "https_proxy": proxy}
    return {"ALL_PROXY": proxy, "all_proxy": proxy}
