"""What the commands print for people (rich tables and trees). --json skips all of this."""
from datetime import datetime
from typing import Any, Optional

from rich.console import Console
from rich.markup import escape
from rich.table import Table
from rich.tree import Tree

# soft_wrap: long paths and ids are not broken across lines
out = Console(soft_wrap=True)
err = Console(stderr=True, soft_wrap=True)


def when(value: Optional[str]) -> str:
    """'2026-11-23 14:05' from an ISO timestamp."""
    if not value:
        return ""
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return str(value)[:16]


def investigations(items: list[dict], current_id: Optional[str]) -> Table:
    table = Table(box=None, header_style="bold")
    for column in ("", "Name", "Status", "Results", "Updated", "ID"):
        table.add_column(column, overflow="fold" if column == "Name" else "ellipsis", no_wrap=column != "Name")
    for inv in items:
        mark = "[green]*[/]" if inv.get("investigation_id") == current_id else ""
        table.add_row(mark, escape(inv.get("name") or ""), escape(inv.get("status") or ""),
                      str(inv.get("results_count", 0)), when(inv.get("updated_at")),
                      f"[dim]{escape(inv.get('investigation_id', '')[:8])}[/]")  # enough for `osint use`
    return table


def investigation_header(inv: dict) -> str:
    lines = [f"[bold]{escape(inv.get('name') or '')}[/]  [dim]{escape(inv.get('investigation_id', ''))}[/]"]
    count = inv.get("results_count", 0)
    details = [inv.get("status"), f"{count} result{'' if count == 1 else 's'}", f"updated {when(inv.get('updated_at'))}"]
    lines.append(" · ".join(escape(str(d)) for d in details if d))
    if inv.get("description"):
        lines.append(escape(inv["description"]))
    return "\n".join(lines)


def _result_label(service: Any, method: Any, target: Any, summary: Any, timestamp: Any, extra: str = "") -> str:
    what = f"[cyan]{escape(service or '')}[/] [dim]{escape(method or '')}[/]"
    target = f" [bold]{escape(str(target))}[/]" if target else ""
    summary = f" - {escape(str(summary))}" if summary else ""
    return f"{what}{target}{summary}{extra}  [dim]{when(timestamp)}[/]"


def results_tree(title: str, results: list[dict]) -> Tree:
    """Each saved result, with the follow-up lookups saved under it."""
    tree = Tree(title)
    for r in results:
        extra = " [yellow](partial)[/]" if r.get("partial") else ""
        triage = (r.get("triage") or {}).get("status")
        if triage:
            extra += f" [magenta]{escape(triage.replace('_', ' '))}[/]"
        branch = tree.add(_result_label(r.get("service_name"), r.get("method_name"), r.get("target"),
                                        r.get("summary"), r.get("timestamp"), extra))
        for c in r.get("children") or []:
            branch.add(_result_label(c.get("service_name"), c.get("method_name"), c.get("target"),
                                     c.get("summary"), c.get("timestamp")))
    if not results:
        tree.add("[dim]no results yet[/]")
    return tree


def entities(items: list[dict]) -> Table:
    table = Table(box=None, header_style="bold")
    for column in ("Type", "Value", "Found in", "Status"):
        table.add_column(column, overflow="fold" if column == "Value" else "ellipsis")
    for e in items:
        sources = e.get("sources") or []
        found = f"{len(sources)} result{'s' if len(sources) != 1 else ''}" if sources else ""
        elsewhere = len(e.get("elsewhere") or [])
        if elsewhere:
            found += f" [yellow]+{elsewhere} other case{'s' if elsewhere != 1 else ''}[/]"
        table.add_row(escape(e.get("label") or e.get("type", "")), escape(e.get("value", "")), found,
                      escape((e.get("status") or "").replace("_", " ")))
    return table


def modules(items: list[dict]) -> Table:
    table = Table(box=None, header_style="bold")
    for column in ("ID", "Module", "Looks up", "Cost", "Ready"):
        table.add_column(column)
    for m in items:
        ready = "[green]yes[/]" if m.get("ready") else f"[red]no[/] [dim]{escape('; '.join(m.get('problems') or []))}[/]"
        table.add_row(escape(m.get("id", "")), escape(m.get("name", "")), escape(", ".join(m.get("accepts") or [])),
                      escape(m.get("cost") or ""), ready)
    return table


STATUS_STYLE = {"done": "green", "failed": "red", "cancelled": "dim", "running": "yellow", "queued": "yellow"}


def jobs(items: list[dict]) -> Table:
    table = Table(box=None, header_style="bold")
    for column in ("ID", "Module", "Value", "Status", "Started", "Result"):
        table.add_column(column, overflow="fold" if column in ("Value", "Result") else "ellipsis")
    for j in items:
        status = j.get("status", "")
        result = j.get("error") or j.get("summary") or ""
        table.add_row(escape(j.get("id", "")), escape(j.get("module_name") or j.get("module_id", "")),
                      escape(j.get("value", "")), f"[{STATUS_STYLE.get(status, 'white')}]{escape(status)}[/]",
                      when(j.get("started_at") or j.get("created_at")), escape(str(result)))
    return table


