from __future__ import annotations

import json as jsonlib
import sqlite3
import threading
import webbrowser
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import __version__, actions, db
from .anchor import add_anchors
from .config import Config
from .detect import run_detectors
from .export import export_json, export_markdown
from .ingest.markdown import ingest_markdown
from .ingest.opencode import default_opencode_db, ingest_opencode
from .models import Event, Finding, MemoryRecord
from .normalize import date_only, human_age, redact_text
from .sync import apply_sync, plan_sync, rollback_event

console = Console()
app = typer.Typer(
    name="memsift",
    help="Sift your agent's memory: find junk, review it, write clean Markdown back.",
    no_args_is_help=True,
    add_completion=False,
)


def _config() -> Config:
    return Config.load()


def _connect(cfg: Config) -> sqlite3.Connection:
    cfg.ensure_dirs()
    return db.connect(cfg.db_path)


def _fail(message: str, code: int = 1) -> None:
    console.print(f"[red]error:[/red] {message}")
    raise typer.Exit(code)


def _short(value: str, length: int = 80) -> str:
    value = " ".join(value.split())
    return value if len(value) <= length else value[: length - 1] + "…"


def _record_view(record: MemoryRecord) -> dict[str, object]:
    secret = record.sensitivity == "secret"
    return {
        "id": record.id,
        "claim": redact_text(record.claim) if secret else record.claim,
        "body": redact_text(record.body) if secret else record.body,
        "topic_key": record.topic_key,
        "scope": record.scope,
        "source_kind": record.source_kind,
        "source_ref": record.source_ref,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "confidence": record.confidence,
        "status": record.status,
        "supersedes": record.supersedes,
        "superseded_by": record.superseded_by,
        "files": record.files,
        "tags": record.tags,
        "sensitivity": record.sensitivity,
        "pinned": record.pinned,
        "sync_action": record.sync_action,
    }


def _finding_view(finding: Finding) -> dict[str, object]:
    return {
        "id": finding.id,
        "memory_id": finding.memory_id,
        "related_id": finding.related_id,
        "kind": finding.kind,
        "severity": finding.severity,
        "score": finding.score,
        "title": finding.title,
        "detail": finding.detail,
        "status": finding.status,
    }


def _event_view(event: Event) -> dict[str, object]:
    return {
        "id": event.id,
        "memory_id": event.memory_id,
        "action": event.action,
        "actor": event.actor,
        "at": event.at,
        "before": event.before_json,
        "after": event.after_json,
        "note": event.note,
    }


def _print_ingest(stats: object) -> None:
    table = Table(title="Ingest", show_header=True, header_style="bold")
    table.add_column("files", justify="right")
    table.add_column("records", justify="right")
    table.add_column("skipped", justify="right")
    table.add_column("errors")
    table.add_row(
        str(getattr(stats, "files", 0)),
        str(getattr(stats, "records", 0)),
        str(getattr(stats, "skipped", 0)),
        "; ".join(getattr(stats, "errors", [])) or "none",
    )
    console.print(table)


@app.command()
def init(
    path: Optional[Path] = typer.Option(None, "--path", "-p", help="Markdown file or directory to register."),
    no_source: bool = typer.Option(False, "--no-source", help="Do not register any source."),
) -> None:
    """Create the local database and configuration."""
    cfg = _config()
    cfg.ensure_dirs()
    conn = _connect(cfg)
    conn.close()
    added = False
    if not no_source:
        target = (path or Path.cwd()).expanduser()
        if not target.exists():
            _fail(f"source path does not exist: {target}")
        added = cfg.add_source("markdown", target)
    cfg.save()
    console.print(Panel.fit("memsift is ready", style="green"))
    console.print(f"home: [bold]{cfg.home}[/bold]")
    console.print(f"database: {cfg.db_path}")
    console.print(f"config: {cfg.config_path}")
    if cfg.sources:
        console.print("sources:")
        for source in cfg.sources:
            console.print(f"  - {source['kind']}: {source['path']}")
    if added:
        console.print("[dim]source registered[/dim]")


