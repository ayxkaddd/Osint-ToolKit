"""`osint`: investigations, identifiers and background lookups of an OSINT Toolkit server.

Everything goes through the server's HTTP API, so what the CLI does shows up in the web
dashboard (and the other way round). Read commands take --json: the API's answer on
stdout and nothing else, for jq.
"""
import codecs
import functools
import json
import re
import sys
from pathlib import Path
from typing import Optional

import typer

from . import __version__, config, render
from .client import ApiError, Client


def _utf8(stream) -> bool:
    try:
        return codecs.lookup(getattr(stream, "encoding", None) or "ascii").name == "utf-8"
    except LookupError:
        return False


def _never_fail_on_characters() -> None:
    """Output into a pipe on Windows is cp1252: a name in Cyrillic, an emoji (or the help's
    own text) would stop the command with UnicodeEncodeError. Such characters show as "?"."""
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and not _utf8(stream) and hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")


_never_fail_on_characters()

app = typer.Typer(help="Investigations, identifiers and background lookups of an OSINT Toolkit server.",
                  no_args_is_help=True, add_completion=False,
                  context_settings={"help_option_names": ["-h", "--help"]})

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
JsonOption = typer.Option(False, "--json", help="Print the API's answer as JSON, nothing else")


class State:
    url_option: Optional[str] = None


state = State()


@app.callback()
def main(
    url: Optional[str] = typer.Option(None, "--url", help="Server address (default: the one you logged in to, "
                                      "or OSINT_URL, or http://127.0.0.1:8000)"),
    version: bool = typer.Option(False, "--version", help="Show the version and exit"),
):
    if version:
        typer.echo(__version__)
        raise typer.Exit()
    state.url_option = url


def handles_errors(command):
    """Errors go to stderr in words, with exit code 1."""
    @functools.wraps(command)
    def wrapper(*args, **kwargs):
        try:
            return command(*args, **kwargs)
        except ApiError as e:
            render.err.print(f"[red]Error:[/] {render.escape(str(e))}")
            raise typer.Exit(1) from None
    return wrapper


def client(require_login: bool = True) -> Client:
    cfg = config.load()
    if require_login and not cfg.token:
        raise ApiError("Not logged in, run `osint login`")
    return Client(config.server_url(state.url_option, cfg), cfg.token)


def print_json(data) -> None:
    # where output can't be UTF-8, non-ASCII characters go out as \u escapes: still the same JSON
    typer.echo(json.dumps(data, indent=2, ensure_ascii=not _utf8(sys.stdout)))


def resolve_investigation(api: Client, given: Optional[str]) -> str:
    """An investigation id from an id, the start of one, or a name; none given: the current one."""
    if not given:
        current = api.current().get("investigation_id")
        if not current:
            raise ApiError("No current investigation - pick one with `osint use <id>` (see `osint list`)")
        return current
    if UUID_RE.match(given):
        return given.lower()
    items = api.investigations().get("investigations", [])
    by_id = [i for i in items if i["investigation_id"].startswith(given.lower())]
    by_name = [i for i in items if (i.get("name") or "").strip().lower() == given.strip().lower()]
    matches = by_id or by_name
    if len(matches) == 1:
        return matches[0]["investigation_id"]
    if not matches:
        raise ApiError(f"No investigation matches '{given}' (see `osint list`)")
    raise ApiError(f"'{given}' matches {len(matches)} investigations - use more of the id")


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

@app.command()
@handles_errors
def login(
    url: Optional[str] = typer.Argument(None, help="Server address, e.g. http://127.0.0.1:8000"),
    email: Optional[str] = typer.Option(None, "--email", "-e", help="Admin email (asked if not given)"),
):
    """Log in to the server and remember it (the login lasts 24 hours)."""
    cfg = config.load()
    address = (url or state.url_option or config.server_url(None, cfg)).rstrip("/")
    if not re.match(r"^https?://", address):
        address = "http://" + address
    email = email or typer.prompt("Email")
    password = typer.prompt("Password", hide_input=True)
    api = Client(address)
    try:
        token = api.login(email, password)
    finally:
        api.close()
    config.save(config.Config(url=address, token=token))
    render.out.print(f"Logged in to {render.escape(address)}")


