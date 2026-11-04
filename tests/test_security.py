"""Requests from other sites, login, response headers, settings and file paths."""
from pathlib import Path

import pytest
from starlette.routing import WebSocketRoute

OTHER_SITES = ["cross-site", "same-site"]


@pytest.mark.parametrize("site", OTHER_SITES)
def test_other_sites_cannot_call_the_api(client, site):
    headers = {"Sec-Fetch-Site": site}
    assert client.get("/api/investigations/", headers=headers).status_code == 403
    assert client.get("/funstat/users/1/messages/all", headers=headers).status_code == 403
    assert client.post("/api/settings/update", json={}, headers=headers).status_code == 403
    assert client.post("/login", json={"email": "a", "password": "b"}, headers=headers).status_code == 403


@pytest.mark.parametrize("site", OTHER_SITES)
def test_other_sites_can_still_link_to_pages(client, site):
    assert client.get("/dashboard", headers={"Sec-Fetch-Site": site}).status_code == 200


@pytest.mark.parametrize("site", ["same-origin", "none", None])
def test_own_pages_and_scripts_can_call_the_api(client, site):
    headers = {"Sec-Fetch-Site": site} if site else {}
    assert client.get("/api/investigations/", headers=headers).status_code == 200


def test_api_requires_login(anon):
    assert anon.get("/api/investigations/").status_code == 401
    assert anon.get("/dashboard", follow_redirects=False).status_code in (302, 307)


def test_no_websocket_routes(app):
    # The HTTP middleware never sees WebSockets, so a WebSocket route would skip the login check
    assert not [r.path for r in app.routes if isinstance(r, WebSocketRoute)]


def test_security_headers(client):
    page = client.get("/dashboard")
    assert page.headers["x-frame-options"] == "DENY"
    assert page.headers["x-content-type-options"] == "nosniff"
    api = client.get("/api/investigations/")
    assert "sandbox" in api.headers["content-security-policy"]


def test_settings_reject_line_breaks(client):
    before = Path(".env").read_text()
    for value in ["abc\nROOT_PASSWORD=x", "abc\rJWT_SECRET=x"]:
        response = client.post("/api/settings/update", json={"SERPAPI_KEY": value})
        assert response.status_code == 400 and "line breaks" in response.json()["detail"]
    assert Path(".env").read_text() == before


def test_settings_save_normal_values(client):
    assert client.post("/api/settings/update", json={"SERPAPI_KEY": "abc123"}).status_code == 200
    assert "SERPAPI_KEY=abc123" in Path(".env").read_text()


def test_settings_only_editable_keys(client):
    assert client.post("/api/settings/update", json={"ROOT_PASSWORD": "x"}).status_code == 400


def test_reports_stay_inside_reports_folder(client):
    Path("reports").mkdir(exist_ok=True)
    Path("reports_x").mkdir(exist_ok=True)
    Path("reports_x/leak.txt").write_text("secret")
    for path in ["/reports/..%2freports_x%2fleak.txt", "/reports/..%2f.env", "/reports/%2e%2e/reports_x/leak.txt"]:
        response = client.get(path)
        assert response.status_code in (400, 403, 404)
        assert b"secret" not in response.content and b"JWT" not in response.content


def test_telegram_status_without_keys(client):
    assert client.get("/auth/tg/status").json() == {"authorized": False, "configured": False}


@pytest.fixture
def behind_local_proxy(app):
    """The app as uvicorn serves it from a local connection: X-Forwarded-For is applied."""
    import main
    from fastapi.testclient import TestClient
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
    main.framework.failed_logins.clear()
    yield TestClient(ProxyHeadersMiddleware(app, trusted_hosts="*"))
    main.framework.failed_logins.clear()


def _failed_login(client, forwarded_for):
    return client.post("/login", json={"email": "x@x.com", "password": "x"},
                       headers={"X-Forwarded-For": forwarded_for}).status_code


def test_login_limit_ignores_forwarded_for(behind_local_proxy):
    codes = [_failed_login(behind_local_proxy, f"192.0.2.{i}") for i in range(7)]
    assert codes == [401] * 5 + [429] * 2


def test_login_limit_uses_forwarded_for_when_trusted(behind_local_proxy, monkeypatch):
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "true")
    assert [_failed_login(behind_local_proxy, "192.0.2.50") for _ in range(6)] == [401] * 5 + [429]
    assert _failed_login(behind_local_proxy, "192.0.2.77") == 401


def _token(app, **delta):
    import jwt
    from datetime import datetime, timedelta, timezone
    from auth.auth_handler import AuthHandler
    secret = AuthHandler().secret
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": "test@example.com", "iat": now, "exp": now + timedelta(**delta)}, secret, algorithm="HS256")


def test_login_page_sends_a_logged_in_user_to_the_dashboard(app):
    from fastapi.testclient import TestClient
    client = TestClient(app, follow_redirects=False, cookies={"access_token": _token(app, hours=1)})
    response = client.get("/")
    assert response.status_code == 307 and response.headers["location"] == "/dashboard"


@pytest.mark.parametrize("cookie", [None, "expired", "not-a-token", "forged"])
def test_login_page_stays_without_a_live_token(app, cookie):
    import jwt
    from fastapi.testclient import TestClient
    value = {None: None, "expired": _token(app, seconds=-5), "not-a-token": "abc",
             "forged": jwt.encode({"sub": "x", "exp": 9999999999}, "wrong-secret", algorithm="HS256")}[cookie]
    client = TestClient(app, follow_redirects=False, cookies={"access_token": value} if value else None)
    assert client.get("/").status_code == 200
