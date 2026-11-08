"""Email provider checks (services/mailbox_service.py): how each provider's answer is read,
that an answer that can't be read is never "not registered", the mail-server check, the
Gmail check with the GHunt session (only when allowed, never through a proxy), and how the
results are streamed, saved and offered as pivots. No network: canned answers only."""
import asyncio
import base64
import hashlib
import json
from typing import Any

import httpx
import pytest

from services import mailbox_service as m
from utils.browser_client import BrowserResponse
from utils.config import update_env


# ---------------------------------------------------------------------------
# A stand-in for BrowserClient: answers by URL, records what was asked
# ---------------------------------------------------------------------------

def resp(status=200, body: Any = "", content_type="application/json"):
    content = body if isinstance(body, bytes) else (json.dumps(body) if not isinstance(body, str) else body).encode()
    return BrowserResponse(status_code=status, headers=httpx.Headers({"content-type": content_type}), content=content)


class FakeHttp:
    def __init__(self, routes):
        self.routes = routes   # [(url substring, response or callable(method, url, kwargs))]
        self.calls = []

    async def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        for part, answer in self.routes:
            if part in url:
                return answer(method, url, kwargs) if callable(answer) else answer
        raise AssertionError(f"unexpected request {method} {url}")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None


@pytest.fixture
def http(monkeypatch):
    """The fake serves the shared client and the sticky clients the checks open themselves."""
    fake = FakeHttp([])
    monkeypatch.setattr(m, "BrowserClient", lambda *a, **k: fake)
    monkeypatch.setattr(m, "BURST_GAP", 0)
    return fake


def run(coro):
    return asyncio.run(coro)


def statuses(results):
    return {r.email: r.status for r in results}


# ---------------------------------------------------------------------------
# Reading each provider's answer
# ---------------------------------------------------------------------------

def test_microsoft_found_missing_and_throttled(http):
    def answer(method, url, kwargs):
        email = kwargs["json"]["Username"]
        if email.endswith("outlook.com"):
            return resp(body={"IfExistsResult": 5, "ThrottleStatus": 0})
        if email.endswith("hotmail.com"):
            return resp(body={"IfExistsResult": 1, "ThrottleStatus": 0})
        if email.endswith("live.com"):
            return resp(body={"IfExistsResult": 1, "ThrottleStatus": 1})   # throttled: can't trust it
        return resp(body={"IfExistsResult": 4})
    http.routes = [("GetCredentialType", answer)]
    got = statuses(run(m.check_microsoft("bob", http)))
    assert got == {"bob@outlook.com": "found", "bob@hotmail.com": "not_found",
                   "bob@live.com": "error", "bob@msn.com": "error"}


def test_mailru_reads_exists_and_a_block_is_an_error(http):
    def answer(method, url, kwargs):
        email = kwargs["data"]["email"]
        if email.endswith("@mail.ru"):
            return resp(body={"body": {"exists": True}})
        if email.endswith("@bk.ru"):
            return resp(403, "<title>Just a moment...</title>", "text/html")
        return resp(body={"body": {"exists": False}})
    http.routes = [("user/exists", answer)]
    got = statuses(run(m.check_mailru("bob", http)))
    assert got["bob@mail.ru"] == "found" and got["bob@bk.ru"] == "error" and got["bob@inbox.ru"] == "not_found"


def test_rambler_free_name_comes_back_as_an_error_object(http):
    def answer(method, url, kwargs):
        realm = kwargs["json"]["params"][0]["realm"]
        if realm == "rambler.ru":
            return resp(body={"result": {"profile": {"status": "exist"}, "status": "OK"}})
        if realm == "lenta.ru":
            return resp(body={"result": {"error": {"errno": -2000, "strerror": "user not exist"}, "status": "ERROR"}})
        return resp(body={"result": {"error": {"strerror": "Rate limit exceed"}, "status": "ERROR"}})
    http.routes = [("jsonrpc", answer)]
    got = statuses(run(m.check_rambler("bob", http)))
    assert got["bob@rambler.ru"] == "found" and got["bob@lenta.ru"] == "not_found" and got["bob@ro.ru"] == "error"


