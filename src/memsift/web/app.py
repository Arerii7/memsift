from __future__ import annotations

import secrets
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .. import __version__, actions, db
from ..config import Config
from ..export import export_markdown
from ..models import MemoryRecord
from ..normalize import date_only, human_age, redact_diff, redact_text
from ..sync import apply_sync, plan_sync

PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"
KIND_ORDER = ["duplicate", "conflict", "stale", "orphan", "secret"]


def _short(value: str, length: int = 100) -> str:
    value = " ".join(str(value).split())
    return value if len(value) <= length else value[: length - 1] + "…"


def _rec_view(record: MemoryRecord | None) -> dict[str, Any] | None:
    if record is None:
        return None
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
        "sensitivity": record.sensitivity,
        "pinned": record.pinned,
        "sync_action": record.sync_action,
        "files": record.files,
        "superseded_by": record.superseded_by,
        "block_kind": record.block_kind,
    }


def create_app(home: Path | None = None) -> FastAPI:
    cfg = Config.load(home)
    cfg.ensure_dirs()
    app = FastAPI(title="memsift review", version=__version__, docs_url=None, redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]"])
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    csrf_token = secrets.token_urlsafe(32)
    templates.env.globals["csrf_token"] = csrf_token

    @app.middleware("http")
    async def protect_forms(request: Request, call_next):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            await request.body()
            form = await request.form()
            supplied = form.get("csrf_token", "")
            if not isinstance(supplied, str) or not secrets.compare_digest(supplied, csrf_token):
                return PlainTextResponse("Invalid or missing form token", status_code=403)
        return await call_next(request)
    templates.env.filters["redact"] = redact_text
    templates.env.filters["redact_diff"] = redact_diff
    templates.env.filters["short"] = _short
    templates.env.filters["date"] = date_only
    templates.env.filters["age"] = human_age

    def conn() -> sqlite3.Connection:
        return db.connect(cfg.db_path)

    def base_context(request: Request, active: str) -> dict[str, Any]:
        return {"request": request, "cfg": cfg, "active": active, "version": __version__}

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request) -> HTMLResponse:
        connection = conn()
        try:
            status_counts = db.counts(connection)
            finding_counts = db.finding_counts(connection)
            total_records = sum(status_counts.values())
            total_findings = sum(finding_counts.values())
            health = max(0, min(100, 100 - total_findings * 7))
            recent = db.recent_events(connection, 8)
            findings = db.list_findings(connection, limit=8)
            records = {record.id: record for record in db.all_memories(connection)}
            finding_items = [
                {
                    "finding": finding,
                    "record": records.get(finding.memory_id),
                    "related": records.get(finding.related_id or ""),
                }
                for finding in findings
            ]
            pending = sum(1 for record in records.values() if record.sync_action != "none")
            sources = cfg.sources
        finally:
            connection.close()
        context = base_context(request, "dashboard")
        context.update(
            status_counts=status_counts,
            finding_counts=finding_counts,
            total_records=total_records,
            total_findings=total_findings,
            health=health,
            recent=recent,
            findings=finding_items,
            pending=pending,
            sources=sources,
        )
        return templates.TemplateResponse(request, "dashboard.html", context)

    @app.get("/queue", response_class=HTMLResponse)
    def queue(request: Request, kind: str | None = None) -> HTMLResponse:
        connection = conn()
        try:
            all_counts = db.finding_counts(connection)
            findings = db.list_findings(connection, kind=kind, limit=500)
            records = {record.id: record for record in db.all_memories(connection)}
            items = []
            for finding in findings:
                items.append(
                    {
                        "finding": finding,
                        "record": records.get(finding.memory_id),
                        "related": records.get(finding.related_id or ""),
                    }
                )
            kinds = [item for item in KIND_ORDER if item in all_counts]
            kinds.extend(sorted(set(all_counts) - set(kinds)))
        finally:
            connection.close()
        context = base_context(request, "queue")
        context.update(kind=kind, kinds=kinds, counts=all_counts, items=items)
        return templates.TemplateResponse(request, "queue.html", context)

    @app.get("/memory/{memory_id}", response_class=HTMLResponse)
    def memory_detail(request: Request, memory_id: str, error: str | None = None) -> HTMLResponse:
        connection = conn()
        try:
            record = db.get_memory(connection, memory_id)
            if record is None:
                raise HTTPException(404, "memory not found")
            findings = db.findings_for(connection, memory_id)
            events = db.events_for(connection, memory_id)
            related = []
            for finding in findings:
                other_id = finding.related_id if finding.memory_id == memory_id else finding.memory_id
                if other_id and other_id != memory_id:
                    other = db.get_memory(connection, other_id)
                    if other:
                        related.append(other)
        finally:
            connection.close()
        context = base_context(request, "queue")
        context.update(
            record=record,
            view=_rec_view(record),
            findings=findings,
            events=events,
            related=related,
            error=error,
        )
        return templates.TemplateResponse(request, "detail.html", context)

    @app.get("/merge", response_class=HTMLResponse)
    def merge_page(
        request: Request,
        a: str | None = None,
        b: str | None = None,
        error: str | None = None,
    ) -> HTMLResponse:
        connection = conn()
        try:
            records = db.all_memories(connection)
            by_id = {record.id: record for record in records}
            if (not a or not b) and records:
                for finding in db.list_findings(connection, limit=500):
                    if finding.kind in {"duplicate", "conflict"} and finding.related_id:
                        a = a or finding.memory_id
                        b = b or finding.related_id
                        break
            left = by_id.get(a or "")
            right = by_id.get(b or "")
            if (a and left is None) or (b and right is None):
                raise HTTPException(404, "memory not found")
            if left is None and right is None and records:
                left, right = records[0], records[1] if len(records) > 1 else None
        finally:
            connection.close()
        context = base_context(request, "merge")
        context.update(
            records=records,
            left=left,
            right=right,
            view_left=_rec_view(left),
            view_right=_rec_view(right),
            error=error,
        )
        return templates.TemplateResponse(request, "merge.html", context)

    @app.post("/merge")
    def merge_submit(
        canonical: str = Form(...),
        other: str = Form(...),
        claim: str = Form(""),
    ) -> RedirectResponse:
        connection = conn()
        try:
            record, _event = actions.merge_memories(
                connection,
                canonical,
                other,
                claim=claim.strip() or None,
                actor="user",
            )
            connection.commit()
        except (ValueError, sqlite3.Error) as exc:
            connection.rollback()
            return RedirectResponse(f"/merge?error={quote(str(exc))}", status_code=303)
        finally:
            connection.close()
        return RedirectResponse(f"/memory/{record.id}?merged=1", status_code=303)

    @app.post("/findings/{finding_id}/approve")
    def approve(finding_id: str) -> RedirectResponse:
        connection = conn()
        try:
            actions.approve_finding(connection, finding_id)
            connection.commit()
        except ValueError as exc:
            connection.rollback()
            raise HTTPException(404, "finding not found") from exc
        finally:
            connection.close()
        return RedirectResponse("/queue", status_code=303)

    @app.post("/findings/{finding_id}/reject")
    def reject(finding_id: str) -> RedirectResponse:
        connection = conn()
        try:
            actions.reject_finding(connection, finding_id)
            connection.commit()
        except ValueError as exc:
            connection.rollback()
            raise HTTPException(404, "finding not found") from exc
        finally:
            connection.close()
        return RedirectResponse("/queue", status_code=303)

    @app.post("/memory/{memory_id}/action")
    def memory_action(
        memory_id: str,
        action: str = Form(...),
        claim: str = Form(""),
    ) -> RedirectResponse:
        connection = conn()
        try:
            if action == "archive":
                actions.archive_memory(connection, memory_id)
            elif action == "forget":
                actions.forget_memory(connection, memory_id)
            elif action == "pin":
                actions.pin_memory(connection, memory_id)
            elif action == "restore":
                actions.restore_memory(connection, memory_id)
            elif action == "edit":
                if not claim.strip():
                    raise ValueError("claim cannot be empty")
                actions.edit_memory(connection, memory_id, claim=claim.strip())
            else:
                raise ValueError(f"unknown action: {action}")
            connection.commit()
        except (ValueError, sqlite3.Error) as exc:
            connection.rollback()
            return RedirectResponse(f"/memory/{memory_id}?error={quote(str(exc))}", status_code=303)
        finally:
            connection.close()
        if action == "forget":
            return RedirectResponse("/queue", status_code=303)
        return RedirectResponse(f"/memory/{memory_id}", status_code=303)

    @app.get("/sync", response_class=HTMLResponse)
    def sync_page(
        request: Request,
        applied: int | None = None,
        event: str | None = None,
        error: str | None = None,
    ) -> HTMLResponse:
        connection = conn()
        try:
            plan = plan_sync(connection)
            records = {record.id: record for record in db.all_memories(connection)}
            pending = [records[memory_id] for memory_id in plan.memory_ids if memory_id in records]
        finally:
            connection.close()
        context = base_context(request, "sync")
        context.update(
            plan=plan,
            pending=pending,
            applied=applied,
            event=event,
            error=error,
        )
        return templates.TemplateResponse(request, "sync.html", context)

    @app.post("/sync/apply")
    def sync_apply(confirm: str = Form(""), preview_hash: str = Form("")) -> RedirectResponse:
        if confirm != "yes":
            return RedirectResponse("/sync?error=Please+confirm+the+write", status_code=303)
        connection = conn()
        try:
            connection.execute("BEGIN IMMEDIATE")
            plan = plan_sync(connection)
            if not secrets.compare_digest(preview_hash, plan.fingerprint()):
                raise ValueError("Sync preview changed or expired. Review the current diff before applying.")
            if not plan.changed:
                return RedirectResponse("/sync?error=Nothing+to+apply", status_code=303)
            result = apply_sync(connection, plan, cfg)
            connection.commit()
        except (ValueError, OSError, sqlite3.Error) as exc:
            connection.rollback()
            return RedirectResponse(f"/sync?error={quote(str(exc))}", status_code=303)
        finally:
            connection.close()
        return RedirectResponse(
            f"/sync?applied=1&event={quote(result.event_id)}", status_code=303
        )

    @app.get("/settings", response_class=HTMLResponse)
    def settings(request: Request) -> HTMLResponse:
        connection = conn()
        try:
            status_counts = db.counts(connection)
            total = sum(status_counts.values())
            export_preview = export_markdown(connection)
        finally:
            connection.close()
        context = base_context(request, "settings")
        context.update(
            status_counts=status_counts,
            total=total,
            export_preview=export_preview,
        )
        return templates.TemplateResponse(request, "settings.html", context)

    @app.get("/api/health")
    def api_health() -> dict[str, Any]:
        connection = conn()
        try:
            status_counts = db.counts(connection)
            finding_counts = db.finding_counts(connection)
            return {
                "ok": True,
                "records": sum(status_counts.values()),
                "statuses": status_counts,
                "findings": finding_counts,
            }
        finally:
            connection.close()

    return app
