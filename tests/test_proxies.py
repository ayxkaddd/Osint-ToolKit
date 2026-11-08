"""Proxy pool parsing/health/rotation, the rotating transport's fail-over, and
the /api/proxies settings endpoints. No network: the transport is driven with
httpx.MockTransport and the pool's healthy set is set directly."""
import asyncio

import httpx
import pytest

from services.proxy_pool import Proxy, parse_proxy, pool
from utils.config import update_env
from utils.proxy_transport import RotatingProxyTransport


def _set_healthy(urls):
    pool._healthy = [Proxy(url=u) for u in urls]
    pool._by_url = {p.url: p for p in pool._healthy}
    pool._cursor = 0


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


def test_pick_rotates_round_robin():
    _set_healthy(["http://a:1", "http://b:2", "http://c:3"])
    assert [pool.pick() for _ in range(4)] == [
        "http://a:1", "http://b:2", "http://c:3", "http://a:1"]


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


def test_enabled_needs_flag_and_healthy():
    _set_healthy(["http://a:1"])
    update_env({"PROXY_ENABLED": "false"})
    assert pool.enabled() is False
    update_env({"PROXY_ENABLED": "true"})
    assert pool.enabled() is True
    _set_healthy([])
    assert pool.enabled() is False


def _drive(transport):
    async def run():
        async with httpx.AsyncClient(transport=transport) as client:
            return await client.get("http://example.test/")
    return asyncio.run(run())


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