SIGNUP_PAGE = ('<input type="hidden" name="crumb" value="c1"><input name="acrumb" value="a1">'
               '<input type="hidden" name="sessionIndex" value="QQ--">')


@pytest.mark.parametrize("error_id,expected", [
    ("IDENTIFIER_EXISTS", "found"),
    ("IDENTIFIER_NOT_AVAILABLE", "found"),
    (None, "not_found"),
    ("RESERVED_WORD_PRESENT", "skipped"),
])
def test_yahoo_reads_the_signup_validation(http, error_id, expected):
    validation = {"fields": {"userId": {"error": {"id": error_id}} if error_id else {}}}
    http.routes = [("validate", resp(body=validation)), ("account/create", resp(200, SIGNUP_PAGE, "text/html"))]
    [result] = run(m.check_yahoo("bobsmith", http))
    assert result.status == expected
    sent = http.calls[-1][2]["data"]
    assert (sent["crumb"], sent["acrumb"], sent["userId"], sent["yidDomain"]) == ("c1", "a1", "bobsmith", "yahoo.com")


def test_yahoo_without_tokens_is_an_error(http):
    http.routes = [("account/create", resp(200, "<html>new page</html>", "text/html"))]
    with pytest.raises(m.CheckError):
        run(m.check_yahoo("bobsmith", http))


@pytest.mark.parametrize("answer,expected", [
    ({"status": "success", "result": {"available": 0, "reason": "username_taken"}}, "found"),
    ({"status": "success", "result": {"available": 1, "reason": None}}, "not_found"),
])
def test_runbox(http, answer, expected):
    http.routes = [("username_available", resp(body=answer))]
    assert run(m.check_runbox("bob", http))[0].status == expected


def test_eclipso_word_filter_is_not_taken_for_an_account(http):
    # "admin" is refused because of the word, not because someone has it
    http.routes = [("checkAddressAvailability", resp(200, "<available>0</available>", "text/xml"))]
    results = run(m.check_eclipso("admin", http))
    assert {r.status for r in results} == {"skipped"}


def test_eclipso_taken_and_free(http):
    def answer(method, url, kwargs):
        return resp(200, "<available>0</available>" if "bob%40eclipso.eu" in url else "<available>1</available>")
    http.routes = [("checkAddressAvailability", answer)]
    got = statuses(run(m.check_eclipso("bob", http)))
    assert got["bob@eclipso.eu"] == "found" and got["bob@eclipso.de"] == "not_found"


@pytest.mark.parametrize("body,expected", [
    ('{"error": "unavailable_username"}', "found"),
    ('{"error": "invalid_code"}', "not_found"),
])
def test_duck(http, body, expected):
    http.routes = [("quack.duckduckgo.com", resp(400, body))]
    assert run(m.check_duck("bob", http))[0].status == expected
    assert http.calls[0][2]["headers"]["Content-Type"].startswith("multipart/form-data; boundary=")


HTTP_PROVIDERS = [p for p in m.PROVIDERS if p.id not in ("gmail", "yandex", "mailde", "proton", "icloud")]


@pytest.mark.parametrize("provider", HTTP_PROVIDERS, ids=lambda p: p.id)
@pytest.mark.parametrize("answer", [
    resp(503, "<html>maintenance</html>", "text/html"),
    resp(200, "<title>Just a moment...</title><script src='/cdn-cgi/challenge-platform/'></script>", "text/html"),
    resp(200, "surprise", "text/plain"),
], ids=["server-error", "bot-check", "garbage"])
def test_an_unreadable_answer_is_never_not_registered(http, provider, answer):
    http.routes = [("", answer)]
    results = run(m._run_provider(provider, "bobsmith", http))
    assert results and all(r.status in ("error", "skipped") for r in results), [r.to_dict() for r in results]


