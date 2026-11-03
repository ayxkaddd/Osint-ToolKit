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
