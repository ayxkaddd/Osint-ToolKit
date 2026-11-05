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


# ---- pages in other encodings, blocks, and profile data from pages socid_extractor doesn't know ----

class _Pages(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, data: bytes, content_type="text/html; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        import json as _json
        kind, user = self.path.strip("/").split("/", 1)
        if kind == "cp1251":   # charset in the header
            return self._send(200, f"<p>Профиль {user}</p>".encode("cp1251"), "text/html; charset=windows-1251")
        if kind == "cp1251meta":   # charset only in the page
            return self._send(200, f'<meta charset="windows-1251"><p>Профиль {user}</p>'.encode("cp1251"), "text/html")
        if kind == "cf":
            return self._send(403, b"<title>Just a moment...</title><script src='/cdn-cgi/challenge-platform/x'></script>")
        if kind == "busy":
            return self._send(429, b"slow down")
        if kind == "api":
            body = {"ok": True, "data": {"user": {
                "username": user, "name": "Some Person", "bio": "Hello  world", "followers": 12, "verified": False,
                "avatar_url": "https://img.test/a.png", "html_bio": "<b>hi</b>", "csrf_token": "x" * 40,
                "settings": {"theme": "dark"}, "posts": [{"id": i, "text": "post"} for i in range(500)],
                "stats": {"likes": 7}, "tags": ["osint", "test"]}}}
            return self._send(200, _json.dumps(body).encode(), "application/json")
        if kind == "inline":   # a found page whose only JSON is the app config
            return self._send(200, f'<p>{user} Followers</p><script>window.cfg = {{"theme": "dark", "flags": {{"a": 1}}}}</script>'.encode())
        if kind == "ld":
            person = {"@context": "https://schema.org", "@type": "ProfilePage", "mainEntity": {
                "@type": "Person", "name": "LD Person", "alternateName": user, "description": "About me",
                "image": "https://img.test/p.jpg", "sameAs": ["https://x.test/me", "https://y.test/me"]}}
            return self._send(200, f'<p>{user} Followers</p><script type="application/ld+json">{_json.dumps(person)}</script>'.encode())
        if kind == "huge":
            return self._send(200, f"<p>{user} Followers</p>".encode() + b"x" * (5 * 1024 * 1024))
        return self._send(404, b"not found")


@pytest.fixture(scope="module")
def pages():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Pages)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _run(pages, entries):
    from services.username_service import StreamingUsernameSearchService
    sites = [{"name": name, "uri_check": f"{pages}/{path}/{{account}}", "e_code": 200, "e_string": marker,
              "m_code": 404, "m_string": "not found"} for name, path, marker in entries]
    service = StreamingUsernameSearchService(timeout_seconds=10, connect_timeout_seconds=2, stream_delay=0)
    service.get_metadata = lambda: {"sites": sites}

    async def run():
        return [e async for e in service.stream_search("someuser", extract_profile=True)]
    events = asyncio.run(run())
    results = {e.data["site_name"]: e.data for e in events if e.event_type.value == "site_result"}
    profiles = {e.data["site_name"]: e.data["profile_data"] for e in events if e.event_type.value == "profile_extracted"}
    return results, profiles


def test_pages_in_other_encodings_are_matched(pages):
    results, _ = _run(pages, [("Header charset", "cp1251", "Профиль"), ("Meta charset", "cp1251meta", "Профиль")])
    assert {k: v["status"] for k, v in results.items()} == {"Header charset": "found", "Meta charset": "found"}


def test_blocks_and_rate_limits_say_why(pages):
    results, _ = _run(pages, [("Challenge", "cf", "Followers"), ("Busy", "busy", "Followers")])
    assert results["Challenge"]["status"] == "error" and "Cloudflare" in results["Challenge"]["error_message"]
    assert results["Busy"]["status"] == "rate_limited" and "429" in results["Busy"]["error_message"]


def test_profile_from_a_json_answer_is_the_account_and_small(pages):
    _, profiles = _run(pages, [("Api", "api", "someuser")])
    profile = profiles["Api"]
    assert profile["username"] == "someuser" and profile["name"] == "Some Person" and profile["bio"] == "Hello world"
    assert (profile["followers"], profile["verified"], profile["likes"], profile["tags"]) == ("12", "no", "7", "osint, test")
    assert not {"html_bio", "csrf_token", "theme", "posts", "ok"} & profile.keys() and len(profile) <= 40


def test_no_profile_is_made_up_from_page_scripts(pages):
    results, profiles = _run(pages, [("Inline", "inline", "Followers")])
    assert results["Inline"]["status"] == "found" and "Inline" not in profiles


def test_profile_from_the_page_own_profile_data(pages):
    _, profiles = _run(pages, [("Ld", "ld", "Followers")])
    assert profiles["Ld"]["name"] == "LD Person" and profiles["Ld"]["alternateName"] == "someuser"
    assert profiles["Ld"]["sameAs"] == "https://x.test/me, https://y.test/me"
    assert "JSON-LD" in profiles["Ld"]["extracted_from"]


def test_huge_pages_are_read_only_in_part(pages):
    from services import username_service
    results, _ = _run(pages, [("Huge", "huge", "Followers")])
    assert results["Huge"]["status"] == "found" and username_service.MAX_BODY_BYTES < 5 * 1024 * 1024