def test_names_a_provider_does_not_allow_are_skipped(http):
    gmail = m.PROVIDERS_BY_ID["gmail"]
    [result] = run(m._run_provider(gmail, "bob_smith", http))   # no underscores at Gmail
    assert result.status == "skipped" and http.calls == []


def test_gravatar_proves_an_address_apple_and_proton_hide(http):
    digest = hashlib.md5(b"bob@icloud.com").hexdigest()
    http.routes = [(digest, resp(body={"display_name": "Bob", "avatar_url": "https://gravatar.test/a.png"})),
                   ("api.gravatar.com", resp(404, ""))]
    [icloud] = run(m._run_provider(m.PROVIDERS_BY_ID["icloud"], "bob", http))
    assert icloud.status == "found" and icloud.details["name"] == "Bob" and "gravatar_only" not in icloud.details
    [proton] = run(m._run_provider(m.PROVIDERS_BY_ID["proton"], "bob", http))
    assert proton.status == "skipped" and "no longer" in proton.reason


# ---------------------------------------------------------------------------
# Mail servers: RCPT TO, nothing sent
# ---------------------------------------------------------------------------

def _fake_smtp(rcpt_reply: bytes):
    async def handle(reader, writer):
        writer.write(b"220 mx.test ESMTP\r\n")
        while line := await reader.readline():
            cmd = line.decode().upper()
            if cmd.startswith(("EHLO", "HELO")):
                writer.write(b"250-mx.test\r\n250 PIPELINING\r\n")
            elif cmd.startswith("MAIL FROM"):
                writer.write(b"250 OK\r\n")
            elif cmd.startswith("RCPT TO"):
                writer.write(rcpt_reply)
            elif cmd.startswith("DATA"):
                raise AssertionError("no mail may be sent")
            elif cmd.startswith("QUIT"):
                writer.write(b"221 bye\r\n")
                break
            await writer.drain()
        writer.close()
    return handle