@app.command()
@handles_errors
def logout(everywhere: bool = typer.Option(False, "--everywhere", help="End every session: other browsers too")):
    """Forget the login (and end it on the server)."""
    cfg = config.load()
    if cfg.token:
        api = client()
        try:
            api.logout(everywhere)
        except ApiError as e:
            render.err.print(f"[yellow]The server didn't answer ({render.escape(str(e))}); the login is forgotten here anyway[/]")
        finally:
            api.close()
    config.save(config.Config(url=cfg.url, token=None))
    render.out.print("Logged out" + (" everywhere" if everywhere else ""))


# ---------------------------------------------------------------------------
# Investigations
# ---------------------------------------------------------------------------

@app.command("list")
@handles_errors
def list_investigations(as_json: bool = JsonOption):
    """All investigations (* marks the current one)."""
    api = client()
    data = api.investigations()
    if as_json:
        return print_json(data)
    current = api.current().get("investigation_id")
    items = data.get("investigations", [])
    if not items:
        render.out.print("No investigations yet - create one in the web app")
        return
    render.out.print(render.investigations(items, current))


@app.command()
@handles_errors
def current(as_json: bool = JsonOption):
    """The investigation lookups are saved to."""
    data = client().current()
    if as_json:
        return print_json(data)
    if not data.get("investigation"):
        render.out.print("No current investigation - pick one with `osint use <id>`")
        return
    render.out.print(render.investigation_header(data["investigation"]))


@app.command()
@handles_errors
def use(investigation: str = typer.Argument(..., help="Investigation id (or its start, or its name)")):
    """Make an investigation the current one. The web app's current investigation changes too."""
    api = client()
    data = api.set_current(resolve_investigation(api, investigation))
    name = (data.get("investigation") or {}).get("name") or investigation
    render.out.print(f"Lookups are now saved to [bold]{render.escape(name)}[/]")
    render.err.print("[yellow]The web app's current investigation is this one now too.[/]")


@app.command()
@handles_errors
def show(investigation: Optional[str] = typer.Argument(None, help="Investigation (default: the current one)"),
         as_json: bool = JsonOption):
    """An investigation and its results, follow-up lookups under the one they came from."""
    api = client()
    inv_id = resolve_investigation(api, investigation)
    data = api.investigation(inv_id)
    if as_json:
        return print_json(data)
    info = data.get("investigation") or data
    results = data.get("results")
    if results is None:
        results = api.results(inv_id).get("results", [])
    render.out.print(render.results_tree(render.investigation_header(info), results))


@app.command()
@handles_errors
def entities(investigation: Optional[str] = typer.Argument(None, help="Investigation (default: the current one)"),
             type: Optional[str] = typer.Option(None, "--type", "-t", help="Only this kind: email, phone, username, domain, ..."),
             as_json: bool = JsonOption):
    """Identifiers found in an investigation's results."""
    api = client()
    data = api.entities(resolve_investigation(api, investigation), type)
    if as_json:
        return print_json(data)
    items = data.get("entities", [])
    if not items:
        kinds = ", ".join(t["type"] for t in data.get("types", []))
        render.out.print("No identifiers" + (f" of type {render.escape(type)}" if type else "") +
                         (f" (types here: {render.escape(kinds)})" if type and kinds else ""))
        return
    render.out.print(render.entities(items))
    if data.get("total", len(items)) > len(items):
        render.out.print(f"[dim]{len(items)} of {data['total']} shown[/]")


@app.command()
@handles_errors
def export(investigation: Optional[str] = typer.Argument(None, help="Investigation (default: the current one)"),
           output: Optional[Path] = typer.Option(None, "--output", "-o", help="File to write (default: named after the id)"),
           report: bool = typer.Option(False, "--report", help="The HTML report instead of the .zip"),
           everything: bool = typer.Option(False, "--all", help="Report: every result, not only the marked findings")):
    """Save an investigation as a .zip (data, results, notes, files) or as the HTML report."""
    api = client()
    inv_id = resolve_investigation(api, investigation)
    if report:
        target = output or Path(f"{inv_id}-report.html")
        size = api.download(f"/api/investigations/{inv_id}/report", target,
                            {"include": "all" if everything else "findings"})
    else:
        target = output or Path(f"{inv_id}.zip")
        size = api.download(f"/api/investigations/{inv_id}/export", target, {"format": "zip"})
    render.out.print(f"Saved {render.escape(str(target))} ({size:,} bytes)")


