"""Username search against a local test server: found, not found, redirects, POST bodies."""
import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


class _Site(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, body):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        user = self.path.rsplit("/", 1)[-1]
        if self.path.startswith("/found/"):
            return self._send(200, f"{user} Followers")
        if self.path.startswith("/redir/"):
            self.send_response(302)
            self.send_header("Location", "/home")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self._send(404, "not found")

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
        self._send(200 if "someuser" in body else 404, "exists" if "someuser" in body else "nope")


@pytest.fixture(scope="module")
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Site)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_search_results(server):
    from services.username_service import StreamingUsernameSearchService
    sites = [
        {"name": "Found", "uri_check": server + "/found/{account}", "e_code": 200, "e_string": "Followers",
         "m_code": 404, "m_string": "not found"},
        {"name": "Missing", "uri_check": server + "/missing/{account}", "e_code": 200, "e_string": "Followers",
         "m_code": 404, "m_string": "not found"},
        {"name": "Redirect", "uri_check": server + "/redir/{account}", "e_code": 200, "e_string": "Followers",
         "m_code": 302, "m_string": "x"},
        {"name": "JsonPost", "uri_check": server + "/j", "post_body": '{"u": "{account}"}',
         "headers": {"Content-Type": "application/json"}, "e_code": 200, "e_string": "exists",
         "m_code": 404, "m_string": "nope"},
        {"name": "Down", "uri_check": "http://127.0.0.1:1/{account}", "e_code": 200, "e_string": "x",
         "m_code": 404, "m_string": "x"},
    ]
    service = StreamingUsernameSearchService(timeout_seconds=2, connect_timeout_seconds=1, stream_delay=0)
    service.get_metadata = lambda: {"sites": sites}

    async def run():
        return [e async for e in service.stream_search("someuser")]

    events = asyncio.run(run())
    results = {e.data["site_name"]: e.data["status"] for e in events if e.event_type.value == "site_result"}
    assert results == {"Found": "found", "Missing": "not_found", "Redirect": "not_found",
                       "JsonPost": "found", "Down": "error"}
    done = events[-1].data
    assert (done["total_found"], done["total_checked"]) == (2, 5)
