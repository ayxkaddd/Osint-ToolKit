"""The Plugins page says what enabling a plugin with renderer.js gives it."""
import shutil
from pathlib import Path

import pytest
from conftest import REPO


@pytest.fixture
def plugin_with_renderer():
    from services import plugin_loader
    folder = Path("plugins/renderer_test")
    folder.mkdir()
    shutil.copy(REPO / "plugins/crtsh/plugin.yaml", folder / "plugin.yaml")
    (folder / "renderer.js").write_text("registerPluginRenderer('renderer_test', () => null);\n")
    plugin_loader.refresh(force=True)
    yield "renderer_test"
    shutil.rmtree(folder)
    plugin_loader.refresh(force=True)


def test_review_dialog_warns_about_renderer_js(client, plugin_with_renderer):
    files = client.get(f"/api/plugins/{plugin_with_renderer}/files").json()
    assert files["plugin"]["has_renderer"] is True
    assert "JavaScript" in files["plugin"]["blocked"]  # from another source: off until reviewed
    page = client.get("/plugins").text
    assert 'id="reviewRenderer"' in page and "same access as you" in page


@pytest.fixture
def local_api():
    """A tiny JSON API on this machine; records the queries it gets."""
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    seen = []

    class Api(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            seen.append(self.path)
            body = json.dumps([{"login": "alice", "name": "Alice <b>A</b>", "email": "alice@example.test"}]).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Api)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}", seen
    server.shutdown()


def test_no_code_plugin_runs_end_to_end(client, local_api):
    """Manifest, trust, the HTTP request, templates and result items, through the API."""
    import json
    from services import plugin_loader
    url, seen = local_api
    folder = Path("plugins/local_users")
    folder.mkdir()
    (folder / "plugin.yaml").write_text(
        "name: Local users\naccepts: [username]\n"
        f"request:\n  url: {url}/users\n  query:\n    q: \"{{value}}\"\n"
        "response:\n  items: \".\"\n  title: \"{login}\"\n  subtitle: \"{name}\"\n"
        "  fields:\n    Email: email\n  entities:\n    email: email\n")
    try:
        # a local address: off until the user says it's theirs
        plugin_loader.refresh(force=True)
        assert "local network" in plugin_loader.get("local_users").blocked()
        plugin_loader.write_trust("local_users", "local")
        plugin_loader.refresh(force=True)
        response = client.post("/api/plugins/local_users/test", json={"value": "alice", "type": "username"})
        assert response.status_code == 200, response.text
        events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
        items = [e["item"] for e in events if e["event"] == "item"]
        assert seen == ["/users?q=alice"], events
        assert items and items[0]["title"] == "alice" and items[0]["subtitle"] == "Alice <b>A</b>"
        assert ["Email", "alice@example.test"] in items[0]["fields"]
        assert "alice@example.test" in json.dumps(items[0]["entities"])
    finally:
        plugin_loader.write_trust("local_users", None)
        shutil.rmtree(folder)
        plugin_loader.refresh(force=True)