# ---------------------------------------------------------------------------
# Modules and lookups
# ---------------------------------------------------------------------------

@app.command()
@handles_errors
def modules(ready: bool = typer.Option(False, "--ready", help="Only the ones that can run now"),
            as_json: bool = JsonOption):
    """Every module: what it looks up, its cost, whether it can run."""
    data = client().modules()
    if as_json:
        return print_json(data)
    items = [m for m in data.get("modules", []) if m.get("ready") or not ready]
    render.out.print(render.modules(items))


@app.command()
@handles_errors
def lookup(value: str = typer.Argument(..., help="An email, phone number, username, domain, IP, ..."),
           module: Optional[str] = typer.Option(None, "--module", "-m",
                                                help="Modules to run, comma-separated (see the list without it)"),
           type: Optional[str] = typer.Option(None, "--type", "-t", help="Read the value as this kind"),
           as_json: bool = JsonOption):
    """Look a value up in the background, saved to the current investigation.

    Without -m it only lists the modules that can look it up: nothing starts (some cost money)."""
    api = client()
    found = api.detect(value)
    candidates = [c for c in found.get("candidates", []) if not type or c.get("type") == type]
    if not module:
        if as_json:
            return print_json(found)
        if not candidates:
            render.out.print("Not recognised as an identifier" + (f" of type {render.escape(type)}" if type else ""))
            for s in found.get("suggestions") or []:
                render.out.print(f"  did you mean {render.escape(str(s.get('value', s)))}?")
            return
        render.out.print(render.candidates(candidates))
        return
    if not found.get("investigation_id"):
        raise ApiError("No current investigation - lookups are saved there. Pick one with `osint use <id>`")
    started, failed = [], 0
    for module_id in [m.strip() for m in module.split(",") if m.strip()]:
        reading = next((c for c in candidates if any(m.get("id") == module_id for m in c.get("modules", []))), None)
        if reading is None:
            render.err.print(f"[red]{render.escape(module_id)}:[/] doesn't look up this value"
                             + (f" as {render.escape(type)}" if type else "") + " (see `osint lookup VALUE` or `osint modules`)")
            failed += 1
            continue
        try:
            job = api.start_job(module_id, reading["type"], reading["value"]).get("job", {})
        except ApiError as e:
            render.err.print(f"[red]{render.escape(module_id)}:[/] {render.escape(str(e))}")
            failed += 1
            continue
        started.append(job)
        if not as_json:
            render.out.print(f"Started {render.escape(job.get('module_name') or module_id)} on "
                             f"[bold]{render.escape(reading['value'])}[/] [dim](job {render.escape(job.get('id', ''))})[/]")
    if as_json:
        print_json(started)
    elif started:
        render.out.print("[dim]Follow them with `osint jobs`[/]")
    if failed:
        raise typer.Exit(1)


@app.command()
@handles_errors
def jobs(everything: bool = typer.Option(False, "--all", help="Jobs of every investigation, not only the current one"),
         as_json: bool = JsonOption):
    """Running and recent background lookups."""
    api = client()
    inv_id = None if everything else api.current().get("investigation_id")
    data = api.jobs(inv_id)
    if as_json:
        return print_json(data)
    items = data.get("jobs", [])
    if not items:
        render.out.print("No jobs" + ("" if everything else " for the current investigation (--all for every one)"))
        return
    render.out.print(render.jobs(items))


@app.command()
@handles_errors
def cancel(job: str = typer.Argument(..., help="Job id (from `osint jobs`)")):
    """Stop a running background lookup."""
    client().cancel_job(job)
    render.out.print(f"Cancelling {render.escape(job)}")
