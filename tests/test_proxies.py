"""Proxy pool parsing/health/rotation, the rotating transport's fail-over, and
the /api/proxies settings endpoints. No network: the transport is driven with
httpx.MockTransport and the pool's healthy set is set directly."""
import asyncio

import httpx
import pytest

from services.proxy_pool import Proxy, parse_proxy, pool
from utils.config import update_env
from utils.proxy_transport import RotatingProxyTransport


def _set_healthy(urls, latency=0.0):
    pool._healthy = [Proxy(url=u, latency=latency) for u in urls]
    pool._by_url = {p.url: p for p in pool._healthy}


@pytest.fixture(autouse=True)
def _reset_pool():
    _set_healthy([])
    yield
    _set_healthy([])
    update_env({"PROXY_ENABLED": "false"})


@pytest.mark.parametrize("raw,expected", [
    ("1.2.3.4:8080", "http://1.2.3.4:8080"),
    ("socks5://1.2.3.4:1080", "socks5://1.2.3.4:1080"),
    ("http://user:pass@1.2.3.4:3128", "http://user:pass@1.2.3.4:3128"),
    ("  5.6.7.8:3128  ", "http://5.6.7.8:3128"),
    ("# a comment", None),
    ("", None),
    ("garbage", None),
    ("1.2.3.4", None),               # no port
    ("ftp://1.2.3.4:21", None),      # unsupported scheme
])
def test_parse_proxy(raw, expected):
    assert parse_proxy(raw) == expected


def test_parse_proxy_default_scheme():
    assert parse_proxy("5.6.7.8:1080", "socks5") == "socks5://5.6.7.8:1080"


def test_pick_prefers_fast_then_idle_proxy():
    _set_healthy(["http://fast:1", "http://slow:2"])
    pool._by_url["http://fast:1"].latency = 0.5
    pool._by_url["http://slow:2"].latency = 3.0
    assert pool.pick() == "http://fast:1"
    # a fast proxy already carrying many requests loses to an idle slower one
    pool._by_url["http://fast:1"].inflight = 10
    assert pool.pick() == "http://slow:2"


def test_pick_skips_excluded_and_runs_out():
    _set_healthy(["http://a:1", "http://b:2"])
    assert pool.pick(exclude={"http://a:1"}) == "http://b:2"
    assert pool.pick(exclude={"http://a:1", "http://b:2"}) is None


def test_acquire_release_counts_inflight():
    _set_healthy(["http://a:1"])
    proxy = pool.acquire("http://a:1")
    assert proxy.inflight == 1
    pool.release(proxy)
    pool.release(proxy)          # never below zero
    assert proxy.inflight == 0
    assert pool.acquire("http://gone:9") is None


def test_failure_makes_proxy_look_slower():
    _set_healthy(["http://a:1"], latency=1.0)
    pool.report("http://a:1", ok=False)
    assert pool._by_url["http://a:1"].latency == 2.0
    pool.report("http://a:1", ok=True, latency=1.0)   # moves the estimate back down
    assert 1.0 < pool._by_url["http://a:1"].latency < 2.0


def test_refills_when_most_of_the_pool_died():
    import time
    pool._last_refresh = time.time()
    pool._last_size = 100
    _set_healthy([f"http://p:{i}" for i in range(60)])
    assert pool.needs_refresh() is False
    _set_healthy([f"http://p:{i}" for i in range(30)])   # under 40% of the last refresh
    assert pool.needs_refresh() is True


def test_pick_for_cli_skips_socks4():
    _set_healthy(["socks4://a:1", "http://b:2"])
    # socks4 can't be used as a tool proxy; http can
    assert pool.pick_for_cli() in ("http://b:2",)


def test_report_drops_after_max_fails():
    _set_healthy(["http://a:1", "http://b:2"])
    for _ in range(pool.MAX_FAILS):
        pool.report("http://a:1", ok=False)
    assert "http://a:1" not in pool._by_url
    assert all(p.url != "http://a:1" for p in pool._healthy)
    # a success resets the counter for a surviving proxy
    pool.report("http://b:2", ok=False)
    pool.report("http://b:2", ok=True, latency=0.1)
    assert pool._by_url["http://b:2"].fails == 0


def test_disabled_unless_turned_on():
    # Public proxies slow lookups down and get blocked: off unless the operator opts in
    _set_healthy(["http://a:1"])
    update_env({"PROXY_ENABLED": None})
    assert pool.enabled() is False
    assert pool.status()["enabled"] is False


def test_default_source_is_monosans_all_txt():
    from services.proxy_pool import DEFAULT_SOURCES
    assert [url for url, _ in DEFAULT_SOURCES] == [
        "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/all.txt"]


def test_enabled_needs_flag_and_healthy():
    _set_healthy(["http://a:1"])
    update_env({"PROXY_ENABLED": "false"})
    assert pool.enabled() is False
    update_env({"PROXY_ENABLED": "true"})
    assert pool.enabled() is True
    _set_healthy([])
    assert pool.enabled() is False


def _drive(transport, method="GET"):
    async def run():
        async with httpx.AsyncClient(transport=transport) as client:
            return await client.request(method, "http://example.test/", content=b"x" if method == "POST" else None)
    return asyncio.run(run())


def _transport(proxy_h, calls, **kwargs):
    def direct_h(request):
        calls["direct"] += 1
        return httpx.Response(200, text="direct")
    transport = RotatingProxyTransport(verify=False, **kwargs)
    transport._direct = httpx.MockTransport(direct_h)
    transport._by_proxy = {"http://p:1": httpx.MockTransport(proxy_h)}
    return transport