@pytest.mark.parametrize("reply,expected", [
    (b"250 2.1.5 OK\r\n", True),
    (b"550-5.1.1 The email account that you tried to reach does not exist\r\n550 5.1.1 more\r\n", False),
])
def test_smtp_rcpt(monkeypatch, reply, expected):
    async def scenario():
        server = await asyncio.start_server(_fake_smtp(reply), "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        _patch_mx_and_port(monkeypatch, port)
        async with server:
            return await m.smtp_mailbox_exists("bob@mx.test")
    assert run(scenario()) is expected


def test_smtp_block_is_an_error_not_a_missing_mailbox(monkeypatch):
    async def scenario():
        server = await asyncio.start_server(
            _fake_smtp(b"550 5.7.1 Service unavailable; client host blocked using Spamhaus\r\n"), "127.0.0.1", 0)
        _patch_mx_and_port(monkeypatch, server.sockets[0].getsockname()[1])
        async with server:
            await m.smtp_mailbox_exists("bob@mx.test")
    with pytest.raises(m.CheckError, match="5.7.1"):
        run(scenario())


def test_smtp_port_25_blocked(monkeypatch):
    _patch_mx_and_port(monkeypatch, 1)   # nothing listens there
    with pytest.raises(m.CheckError, match="Port 25"):
        run(m.smtp_mailbox_exists("bob@mx.test"))


def _patch_mx_and_port(monkeypatch, port):
    import dns.asyncresolver

    class Mx:
        preference, exchange = 10, "127.0.0.1."

    async def resolve(domain, rtype, lifetime=None):
        return [Mx()]
    monkeypatch.setattr(dns.asyncresolver, "resolve", resolve)
    real_open = asyncio.open_connection
    monkeypatch.setattr(m.asyncio, "open_connection", lambda host, _port: real_open(host, port))


# ---------------------------------------------------------------------------
# Gmail: the GHunt session, only once allowed, always direct
# ---------------------------------------------------------------------------

@pytest.fixture
def ghunt_session(tmp_path, monkeypatch):
    # Put conftest's stand-in path back afterwards: without the setting the default would be
    # the operator's real session (~/.malfrats/ghunt/creds.m)
    from utils.config import get_setting
    previous = get_setting(m.GHUNT_CREDS_KEY)
    assert previous and ".malfrats" not in previous
    path = tmp_path / "creds.m"
    path.write_text(base64.b64encode(json.dumps({
        "cookies": {"SAPISID": "sapisid-value", "SID": "sid-value"},
        "osids": {}, "android": {"master_token": "never-read", "authorization_tokens": {}}}).encode()).decode())
    update_env({m.GHUNT_CREDS_KEY: str(path)})
    yield path
    update_env({m.GHUNT_CREDS_KEY: previous, m.GMAIL_PERMISSION_KEY: None})


def _google(monkeypatch, handler, seen):
    real = httpx.AsyncClient

    class Client(real):
        def __init__(self, **kwargs):
            seen.update(kwargs)
            super().__init__(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(m.httpx, "AsyncClient", Client)


def test_gmail_waits_for_permission_and_never_reads_the_session(ghunt_session, monkeypatch):
    update_env({m.GMAIL_PERMISSION_KEY: None})
    monkeypatch.setattr(m, "_google_cookies", lambda: pytest.fail("the session was read without permission"))
    result = run(m.google_account("bob.smith@gmail.com"))
    assert result.status == "skipped" and result.details == {"needs_permission": True}


def test_gmail_found_with_the_session(ghunt_session, monkeypatch):
    update_env({m.GMAIL_PERMISSION_KEY: "true"})
    update_env({"PROXY_ENABLED": "true"})   # even with proxies on, Google is asked directly
    seen, asked = {}, {}

    def handler(request):
        asked["url"], asked["headers"] = request.url, request.headers
        return httpx.Response(200, json={"people": {"x": {"personId": "123", "metadata": {"identityInfo": {
            "sourceIds": [{"container": "PROFILE", "id": "109876543210987654321"}]}}}}})
    _google(monkeypatch, handler, seen)
    try:
        result = run(m.google_account("bob.smith@gmail.com"))
    finally:
        update_env({"PROXY_ENABLED": "false"})
    assert result.status == "found" and result.details == {"gaia_id": "109876543210987654321"}
    assert asked["url"].host == "people-pa.clients6.google.com" and asked["url"].params["id"] == "bob.smith@gmail.com"
    auth = asked["headers"]["authorization"]
    ts, digest = auth.removeprefix("SAPISIDHASH ").split("_")
    assert digest == hashlib.sha1(f"{ts} sapisid-value https://photos.google.com".encode()).hexdigest()
    assert "SAPISID=sapisid-value" in asked["headers"]["cookie"]
    assert seen["trust_env"] is False and not {"proxy", "proxies", "mounts", "transport"} & (seen.keys() - {"transport"})


@pytest.mark.parametrize("answer,status", [
    (httpx.Response(200, json={}), "not_found"),
    # known only from the operator's own contacts: not a Google account
    (httpx.Response(200, json={"people": {"x": {"metadata": {"identityInfo": {"sourceIds": [{"container": "CONTACT"}]}}}}}),
     "not_found"),
])
def test_gmail_not_found(ghunt_session, monkeypatch, answer, status):
    update_env({m.GMAIL_PERMISSION_KEY: "true"})
    _google(monkeypatch, lambda request: answer, {})
    assert run(m.google_account("bob.smith@gmail.com")).status == status


def test_gmail_expired_session_and_no_session(ghunt_session, monkeypatch):
    update_env({m.GMAIL_PERMISSION_KEY: "true"})
    _google(monkeypatch, lambda request: httpx.Response(401), {})
    with pytest.raises(m.CheckError, match="ghunt login"):
        run(m.google_account("bob.smith@gmail.com"))
    ghunt_session.unlink()
    result = run(m.google_account("bob.smith@gmail.com"))
    assert result.status == "skipped" and "ghunt login" in result.reason


# ---------------------------------------------------------------------------
# Streamed with the username search, saved, and offered as pivots
# ---------------------------------------------------------------------------

def test_stream_search_checks_mailboxes_only_when_asked(monkeypatch):
    from services import username_service as us

    async def fake_checks(username):
        yield m.MailboxResult("Microsoft", f"{username}@outlook.com", m.FOUND)
        yield m.MailboxResult("Yahoo", f"{username}@yahoo.com", m.NOT_FOUND)
    monkeypatch.setattr(us, "run_mailbox_checks", fake_checks)
    service = us.StreamingUsernameSearchService(timeout_seconds=2, connect_timeout_seconds=1, stream_delay=0)
    service.get_metadata = lambda: {"sites": []}

    async def kinds(**kw):
        return [e async for e in service.stream_search("someuser", **kw)]
    events = run(kinds(check_mailboxes=True))
    mailbox = [e.data for e in events if e.event_type == us.EventType.MAILBOX_RESULT]
    assert {d["email"]: d["status"] for d in mailbox} == {"someuser@outlook.com": "found", "someuser@yahoo.com": "not_found"}
    assert events[-1].data["mailboxes_found"] == 1
    completed = [e for e in events if e.event_type == us.EventType.MAILBOX_COMPLETED]
    assert [e.data for e in completed] == [{"found": 1}]
    plain = run(kinds())
    assert not [e for e in plain if e.event_type in (us.EventType.MAILBOX_RESULT, us.EventType.MAILBOX_STARTED)]
    assert "mailboxes_found" not in plain[-1].data


def test_saved_result_keeps_found_addresses_as_entities_only():
    from services.entities import extract_entities
    from utils.stream_reducers import reduce_username_search
    events = [
        {"event_type": "search_started", "data": {"username": "bob", "total_sites": 0}},
        {"event_type": "mailbox_result", "data": {"provider": "Microsoft", "email": "bob@outlook.com", "status": "found"}},
        {"event_type": "mailbox_result", "data": {"provider": "Microsoft", "email": "bob@hotmail.com", "status": "not_found"}},
        {"event_type": "mailbox_result", "data": {"provider": "Yandex", "email": "bob@yandex.ru", "status": "error",
                                                   "reason": "Port 25 (mail servers) is blocked on this network"}},
        {"event_type": "search_completed", "data": {"username": "bob", "total_checked": 0}},
    ]
    saved = reduce_username_search(events)
    assert saved["mailboxes"] == [{"provider": "Microsoft", "email": "bob@outlook.com", "status": "found"}]
    assert saved["mailbox_checks"]["not_found"] == [{"provider": "Microsoft", "domain": "hotmail.com"}]
    assert saved["mailbox_checks"]["error"][0]["domain"] == "yandex.ru"
    emails = {e.value for e, _ in extract_entities(saved, "username") if e.type == "email"}
    assert emails == {"bob@outlook.com"}   # an address that doesn't exist is no lead


def test_google_permission_endpoints(client):
    assert ".malfrats" not in str(m.ghunt_creds_path())   # never the real session in tests
    assert client.get("/api/username/mailboxes/status").json()["gmail_permission"] is False
    assert client.post("/api/username/mailboxes/google-permission", json={"allow": True}).json() == {"gmail_permission": True}
    status = client.get("/api/username/mailboxes/status").json()
    assert status["gmail_permission"] is True and status["ghunt_session"] is False
    assert {"gmail", "microsoft", "mailru"} <= {p["id"] for p in status["providers"]}
    client.post("/api/username/mailboxes/google-permission", json={"allow": False})
    assert client.get("/api/username/mailboxes/status").json()["gmail_permission"] is False
    assert client.get("/api/username/mailboxes/check?username=bob&provider=nope").status_code == 404