def candidates(found: list[dict]) -> Tree:
    """What a value could be, and the modules that can look each reading up."""
    tree = Tree("[bold]Modules that can look this up[/] [dim](start them with -m id,id)[/]")
    for c in found:
        branch = tree.add(f"{escape(c.get('label') or c.get('type', ''))}: [bold]{escape(c.get('display') or c.get('value', ''))}[/]")
        for m in c.get("modules") or []:
            state = "[green]ready[/]" if m.get("ready") else f"[red]needs setup[/] [dim]{escape('; '.join(m.get('problems') or []))}[/]"
            earlier = " [yellow]looked up before[/]" if m.get("previous") else ""
            branch.add(f"[cyan]{escape(m.get('id', ''))}[/] {escape(m.get('name', ''))} [dim]{escape(m.get('cost') or '')}[/] {state}{earlier}")
        if not c.get("modules"):
            branch.add("[dim]no module looks this up yet[/]")
    return tree


# --- following lookups (osint lookup) ---

TITLE_KEYS = ("site_name", "title", "name", "module", "provider", "email", "username", "domain", "value", "label")
SUBTITLE_KEYS = ("subtitle", "category", "status", "type")
URL_KEYS = ("url", "link", "profile_url")
# the lists that are a module's finds themselves; other lists say what they are
MAIN_SECTIONS = {"results", "items", "modules", "entries", "domains"}
LIST_MAX = 50


def _scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _first(item: dict, keys: tuple) -> Optional[str]:
    for key in keys:
        value = item.get(key)
        if not _empty(value) and not isinstance(value, (dict, list)):
            return _scalar(value)
    return None


def _item_text(item: Any, with_details: bool = True) -> str:
    """A find on one line: its name, what kind it is, its link; else a few of its fields."""
    if not isinstance(item, dict):
        return escape(_scalar(item))
    title, subtitle, url = _first(item, TITLE_KEYS), _first(item, SUBTITLE_KEYS), _first(item, URL_KEYS)
    parts = [f"[bold]{escape(title)}[/]"] if title else []
    if subtitle and subtitle != title:
        parts.append(f"[dim]{escape(subtitle)}[/]")
    if url and url != title:
        parts.append(escape(url))
    if not parts and with_details:
        fields = [(k, v) for k, v in item.items() if not _empty(v) and not isinstance(v, (dict, list))][:4]
        parts = [f"[dim]{escape(str(k))}:[/] {escape(_scalar(v))}" for k, v in fields]
    return " ".join(parts)


def stream_item(module: str, section: str, key: Optional[str], item: Any) -> str:
    """One find of a streaming lookup, as it arrives."""
    parts = [f"[cyan]{escape(module)}[/]"]
    if section not in MAIN_SECTIONS:
        parts.append(f"[dim]{escape(section.replace('_', ' '))}:[/]")
    if key is not None:
        parts.append(f"[bold]{escape(str(key))}[/]")
    text = _item_text(item, with_details=True)
    if text:
        parts.append(text)
    return " ".join(parts)


def _add(node: Tree, value: Any) -> None:
    if isinstance(value, dict):
        for key, v in value.items():
            if _empty(v):
                continue
            if isinstance(v, (dict, list)):
                _add(node.add(f"[bold]{escape(str(key))}[/]"), v)
            else:
                node.add(f"[bold]{escape(str(key))}:[/] {escape(_scalar(v))}")
    elif isinstance(value, list):
        for v in value[:LIST_MAX]:
            if isinstance(v, (dict, list)):
                label = _item_text(v, with_details=False) if isinstance(v, dict) else ""
                _add(node.add(label or "[dim]-[/]"), v)
            elif not _empty(v):
                node.add(escape(_scalar(v)))
        if len(value) > LIST_MAX:
            node.add(f"[dim]... {len(value) - LIST_MAX} more (--json shows all)[/]")
    elif not _empty(value):
        node.add(escape(_scalar(value)))


def answer(module: str, value: Any, result: Any) -> Tree:
    """A lookup's whole answer, every field, the way the server saved it."""
    tree = Tree(f"[cyan]{escape(module)}[/] [bold]{escape(str(value or ''))}[/]")
    _add(tree, result)
    if not tree.children:
        tree.add("[dim]empty answer[/]")
    return tree


def _progress(job: dict) -> str:
    progress = job.get("progress") or {}
    done, total, found = progress.get("done"), progress.get("total"), progress.get("found")
    parts = []
    if done is not None:
        parts.append(f"{done}/{total} checked" if total else f"{done} checked")
    if found is not None:
        parts.append(f"{found} found")
    return ", ".join(parts)


def jobs_waiting(items: list[dict]) -> str:
    """The spinner's line while lookups run."""
    parts = []
    for j in items:
        state = j.get("status") or "queued"
        detail = _progress(j) if state == "running" else ""
        parts.append(f"{escape(j.get('module_name') or j.get('module_id', ''))} "
                     f"[{STATUS_STYLE.get(state, 'white')}]{escape(detail or state)}[/]")
    return "Waiting: " + " · ".join(parts)


def job_finished(job: dict) -> str:
    name = escape(job.get("module_name") or job.get("module_id", ""))
    status = job.get("status")
    if status == "failed":
        return f"[red]✗ {name} failed:[/] {escape(str(job.get('error') or 'no reason given'))}"
    if status == "cancelled":
        return f"[dim]- {name} was cancelled[/]"
    summary = f": {escape(str(job['summary']))}" if job.get("summary") else ""
    saved = f" [dim](result {escape(job['result_id'])})[/]" if job.get("result_id") else ""
    return f"[green]✓ {name} done[/]{summary}{saved}"
