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
        mark = "[green]●[/]" if inv.get("investigation_id") == current_id else ""
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
