"""The CLI against a fake server (httpx.MockTransport): no network, no real server."""
import json
import os
import stat
from urllib.parse import parse_qs

import httpx
import pytest
from typer.testing import CliRunner

from osint_cli import client, config, follow, main
from osint_cli.main import app

INV = "11111111-2222-3333-4444-555555555555"
OTHER = "99999999-2222-3333-4444-555555555555"
TOKEN = "header.payload.signature"


def _job(job_id, name, status, result_id=None, **extra):
    return {"id": job_id, "module_name": name, "value": "a@example.test", "investigation_id": INV,
            "status": status, "result_id": result_id, **extra}


# what /api/jobs says about each job on the Nth listing: Holehe answers in one piece,
# OSINT Industries streams (its live result grows, re-sorted, before it is saved)
JOB_SCRIPTS = {
    "job-holehe": lambda n: _job("job-holehe", "Holehe", "running") if n < 2
    else _job("job-holehe", "Holehe", "done", "res-holehe", summary="2 sites"),
    "job-oi": lambda n: _job("job-oi", "OSINT Industries", "running", "res-oi", progress={"found": n}) if n < 3
    else _job("job-oi", "OSINT Industries", "done", "res-oi", summary="3 results"),
}
GITHUB = {"module": "github", "url": "https://github.com/a"}
DISCORD = {"module": "discord", "url": "https://discord.com/users/1"}
SPOTIFY = {"module": "spotify", "url": "https://open.spotify.com/user/a"}
HOLEHE = {"service_name": "holehe", "result": {"email": "a@example.test",
                                               "sites": [{"name": "twitter", "exists": True},
                                                         {"name": "instagram", "exists": False}]}}
RESULTS = {  # (result id, listing number) -> the record GET .../results/<id> answers
    ("res-oi", 1): {"running": True, "result": {"modules": [GITHUB], "completed": False}},
    ("res-oi", 2): {"running": True, "result": {"modules": [DISCORD, {**GITHUB, "name": "A"}], "completed": False}},
    ("res-oi", 3): {"result": {"modules": [DISCORD, GITHUB, SPOTIFY], "completed": True}},
    ("res-holehe", 2): HOLEHE, ("res-holehe", 3): HOLEHE,
}


