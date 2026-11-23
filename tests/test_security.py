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


# --- First-run setup: only from this computer, or with the console's setup link ---

@pytest.fixture
def setup_pending(monkeypatch):
    """Setup not done yet; saving the admin account is faked so the test .env stays."""
    from routes import setup_routes
    monkeypatch.setattr(setup_routes, "check_setup_complete", lambda: False)
    monkeypatch.setattr(setup_routes, "save_env_config", lambda config: None)
    monkeypatch.setattr(setup_routes, "save_setup_state", lambda state: None)
    return setup_routes


ADMIN_FORM = {"email": "admin@example.com", "password": "Admin-pass1", "confirm_password": "Admin-pass1"}


def test_setup_from_another_computer_needs_the_token(app, setup_pending):
    from fastapi.testclient import TestClient
    remote = TestClient(app, client=("203.0.113.9", 5000), follow_redirects=False)
    assert remote.post("/setup/admin", data=ADMIN_FORM).status_code == 403
    page = remote.get("/setup")
    assert page.status_code == 403 and "setup link" in page.text
    assert remote.post("/setup/admin", data=ADMIN_FORM,
                       params={"token": "wrong"}).status_code == 403
    assert remote.post("/setup/admin", data=ADMIN_FORM,
                       params={"token": setup_pending.SETUP_TOKEN}).status_code == 200


def test_setup_link_moves_the_token_into_a_cookie(app, setup_pending):
    from fastapi.testclient import TestClient
    remote = TestClient(app, client=("203.0.113.9", 5000), follow_redirects=False)
    response = remote.get("/setup", params={"token": setup_pending.SETUP_TOKEN})
    assert response.status_code == 307 and response.headers["location"] == "/setup"
    assert "httponly" in response.headers["set-cookie"].lower()
    # the wizard's own requests now carry it
    assert remote.post("/setup/admin", data=ADMIN_FORM).status_code == 200


def test_setup_from_this_computer_needs_no_token(app, setup_pending):
    from fastapi.testclient import TestClient
    for host in ("127.0.0.1", "::1"):
        local = TestClient(app, client=(host, 5000))
        assert local.get("/setup").status_code == 200
        assert local.post("/setup/admin", data=ADMIN_FORM).status_code == 200


def test_setup_link_is_logged(setup_pending):
    assert f"/setup?token={setup_pending.SETUP_TOKEN}" in setup_pending.setup_link_message()


# --- Sessions: "Log out everywhere" ends every token issued before it ---

@pytest.fixture
def restore_epoch():
    yield
    from utils.config import update_env
    update_env({"SESSION_EPOCH": None})


def test_log_out_everywhere_rejects_older_tokens(app, client, restore_epoch):
    from fastapi.testclient import TestClient
    from conftest import EMAIL, PASSWORD
    other = TestClient(app)
    assert other.post("/login", json={"email": EMAIL, "password": PASSWORD}).status_code == 200
    copied = other.cookies["access_token"]
    assert other.get("/api/investigations/").status_code == 200

    assert other.post("/logout", params={"everywhere": "true"}).status_code == 200
    stolen = TestClient(app, cookies={"access_token": copied})
    assert stolen.get("/api/investigations/").status_code == 401
    assert client.get("/api/investigations/").status_code == 401  # the other browser too

    # a new login works again
    fresh = TestClient(app)
    assert fresh.post("/login", json={"email": EMAIL, "password": PASSWORD}).status_code == 200
    assert fresh.get("/api/investigations/").status_code == 200


def test_plain_logout_keeps_other_sessions(app, client):
    from fastapi.testclient import TestClient
    assert TestClient(app).post("/logout").status_code == 200
    assert client.get("/api/investigations/").status_code == 200


def test_logged_out_visitor_cannot_end_sessions(anon, client):
    assert anon.post("/logout", params={"everywhere": "true"}).status_code == 200
    assert client.get("/api/investigations/").status_code == 200


def test_tokens_from_before_epochs_still_work(app):
    from fastapi.testclient import TestClient
    old_style = _token(app, hours=1)  # no "epoch" claim
    assert TestClient(app, cookies={"access_token": old_style}).get("/api/investigations/").status_code == 200


# --- Secure cookies over HTTPS ---

def _login_cookie(app, monkeypatch, base_url="http://testserver", headers=None, **env):
    from fastapi.testclient import TestClient
    from conftest import EMAIL, PASSWORD
    import main
    main.framework.failed_logins.clear()
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    response = TestClient(app, base_url=base_url).post(
        "/login", json={"email": EMAIL, "password": PASSWORD}, headers=headers or {})
    assert response.status_code == 200
    return response.headers["set-cookie"].lower()


def test_cookie_not_secure_over_plain_http(app, monkeypatch):
    assert "secure" not in _login_cookie(app, monkeypatch)


def test_cookie_secure_over_https(app, monkeypatch):
    assert "secure" in _login_cookie(app, monkeypatch, base_url="https://testserver")


def test_cookie_secure_behind_trusted_https_proxy(app, monkeypatch):
    https = {"X-Forwarded-Proto": "https"}
    assert "secure" not in _login_cookie(app, monkeypatch, headers=https)
    assert "secure" in _login_cookie(app, monkeypatch, headers=https, TRUST_PROXY_HEADERS="true")


def test_cookie_secure_setting(app, monkeypatch):
    assert "secure" in _login_cookie(app, monkeypatch, COOKIE_SECURE="true")
