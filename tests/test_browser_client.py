"""BrowserClient (curl_cffi with Chrome's fingerprint): browser headers, readable errors,
and proxy rotation (a proxy, then direct). No network: local servers only."""
import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from curl_cffi.const import CurlECode
from curl_cffi.requests.exceptions import RequestException

from services.proxy_pool import Proxy, pool
from utils.browser_client import BrowserClient, BrowserResponse, RequestError, RequestTimeout
from utils.config import update_env


def _set_healthy(urls):
    pool._healthy = [Proxy(url=u, latency=0.0) for u in urls]
    pool._by_url = {p.url: p for p in pool._healthy}


@pytest.fixture(autouse=True)
def _reset_pool():
    _set_healthy([])
    yield
    _set_healthy([])
    update_env({"PROXY_ENABLED": "false"})


def _serve(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"127.0.0.1:{srv.server_address[1]}"


class _Echo(BaseHTTPRequestHandler):
    """Answers with what it was sent; as a forward proxy (absolute URL) it says so."""
    def log_message(self, *args):
        pass

    def do_GET(self):
        via = "proxy" if self.path.startswith("http://") else "direct"
        if self.path.endswith("/emoji-header"):
            self.send_response(200)
            self._headers_buffer.append("X-Note: ⛄ snow\r\n".encode())  # raw UTF-8, as WordPress does
            self.send_header("Content-Type", "TEXT/plain")
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")
            return
        if self.path.endswith("/slow"):
            import time
            time.sleep(3)
        body = f"{via}|{self.headers.get('User-Agent')}|{self.headers.get('X-Site')}".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def echo():
    srv, host = _serve(_Echo)
    yield host
    srv.shutdown()


def _get(url, **kwargs):
    async def run():
        async with BrowserClient(timeout=5, connect_timeout=2, **kwargs) as client:
            return await client.get(url, headers={"X-Site": "kept"})
    return asyncio.run(run())


def test_sends_chrome_headers_and_keeps_site_headers(echo):
    via, agent, site = _get(f"http://{echo}/x").text.split("|")
    assert via == "direct" and "Chrome/" in agent and site == "kept"


def test_headers_with_any_characters_are_read(echo):
    response = _get(f"http://{echo}/emoji-header")
    assert response.text == "ok" and response.headers.get("content-type") == "TEXT/plain"
    assert "snow" in response.headers.get("X-NOTE")


def test_username_checks_send_no_user_agent_of_their_own():
    # A Firefox/Safari UA on top of Chrome's TLS fingerprint gets blocked more, not less
    from services.username_service import StreamingUsernameSearchService
    service = StreamingUsernameSearchService()
    _, _, kwargs = service._build_request({"uri_check": "https://a.test/{account}"}, "bob")
    assert kwargs["headers"] == {}
    _, _, kwargs = service._build_request(
        {"uri_check": "https://a.test/{account}", "headers": {"User-Agent": "special"}}, "bob")
    assert kwargs["headers"] == {"User-Agent": "special"}


def test_errors_are_short_and_readable():
    with pytest.raises(RequestError) as error:
        _get("http://127.0.0.1:1/x")
    assert "curl.se" not in str(error.value) and "connect" in str(error.value).lower()


def test_slow_answer_is_a_timeout(echo):
    async def run():
        async with BrowserClient(timeout=0.5, connect_timeout=0.5) as client:
            await client.get(f"http://{echo}/slow")
    with pytest.raises(RequestTimeout):
        asyncio.run(run())


def test_goes_through_a_proxy_from_the_pool(echo):
    # The echo server doubles as an HTTP forward proxy: it sees the absolute URL
    _set_healthy([f"http://{echo}"])
    update_env({"PROXY_ENABLED": "true"})
    assert _get("http://site.test/x").text.startswith("proxy|")
    assert pool._by_url[f"http://{echo}"].fails == 0


def _fake_send(client, proxy_behaviour, calls):
    async def send(method, url, headers, json, data, proxy):
        calls.append(proxy)
        if proxy:
            return await proxy_behaviour()
        return BrowserResponse(status_code=200, headers=httpx.Headers(), content=b"direct")
    client._send = send


def _drive(method, proxy_behaviour, **kwargs):
    _set_healthy(["http://p:1"])
    update_env({"PROXY_ENABLED": "true"})
    calls = []

    async def run():
        async with BrowserClient(**kwargs) as client:
            _fake_send(client, proxy_behaviour, calls)
            return await client.request(method, "http://site.test/", data="x" if method == "POST" else None)
    return asyncio.run(run()), calls


def _raise(code):
    async def behaviour():
        raise RequestException("Failed to perform, curl: (%d) nope" % code, code)
    return behaviour


def test_dead_proxy_falls_back_to_direct():
    response, calls = _drive("GET", _raise(CurlECode.COULDNT_CONNECT))
    assert response.content == b"direct" and calls == ["http://p:1", None]
    assert pool._by_url["http://p:1"].fails == 1


def test_slow_proxy_is_cut_off():
    async def slow():
        await asyncio.sleep(2)
    response, calls = _drive("GET", slow, attempt_timeout=0.05)
    assert response.content == b"direct" and pool._by_url["http://p:1"].fails == 1


@pytest.mark.parametrize("code,retried", [
    (CurlECode.COULDNT_CONNECT, True),   # nothing sent yet: safe to resend the body
    (CurlECode.RECV_ERROR, False),       # the body may have gone out: not sent twice
])
def test_post_is_resent_only_when_nothing_was_sent(code, retried):
    if retried:
        response, calls = _drive("POST", _raise(code))
        assert calls == ["http://p:1", None]
    else:
        with pytest.raises(RequestError):
            _drive("POST", _raise(code))
    assert pool._by_url["http://p:1"].fails == 1