class FakeServer:
    """Answers like the toolkit's API; keeps every request it got."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.current = INV
        self.expired = False
        self.started: list[str] = []   # job ids, in the order they were started
        self.polls = 0                 # job listings since the first job started

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path, method = request.url.path, request.method
        if path == "/login":
            body = json.loads(request.content)
            if body["password"] != "right":
                return httpx.Response(401, json={"detail": "Invalid credentials"})
            return httpx.Response(200, json={"success": True},
                                  headers={"set-cookie": f"access_token={TOKEN}; HttpOnly; Path=/; SameSite=lax"})
        if self.expired or f"access_token={TOKEN}" not in request.headers.get("cookie", ""):
            return httpx.Response(401, json={"detail": "Not authenticated"})
        if path == "/logout":
            return httpx.Response(200, json={"success": True})
        if path == "/api/investigations/":
            return httpx.Response(200, json={"status": "success", "count": 2, "investigations": [
                {"investigation_id": INV, "name": "Case A", "status": "active", "results_count": 2,
                 "updated_at": "2026-11-23T10:00:00"},
                {"investigation_id": OTHER, "name": "Case B", "status": "archived", "results_count": 0}]})
        if path == "/api/investigations/current":
            return httpx.Response(200, json={"status": "success", "investigation_id": self.current,
                                             "investigation": {"investigation_id": self.current, "name": "Case A"}})
        if path == "/api/investigations/set" and method == "POST":
            self.current = parse_qs(request.content.decode())["investigation_id"][0]
            return httpx.Response(200, json={"status": "success", "investigation": {"name": "Case B"}})
        if path == f"/api/investigations/{INV}":
            return httpx.Response(200, json={"status": "success", "investigation": {"investigation_id": INV, "name": "Case A"},
                                             "results": [{"result_id": "r1", "service_name": "whois", "method_name": "lookup",
                                                          "target": "example.test", "summary": "registrar X",
                                                          "children": [{"service_name": "ns", "method_name": "fingerprint",
                                                                        "target": "ns1.example.test"}]}]})
        if path == f"/api/investigations/{INV}/entities":
            entities = [{"type": "email", "label": "Email", "value": "a@example.test", "sources": [{"result_id": "r1"}]},
                        {"type": "domain", "label": "Domain", "value": "example.test", "sources": []}]
            kind = request.url.params.get("type")
            entities = [e for e in entities if not kind or e["type"] == kind]
            return httpx.Response(200, json={"total": len(entities), "types": [], "entities": entities})
        if path == f"/api/investigations/{INV}/export":
            return httpx.Response(200, content=b"PK\x03\x04zip-bytes")
        if path == "/api/lookup/detect":
            return httpx.Response(200, json={"query": request.url.params["q"], "investigation_id": self.current,
                                             "candidates": [{"type": "email", "label": "Email", "value": "a@example.test",
                                                             "modules": [{"id": "holehe", "name": "Holehe", "ready": True},
                                                                         {"id": "oi", "name": "OSINT Industries", "ready": True,
                                                                          "cost": "paid"}]}],
                                             "suggestions": []})
        if path == "/api/jobs" and method == "POST":
            body = json.loads(request.content)
            self.started.append(f"job-{body['module']}")
            return httpx.Response(200, json={"job": {"id": f"job-{body['module']}", "module_name": body["module"],
                                                     "value": body["value"], "status": "queued"}})
        if path == "/api/jobs" and self.started:
            self.polls += 1
            return httpx.Response(200, json={"jobs": [JOB_SCRIPTS[j](self.polls) for j in self.started]})
        if path.startswith(f"/api/investigations/{INV}/results/"):
            record = RESULTS.get((path.rsplit("/", 1)[1], min(self.polls, 3)))
            if record is None:
                return httpx.Response(404, json={"detail": "Result not found"})
            return httpx.Response(200, json={"status": "success", "result": record})
        if path == "/api/jobs":
            return httpx.Response(200, json={"jobs": [{"id": "job-1", "module_name": "Holehe", "value": "a@example.test",
                                                       "status": "running"}]})
        if path.startswith("/api/jobs/") and method == "DELETE":
            return httpx.Response(200, json={"status": "cancelling"})
        return httpx.Response(404, json={"detail": "Not Found"})


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("OSINT_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.delenv("OSINT_URL", raising=False)
    fake = FakeServer()
    monkeypatch.setattr(client, "transport", httpx.MockTransport(fake))
    return fake


@pytest.fixture
def logged_in(server):
    config.save(config.Config(url="http://toolkit.test:8000", token=TOKEN))
    return server


def run(*args, input=None):
    return CliRunner().invoke(app, list(args), input=input)


def test_login_stores_the_cookie_and_the_address(server):
    result = run("login", "http://toolkit.test:8000", "--email", "admin@example.test", input="right\n")
    assert result.exit_code == 0, result.output
    saved = config.load()
    assert saved.token == TOKEN and saved.url == "http://toolkit.test:8000"
    assert server.requests[0].url == "http://toolkit.test:8000/login"
    if os.name != "nt":
        assert stat.S_IMODE(config.config_path().stat().st_mode) == 0o600


def test_wrong_password(server):
    result = run("login", "http://toolkit.test:8000", "--email", "admin@example.test", input="wrong\n")
    assert result.exit_code == 1 and "Wrong email or password" in result.output
    assert config.load().token is None


def test_json_output_is_only_json(logged_in):
    result = run("list", "--json")
    assert result.exit_code == 0
    assert [i["name"] for i in json.loads(result.stdout)["investigations"]] == ["Case A", "Case B"]


def test_requests_carry_the_login_cookie(logged_in):
    run("list")
    assert all(f"access_token={TOKEN}" in r.headers["cookie"] for r in logged_in.requests)
    assert all(r.url.host == "toolkit.test" for r in logged_in.requests)


def test_expired_session_says_to_log_in(logged_in):
    logged_in.expired = True
    result = run("list")
    assert result.exit_code == 1
    assert "Session expired, run `osint login`" in result.output


def test_not_logged_in(server):
    result = run("list")
    assert result.exit_code == 1 and "osint login" in result.output and not server.requests


def test_lookup_starts_one_job_per_module(logged_in):
    result = run("lookup", "a@example.test", "-m", "holehe,oi", "--detach", "--json")
    assert result.exit_code == 0, result.output
    jobs = [json.loads(r.content) for r in logged_in.requests if r.url.path == "/api/jobs" and r.method == "POST"]
    assert jobs == [{"module": "holehe", "type": "email", "value": "a@example.test"},
                    {"module": "oi", "type": "email", "value": "a@example.test"}]
    assert [j["id"] for j in json.loads(result.stdout)] == ["job-holehe", "job-oi"]


def test_lookup_without_modules_starts_nothing(logged_in):
    result = run("lookup", "a@example.test")
    assert result.exit_code == 0 and "holehe" in result.output and "-m" in result.output
    assert not [r for r in logged_in.requests if r.url.path == "/api/jobs"]


def test_lookup_with_a_module_that_does_not_fit(logged_in):
    result = run("lookup", "a@example.test", "-m", "whois")
    assert result.exit_code == 1 and "doesn't look up this value" in result.output


def test_use_takes_the_start_of_an_id_and_warns_about_the_browser(logged_in):
    result = run("use", "9999")
    assert result.exit_code == 0, result.output
    assert logged_in.current == OTHER
    assert "web app" in result.output


def test_show_draws_follow_ups_under_their_result(logged_in):
    result = run("show")
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    whois = next(i for i, line in enumerate(lines) if "whois" in line)
    assert "ns1.example.test" in lines[whois + 1]


def test_entities_by_type(logged_in):
    result = run("entities", "--type", "email", "--json")
    assert [e["value"] for e in json.loads(result.stdout)["entities"]] == ["a@example.test"]


def test_export_writes_the_zip(logged_in, tmp_path):
    target = tmp_path / "case.zip"
    result = run("export", "-o", str(target))
    assert result.exit_code == 0, result.output
    assert target.read_bytes().startswith(b"PK")
    export = next(r for r in logged_in.requests if r.url.path.endswith("/export"))
    assert export.url.params["format"] == "zip"


def test_jobs_and_cancel(logged_in):
    assert "Holehe" in run("jobs").output
    result = run("cancel", "job-1")
    assert result.exit_code == 0
    assert any(r.method == "DELETE" and r.url.path == "/api/jobs/job-1" for r in logged_in.requests)


def test_logout_forgets_the_token(logged_in):
    result = run("logout", "--everywhere")
    assert result.exit_code == 0
    assert config.load().token is None
    assert any(r.url.path == "/logout" and r.url.params.get("everywhere") == "true" for r in logged_in.requests)


def test_server_address_from_option_and_environment(logged_in, monkeypatch):
    monkeypatch.setenv("OSINT_URL", "http://from-env.test:9000")
    run("list")
    assert logged_in.requests[-1].url.host == "from-env.test"
    run("--url", "http://from-option.test", "list")
    assert logged_in.requests[-1].url.host == "from-option.test"


# --- Consoles that can't show every character (a pipe on Windows is cp1252) ---

def _cp1252(*args, **env):
    import subprocess
    import sys
    return subprocess.run([sys.executable, "-c", "from osint_cli.main import app; app()", *args],
                          capture_output=True, env={**os.environ, "PYTHONIOENCODING": "cp1252", **env}, timeout=60)


def test_help_on_a_cp1252_console():
    result = _cp1252("--help")
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert b"list" in result.stdout and b"Traceback" not in result.stderr


def test_names_a_console_cannot_show_do_not_stop_the_command(tmp_path):
    import io
    from osint_cli import main
    stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    main.sys.stdout, saved = stream, main.sys.stdout
    try:
        main._never_fail_on_characters()
        print("Справа ● 🔍", file=stream)
        main.print_json({"name": "Справа"})
        stream.flush()
    finally:
        main.sys.stdout = saved
    text = stream.buffer.getvalue().decode("cp1252")
    assert "?" in text
    assert json.loads(text[text.index("{"):]) == {"name": "Справа"}  # escaped, nothing lost


@pytest.fixture
def no_waiting(monkeypatch):
    monkeypatch.setattr(follow, "POLL_SECONDS", 0)


def test_lookup_waits_and_shows_each_answer(logged_in, no_waiting):
    result = run("lookup", "a@example.test", "-m", "holehe,oi")
    assert result.exit_code == 0, result.output
    out = result.output
    # the streamed finds, each once, in the order they arrived (not the server's sort)
    assert [out.count(url) for url in ("github.com/a", "discord.com/users/1", "open.spotify.com/user/a")] == [1, 1, 1]
    assert out.index("github.com/a") < out.index("discord.com") < out.index("spotify.com")
    assert "OSINT Industries done: 3 results" in out
    # the plain answer, every field, once it's done
    assert "twitter" in out and "instagram" in out and "exists: no" in out
    assert "Holehe done: 2 sites" in out
    assert out.index("Holehe done") < out.index("spotify.com")   # Holehe finished first


def test_lookup_json_waits_for_the_saved_results(logged_in, no_waiting):
    result = run("lookup", "a@example.test", "-m", "holehe,oi", "--json")
    assert result.exit_code == 0, result.output
    done = json.loads(result.stdout)
    assert [d["job"]["status"] for d in done] == ["done", "done"]
    assert {d["job"]["id"]: d["result"]["result"] for d in done}["job-oi"]["modules"][2] == SPOTIFY


def test_lookup_asks_which_modules_at_a_terminal(logged_in, no_waiting, monkeypatch):
    asked = []
    monkeypatch.setattr(main, "interactive", lambda: True)
    monkeypatch.setattr(main, "pick_modules", lambda candidates: asked.append(candidates) or [(candidates[0], "holehe")])
    result = run("lookup", "a@example.test")
    assert result.exit_code == 0, result.output
    assert asked and [m["id"] for m in asked[0][0]["modules"]] == ["holehe", "oi"]
    assert logged_in.started == ["job-holehe"] and "Holehe done" in result.output


def test_lookup_picking_nothing_starts_nothing(logged_in, monkeypatch):
    monkeypatch.setattr(main, "interactive", lambda: True)
    monkeypatch.setattr(main, "pick_modules", lambda candidates: [])
    result = run("lookup", "a@example.test")
    assert result.exit_code == 0 and "Nothing started" in result.output and not logged_in.started


def test_the_picker_shows_costs_and_what_needs_setup(monkeypatch):
    import questionary
    shown = {}

    class Question:
        def ask(self):
            return [shown["choices"][1].value]

    def checkbox(message, choices, **kwargs):
        shown["choices"] = choices
        return Question()

    monkeypatch.setattr(questionary, "checkbox", checkbox)
    reading = {"type": "email", "value": "a@example.test", "modules": [
        {"id": "oi", "name": "OSINT Industries", "ready": True, "cost": "paid", "cost_note": "credits",
         "previous": [{"result_id": "r0"}]},
        {"id": "holehe", "name": "Holehe", "ready": True, "cost": "free"},
        {"id": "hunter", "name": "Hunter", "ready": False, "problems": ["HUNTER_API_KEY is not set"],
         "setup": [{"problem": "HUNTER_API_KEY is not set", "action": "Add the Hunter API key"}]},
        {"id": "old", "name": "Older server", "ready": False, "problems": ["Something is missing"]}]}
    assert main.pick_modules([reading]) == [(reading, "holehe")]
    paid, free, unready, older = shown["choices"]
    assert ("fg:ansiyellow", "  paid (credits)") in paid.title and "looked up before" in paid.title[-1][1]
    assert len(free.title) == 1 and not free.disabled
    assert unready.disabled == "needs setup: Add the Hunter API key"
    assert older.disabled == "needs setup: Something is missing"


def test_follow_shows_running_lookups_again(logged_in, no_waiting):
    logged_in.started = ["job-oi"]
    result = run("follow")
    assert result.exit_code == 0, result.output
    assert "spotify.com" in result.output and "OSINT Industries done" in result.output


def test_new_items_by_identity_not_place():
    seen = set()
    first = follow.new_items({"modules": [GITHUB], "count": 1, "domains": {"a.test": {"ns": "x"}}}, seen)
    assert [(s, k) for s, k, _ in first] == [("modules", None), ("domains", "a.test")]
    again = follow.new_items({"modules": [DISCORD, {**GITHUB, "profile": {"bio": "hi"}}],
                              "domains": {"a.test": {"ns": "y"}, "b.test": {}}}, seen)
    assert [(s, k, i) for s, k, i in again] == [("modules", None, DISCORD), ("domains", "b.test", {})]