def test_transport_uses_proxy_when_healthy():
    _set_healthy(["http://p:1"])
    update_env({"PROXY_ENABLED": "true"})
    calls = {"proxy": 0, "direct": 0}

    def proxy_h(request):
        calls["proxy"] += 1
        return httpx.Response(200, text="via-proxy")

    def direct_h(request):
        calls["direct"] += 1
        return httpx.Response(200, text="direct")

    transport = RotatingProxyTransport(verify=False)
    transport._direct = httpx.MockTransport(direct_h)
    transport._by_proxy = {"http://p:1": httpx.MockTransport(proxy_h)}

    resp = _drive(transport)
    assert resp.text == "via-proxy"
    assert calls == {"proxy": 1, "direct": 0}
    assert pool._by_url["http://p:1"].fails == 0


def test_transport_fails_over_to_direct_on_connect_error():
    _set_healthy(["http://p:1"])
    update_env({"PROXY_ENABLED": "true"})
    calls = {"direct": 0}

    def proxy_h(request):
        raise httpx.ConnectError("boom", request=request)

    def direct_h(request):
        calls["direct"] += 1
        return httpx.Response(200, text="direct")

    transport = RotatingProxyTransport(verify=False)
    transport._direct = httpx.MockTransport(direct_h)
    transport._by_proxy = {"http://p:1": httpx.MockTransport(proxy_h)}

    resp = _drive(transport)
    assert resp.text == "direct"
    assert calls["direct"] == 1
    assert pool._by_url["http://p:1"].fails == 1  # the dead proxy was marked


def test_transport_goes_direct_when_disabled():
    _set_healthy(["http://p:1"])
    update_env({"PROXY_ENABLED": "false"})
    calls = {"proxy": 0, "direct": 0}

    def proxy_h(request):
        calls["proxy"] += 1
        return httpx.Response(200, text="via-proxy")

    def direct_h(request):
        calls["direct"] += 1
        return httpx.Response(200, text="direct")

    transport = RotatingProxyTransport(verify=False)
    transport._direct = httpx.MockTransport(direct_h)
    transport._by_proxy = {"http://p:1": httpx.MockTransport(proxy_h)}

    resp = _drive(transport)
    assert resp.text == "direct"
    assert calls == {"proxy": 0, "direct": 1}


def test_slow_proxy_is_cut_off_and_the_check_goes_direct():
    # A proxy that connects but doesn't answer used to hold the check for its whole 10s
    _set_healthy(["http://p:1"])
    update_env({"PROXY_ENABLED": "true"})
    calls = {"direct": 0}

    async def proxy_h(request):
        await asyncio.sleep(2)
        return httpx.Response(200, text="via-proxy")

    resp = _drive(_transport(proxy_h, calls, attempt_timeout=0.05))
    assert resp.text == "direct"
    proxy = pool._by_url["http://p:1"]
    assert (proxy.fails, proxy.inflight) == (1, 0)


def test_without_attempt_timeout_a_slow_proxy_is_waited_for():
    # Modules with slow endpoints (crt.sh, WHOIS history) don't set one
    _set_healthy(["http://p:1"])
    update_env({"PROXY_ENABLED": "true"})
    calls = {"direct": 0}

    async def proxy_h(request):
        await asyncio.sleep(0.1)
        return httpx.Response(200, text="via-proxy")

    assert _drive(_transport(proxy_h, calls)).text == "via-proxy"
    assert calls["direct"] == 0


def _socks_error():
    from socksio.exceptions import ProtocolError
    return ProtocolError("Malformed reply")


@pytest.mark.parametrize("method,make_error,retried", [
    ("GET", lambda r: httpx.ReadError("reset", request=r), True),   # no body: safe to resend
    ("POST", lambda r: _socks_error(), True),                       # SOCKS handshake: nothing sent yet
    ("GET", lambda r: _socks_error(), True),
    ("POST", lambda r: httpx.ReadError("reset", request=r), False),  # body may be sent: not resent
])
def test_which_proxy_errors_are_retried(method, make_error, retried):
    _set_healthy(["http://p:1"])
    update_env({"PROXY_ENABLED": "true"})
    calls = {"direct": 0}

    def proxy_h(request):
        raise make_error(request)

    transport = _transport(proxy_h, calls)
    if retried:
        assert _drive(transport, method).text == "direct"
    else:
        with pytest.raises(httpx.ReadError):
            _drive(transport, method)
        assert calls["direct"] == 0
    assert pool._by_url["http://p:1"].fails == 1


def test_caller_deadline_counts_as_a_proxy_failure():
    # The username module cancels a check after 10s; the slow proxy must be marked
    _set_healthy(["http://p:1"])
    update_env({"PROXY_ENABLED": "true"})

    async def proxy_h(request):
        await asyncio.sleep(2)
        return httpx.Response(200)

    transport = _transport(proxy_h, {"direct": 0})

    async def run():
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(client.get("http://example.test/"), 0.05)
    asyncio.run(run())
    proxy = pool._by_url["http://p:1"]
    assert (proxy.fails, proxy.inflight) == (1, 0)


def test_proxy_settings_save_and_load(client, monkeypatch):
    monkeypatch.setattr(pool, "trigger_refresh", lambda: None)

    bad = client.post("/api/proxies", json={
        "proxies": "not-a-proxy", "enabled": True, "fetch_public": False})
    assert bad.status_code == 400

    ok = client.post("/api/proxies", json={
        "proxies": "1.2.3.4:8080\nsocks5://5.6.7.8:1080\n# comment",
        "enabled": True, "fetch_public": False})
    assert ok.status_code == 200 and ok.json()["saved"] == 2

    got = client.get("/api/proxies").json()
    assert "1.2.3.4:8080" in got["proxies"]
    assert got["enabled"] is True and got["fetch_public"] is False