@app.command()
def scan(
    source: str = typer.Option("markdown", "--source", "-s", help="markdown or opencode"),
    path: Optional[Path] = typer.Option(None, "--path", "-p", help="Override configured source path."),
    project: Optional[Path] = typer.Option(None, "--project", help="Project directory for OpenCode."),
    opencode_db: Optional[Path] = typer.Option(None, "--db", help="Path to opencode.db."),
    no_save: bool = typer.Option(False, "--no-save", help="Do not register --path as a source."),
    json_output: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Ingest sources and run all detectors."""
    cfg = _config()
    conn = _connect(cfg)
    try:
        if source == "markdown":
            if path is not None:
                paths = [path]
                if not no_save and cfg.add_source("markdown", path):
                    cfg.save()
            else:
                paths = [
                    Path(item["path"])
                    for item in cfg.sources
                    if item.get("kind") == "markdown" and item.get("path")
                ]
            if not paths:
                _fail("no Markdown sources registered; run `memsift init --path DIR`")
            stats = ingest_markdown(conn, paths, cfg, mark_missing=path is None)
        elif source == "opencode":
            target = project or path or Path.cwd()
            stats = ingest_opencode(
                conn,
                opencode_db=opencode_db or default_opencode_db(),
                project=target,
                config=cfg,
            )
        else:
            _fail(f"unknown source: {source}")
        report = run_detectors(conn, cfg)
        conn.commit()
    except typer.Exit:
        raise
    except (OSError, ValueError, sqlite3.Error) as exc:
        conn.rollback()
        _fail(str(exc))
    finally:
        conn.close()

    if json_output:
        typer.echo(
            jsonlib.dumps(
                {"ingest": stats.as_dict(), "detectors": report.as_dict()},
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    _print_ingest(stats)
    if stats.errors:
        console.print("[yellow]some inputs were skipped; see errors above[/yellow]")
    _print_findings_summary(report.by_kind, report.total)


def _print_findings_summary(by_kind: dict[str, int], total: int) -> None:
    if total == 0:
        console.print("[green]No findings. Memory looks clean.[/green]")
        return
    table = Table(title=f"Findings ({total})", header_style="bold")
    table.add_column("kind")
    table.add_column("count", justify="right")
    for kind, count in sorted(by_kind.items()):
        table.add_row(kind, str(count))
    console.print(table)
    console.print("[dim]Next: memsift doctor, memsift list, or memsift review[/dim]")


@app.command()
def doctor(
    format: str = typer.Option("table", "--format", "-f", help="table or json"),
    min_confidence: float = typer.Option(0.0, "--min-confidence", help="Hide findings below this confidence."),
) -> None:
    """Find and report memory problems."""
    cfg = _config()
    conn = _connect(cfg)
    try:
        report = run_detectors(conn, cfg)
        conn.commit()
        records = {record.id: record for record in db.all_memories(conn)}
        findings = [
            finding
            for finding in report.findings
            if records.get(finding.memory_id) is None
            or records[finding.memory_id].confidence >= min_confidence
        ]
        total_records = len(records)
        health = max(0, min(100, 100 - len(findings) * 8))
    finally:
        conn.close()
    if format == "json":
        typer.echo(
            jsonlib.dumps(
                {
                    "health": health,
                    "records": total_records,
                    "findings": [_finding_view(item) for item in findings],
                    "by_kind": _count_findings(findings),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    console.print(
        Panel(
            f"records: {total_records}   findings: {len(findings)}   health: {health}/100",
            title="memsift doctor",
            style="cyan",
        )
    )
    if not findings:
        console.print("[green]No findings above the confidence threshold.[/green]")
        return
    table = Table(header_style="bold")
    table.add_column("kind")
    table.add_column("score", justify="right")
    table.add_column("id")
    table.add_column("finding")
    for finding in findings[:80]:
        table.add_row(
            finding.kind,
            f"{finding.score:.2f}",
            finding.memory_id,
            _short(finding.title, 100),
        )
    console.print(table)
    if len(findings) > 80:
        console.print(f"[dim]... {len(findings) - 80} more; use --format json or memsift review[/dim]")
    console.print("[dim]Queue: memsift review[/dim]")


def _count_findings(findings: list[Finding]) -> dict[str, int]:
    result: dict[str, int] = {}
    for finding in findings:
        result[finding.kind] = result.get(finding.kind, 0) + 1
    return result


@app.command("list")
def list_cmd(
    status: Optional[str] = typer.Option(None, "--status", "-s"),
    scope: Optional[str] = typer.Option(None, "--scope"),
    source: Optional[str] = typer.Option(None, "--source"),
    limit: int = typer.Option(100, "--limit", "-n"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """List indexed memories."""
    cfg = _config()
    conn = _connect(cfg)
    try:
        records = db.list_memories(
            conn,
            status=status,
            scope=scope,
            source_kind=source,
            limit=limit,
        )
    finally:
        conn.close()
    if json_output:
        typer.echo(jsonlib.dumps([_record_view(record) for record in records], ensure_ascii=False, indent=2))
        return
    table = Table(header_style="bold")
    table.add_column("id")
    table.add_column("status")
    table.add_column("topic")
    table.add_column("claim")
    table.add_column("source")
    for record in records:
        table.add_row(
            record.id,
            record.status,
            record.topic_key or "-",
            _short(redact_text(record.claim) if record.sensitivity == "secret" else record.claim, 70),
            _short(record.source_ref, 55),
        )
    console.print(table)
    console.print(f"[dim]{len(records)} record(s)[/dim]")


@app.command()
def show(
    memory_id: str = typer.Argument(..., help="Memory id"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Show a record, its findings, and its audit history."""
    cfg = _config()
    conn = _connect(cfg)
    try:
        record = db.get_memory(conn, memory_id)
        if record is None:
            _fail(f"memory not found: {memory_id}")
        findings = db.findings_for(conn, memory_id)
        events = db.events_for(conn, memory_id)
    finally:
        conn.close()
    if json_output:
        typer.echo(
            jsonlib.dumps(
                {
                    "memory": _record_view(record),
                    "findings": [_finding_view(item) for item in findings],
                    "events": [_event_view(item) for item in events],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    body = redact_text(record.body) if record.sensitivity == "secret" else record.body
    console.print(Panel(body or "(empty)", title=f"{record.id} · {record.status}", border_style="cyan"))
    console.print(f"claim: {redact_text(record.claim) if record.sensitivity == 'secret' else record.claim}")
    console.print(f"topic: {record.topic_key or '-'}   scope: {record.scope}")
    console.print(f"source: {record.source_kind} {record.source_ref}")
    console.print(f"confidence: {record.confidence:.2f}   sensitivity: {record.sensitivity}")
    console.print(f"created: {date_only(record.created_at)} ({human_age(record.created_at)})")
    if record.superseded_by:
        console.print(f"superseded by: {record.superseded_by}")
    if record.files:
        console.print(f"files: {', '.join(record.files)}")
    if findings:
        table = Table(title="Findings", header_style="bold")
        table.add_column("kind")
        table.add_column("score", justify="right")
        table.add_column("title")
        for finding in findings:
            table.add_row(finding.kind, f"{finding.score:.2f}", finding.title)
        console.print(table)
    if events:
        table = Table(title="History", header_style="bold")
        table.add_column("when")
        table.add_column("action")
        table.add_column("actor")
        table.add_column("note")
        for event in events:
            table.add_row(date_only(event.at), event.action, event.actor, _short(event.note, 60))
        console.print(table)


@app.command()
def review(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8787, "--port"),
    no_open: bool = typer.Option(False, "--no-open", help="Do not open a browser."),
) -> None:
    """Open the local review UI."""
    import uvicorn

    from .web.app import create_app

    cfg = _config()
    cfg.ensure_dirs()
    url = f"http://{host}:{port}"
    console.print(Panel.fit(f"memsift review · {url}", style="cyan"))
    console.print("[dim]Ctrl+C to stop[/dim]")
    if not no_open:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(home=cfg.home), host=host, port=port, log_level="info")


@app.command("merge")
def merge_cmd(
    canonical: str = typer.Argument(...),
    other: str = typer.Argument(...),
    claim: Optional[str] = typer.Option(None, "--claim"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Merge two records; the second is archived."""
    cfg = _config()
    conn = _connect(cfg)
    try:
        record, event_id = actions.merge_memories(conn, canonical, other, claim=claim)
        conn.commit()
    except (ValueError, sqlite3.Error) as exc:
        conn.rollback()
        _fail(str(exc))
    finally:
        conn.close()
    if json_output:
        typer.echo(jsonlib.dumps({"memory": _record_view(record), "event": event_id}, ensure_ascii=False, indent=2))
        return
    console.print(f"[green]merged[/green] {other} -> {canonical}")
    console.print(f"event: {event_id}")
    console.print("[dim]Preview writes with memsift sync --dry-run[/dim]")


@app.command()
def supersede(
    old: str = typer.Argument(...),
    new: str = typer.Argument(...),
) -> None:
    """Archive an old record and point it at a newer one."""
    cfg = _config()
    conn = _connect(cfg)
    try:
        event_id = actions.supersede_memory(conn, old, new)
        conn.commit()
    except (ValueError, sqlite3.Error) as exc:
        conn.rollback()
        _fail(str(exc))
    finally:
        conn.close()
    console.print(f"[green]superseded[/green] {old} -> {new}")
    console.print(f"event: {event_id}")


@app.command()
def archive(memory_id: str = typer.Argument(...)) -> None:
    """Archive a record; sync will remove its anchored block after review."""
    _memory_action(actions.archive_memory, memory_id, "archived")


@app.command()
def forget(memory_id: str = typer.Argument(...)) -> None:
    """Forget a record; sync will remove its anchored block after review."""
    _memory_action(actions.forget_memory, memory_id, "forgotten")


@app.command()
def pin(memory_id: str = typer.Argument(...)) -> None:
    """Pin a record as canonical."""
    _memory_action(actions.pin_memory, memory_id, "pinned")


@app.command()
def restore(memory_id: str = typer.Argument(...)) -> None:
    """Restore an archived/forgotten record in the database."""
    _memory_action(actions.restore_memory, memory_id, "restored")


def _memory_action(function, memory_id: str, label: str) -> None:
    cfg = _config()
    conn = _connect(cfg)
    try:
        event_id = function(conn, memory_id)
        conn.commit()
    except (ValueError, sqlite3.Error) as exc:
        conn.rollback()
        _fail(str(exc))
    finally:
        conn.close()
    console.print(f"[green]{label}[/green] {memory_id} (event {event_id})")


@app.command()
def sync(
    apply: bool = typer.Option(False, "--apply", help="Write changes. Default is a dry run."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Preview or apply approved Markdown changes."""
    cfg = _config()
    conn = _connect(cfg)
    try:
        plan = plan_sync(conn)
        if plan.skipped:
            for skipped in plan.skipped:
                console.print(f"[yellow]skip:[/yellow] {skipped}")
        if not plan.changed:
            if not plan.skipped:
                console.print("[green]Nothing approved to sync.[/green]")
            return
        if json_output and not apply:
            typer.echo(
                jsonlib.dumps(
                    {
                        "changed": True,
                        "memory_ids": plan.memory_ids,
                        "diff": plan.diff_text(),
                        "skipped": plan.skipped,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return
        if not json_output:
            console.print("[bold]Sync preview[/bold]")
            console.print(plan.diff_text(), markup=False, highlight=False)
        if not apply:
            console.print("[yellow]dry run[/yellow] — run `memsift sync --apply` to write")
            return
        if not yes and not typer.confirm("Write these changes?"):
            console.print("cancelled")
            return
        result = apply_sync(conn, plan, cfg)
        conn.commit()
    except (ValueError, OSError, sqlite3.Error) as exc:
        conn.rollback()
        _fail(str(exc))
    finally:
        conn.close()
    if json_output:
        typer.echo(
            jsonlib.dumps(
                {
                    "event_id": result.event_id,
                    "backup_dir": str(result.backup_dir),
                    "files": result.files,
                    "memory_ids": result.memory_ids,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    console.print(f"[green]synced[/green] {len(result.files)} file(s)")
    console.print(f"backup: {result.backup_dir}")
    console.print(f"event: {result.event_id}")
    console.print(f"[dim]rollback: memsift rollback {result.event_id}[/dim]")


@app.command()
def history(
    memory_id: Optional[str] = typer.Argument(None),
    limit: int = typer.Option(50, "--limit", "-n"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Show the audit trail."""
    cfg = _config()
    conn = _connect(cfg)
    try:
        events = db.events_for(conn, memory_id, limit) if memory_id else db.recent_events(conn, limit)
    finally:
        conn.close()
    if json_output:
        typer.echo(jsonlib.dumps([_event_view(event) for event in events], ensure_ascii=False, indent=2))
        return
    table = Table(header_style="bold")
    table.add_column("event")
    table.add_column("when")
    table.add_column("memory")
    table.add_column("action")
    table.add_column("note")
    for event in events:
        table.add_row(
            event.id,
            date_only(event.at),
            event.memory_id or "-",
            event.action,
            _short(event.note, 60),
        )
    console.print(table)


@app.command()
def rollback(
    event_id: str = typer.Argument(..., help="Sync event id"),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Restore files from a sync backup."""
    cfg = _config()
    conn = _connect(cfg)
    try:
        if not yes and not typer.confirm(f"Restore files from {event_id}?"):
            console.print("cancelled")
            return
        paths = rollback_event(conn, event_id)
        conn.commit()
    except (ValueError, OSError, sqlite3.Error) as exc:
        conn.rollback()
        _fail(str(exc))
    finally:
        conn.close()
    console.print(f"[green]rolled back[/green] {len(paths)} file(s)")
    for path in paths:
        console.print(f"  {path}")


@app.command()
def export(
    format: str = typer.Option("md", "--format", "-f", help="md or json"),
    scope: Optional[str] = typer.Option(None, "--scope"),
    output: Optional[Path] = typer.Option(None, "--output", "-o"),
) -> None:
    """Export active, non-secret memory."""
    cfg = _config()
    conn = _connect(cfg)
    try:
        if format == "json":
            text = export_json(conn, scope)
        elif format == "md":
            text = export_markdown(conn, scope)
        else:
            _fail(f"unknown export format: {format}")
    finally:
        conn.close()
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
        console.print(f"[green]wrote[/green] {output}")
    else:
        typer.echo(text)


@app.command()
def anchor(
    path: Optional[Path] = typer.Option(None, "--path", "-p"),
    apply: bool = typer.Option(False, "--apply", help="Write anchors. Default is a dry run."),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Make Markdown blocks writable by adding memsift anchors."""
    cfg = _config()
    target = path or Path.cwd()
    preview = add_anchors(target, config=cfg, apply=False)
    if preview.errors:
        for error in preview.errors:
            console.print(f"[red]error:[/red] {error}")
        raise typer.Exit(1)
    if preview.count == 0:
        console.print("[green]Nothing to anchor.[/green]")
        return
    console.print(preview.diff, markup=False, highlight=False)
    if not apply:
        console.print(f"[yellow]dry run[/yellow] — would add {preview.count} anchor pair(s)")
        console.print("[dim]run `memsift anchor --apply` to write[/dim]")
        return
    if not yes and not typer.confirm(f"Add {preview.count} anchor pair(s)?"):
        console.print("cancelled")
        return
    result = add_anchors(target, config=cfg, apply=True)
    if result.errors:
        for error in result.errors:
            console.print(f"[red]error:[/red] {error}")
        raise typer.Exit(1)
    console.print(f"[green]anchored[/green] {result.count} block(s); backup: {result.backup}")


@app.command("import")
def import_opencode_cmd(
    source: str = typer.Argument("opencode", help="Source adapter (currently: opencode)."),
    project: Optional[Path] = typer.Option(None, "--project"),
    opencode_db: Optional[Path] = typer.Option(None, "--db"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Import explicit memory markers from OpenCode (read-only)."""
    if source != "opencode":
        _fail(f"unknown import source: {source}")
    cfg = _config()
    conn = _connect(cfg)
    try:
        stats = ingest_opencode(
            conn,
            opencode_db=opencode_db or default_opencode_db(),
            project=project or Path.cwd(),
            config=cfg,
        )
        report = run_detectors(conn, cfg)
        conn.commit()
    except (OSError, ValueError, sqlite3.Error) as exc:
        conn.rollback()
        _fail(str(exc))
    finally:
        conn.close()
    if json_output:
        typer.echo(
            jsonlib.dumps(
                {"ingest": stats.as_dict(), "detectors": report.as_dict()},
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    _print_ingest(stats)
    _print_findings_summary(report.by_kind, report.total)


@app.command()
def version() -> None:
    """Print the version."""
    console.print(f"memsift {__version__}")



if __name__ == "__main__":  # pragma: no cover
    app()
