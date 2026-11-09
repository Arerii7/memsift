from __future__ import annotations

import difflib
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from . import db
from .config import Config
from .ingest.markdown import parse_blocks
from .models import MemoryRecord, now_ms


@dataclass(slots=True)
class SyncChange:
    path: Path
    original: str
    updated: str
    memory_ids: list[str] = field(default_factory=list)
    diff: str = ""

    @property
    def changed(self) -> bool:
        return self.original != self.updated


@dataclass(slots=True)
class SyncPlan:
    changes: list[SyncChange] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return any(change.changed for change in self.changes)

    @property
    def memory_ids(self) -> list[str]:
        return [memory_id for change in self.changes for memory_id in change.memory_ids]

    def diff_text(self) -> str:
        return "\n".join(change.diff for change in self.changes if change.diff)


@dataclass(slots=True)
class SyncResult:
    event_id: str
    backup_dir: Path
    files: list[dict[str, str]]
    memory_ids: list[str]


def _path_from_ref(source_ref: str) -> Path:
    return Path(source_ref.rsplit(":", 1)[0]).expanduser()


def _pending(conn: sqlite3.Connection) -> list[MemoryRecord]:
    return [
        record
        for record in db.all_memories(conn)
        if record.sync_action in {"update", "delete"} and record.source_kind == "markdown"
    ]


def plan_sync(conn: sqlite3.Connection) -> SyncPlan:
    pending = _pending(conn)
    by_path: dict[Path, list[MemoryRecord]] = {}
    for record in pending:
        by_path.setdefault(_path_from_ref(record.source_ref), []).append(record)

    plan = SyncPlan()
    for path, records in sorted(by_path.items(), key=lambda item: str(item[0])):
        if not path.exists():
            plan.skipped.append(f"{path}: source file no longer exists")
            continue
        try:
            original = path.read_text(encoding="utf-8")
        except OSError as exc:
            plan.skipped.append(f"{path}: {exc}")
            continue
        digest = hashlib.sha256(original.encode("utf-8")).hexdigest()
        if any(record.source_hash != digest for record in records):
            plan.skipped.append(
                f"{path}: source file changed since scan; rescan and review pending changes"
            )
            continue
        blocks = parse_blocks(original, filename=path.name, relpath=path.name)
        by_id = {block.explicit_id: block for block in blocks if block.explicit_id}
        lines = original.splitlines()
        edits: list[tuple[int, int, list[str], str]] = []
        memory_ids: list[str] = []
        for record in records:
            block = by_id.get(record.id)
            if block is None:
                plan.skipped.append(f"{path}: no writable anchor for {record.id}")
                continue
            if record.sync_action == "update":
                replacement = record.body.splitlines() or [record.claim]
                edits.append((block.content_start, block.content_end, replacement, record.id))
            else:
                end = block.end_line
                if end < len(lines) and not lines[end].strip():
                    end += 1
                edits.append((block.start_line, end, [], record.id))
            memory_ids.append(record.id)

        if not edits:
            continue
        edits.sort(key=lambda item: (item[0], item[1]), reverse=True)
        new_lines = list(lines)
        for start, end, replacement, _memory_id in edits:
            new_lines[start:end] = replacement
        updated = "\n".join(new_lines)
        if original.endswith("\n"):
            updated += "\n"
        diff = "".join(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                updated.splitlines(keepends=True),
                fromfile=str(path),
                tofile=f"{path} (memsift)",
            )
        )
        plan.changes.append(
            SyncChange(
                path=path,
                original=original,
                updated=updated,
                memory_ids=memory_ids,
                diff=diff,
            )
        )
    return plan


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode if path.exists() else 0o644
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".memsift.tmp", dir=str(path.parent)
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, stat.S_IMODE(mode))
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def _backup_dest(backup_dir: Path, path: Path) -> Path:
    return backup_dir / "files" / str(path.resolve()).lstrip("/")


def apply_sync(
    conn: sqlite3.Connection, plan: SyncPlan, config: Config | None = None, *, actor: str = "user"
) -> SyncResult:
    cfg = config or Config.load()
    changed = [change for change in plan.changes if change.changed]
    if not changed:
        raise ValueError("nothing to sync")
    for change in changed:
        if change.path.read_text(encoding="utf-8") != change.original:
            raise ValueError(f"source file changed since sync preview: {change.path}")
    cfg.ensure_dirs()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = cfg.backups_dir / stamp
    backup_dir.mkdir(parents=True, exist_ok=False)
    files: list[dict[str, str]] = []
    written: list[tuple[Path, Path]] = []
    try:
        for change in changed:
            dest = _backup_dest(backup_dir, change.path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(change.path, dest)
            _atomic_write(change.path, change.updated)
            digest = hashlib.sha256(change.updated.encode("utf-8")).hexdigest()
            db.upsert_source_file(
                conn,
                change.path,
                digest=digest,
                mtime=int(change.path.stat().st_mtime * 1000),
                parser="markdown",
            )
            for memory_id in change.memory_ids:
                db.update_memory_fields(
                    conn,
                    memory_id,
                    sync_action="none",
                    source_hash=digest,
                    last_seen_at=now_ms(),
                )
            files.append({"path": str(change.path), "backup": str(dest)})
            written.append((change.path, dest))
    except Exception:
        # A failed multi-file sync must not leave a half-applied plan.
        for path, dest in written:
            shutil.copy2(dest, path)
        raise

    event_id = db.insert_event(
        conn,
        memory_id=None,
        action="sync",
        actor=actor,
        before={"files": [{"path": str(c.path), "hash": hashlib.sha256(c.original.encode()).hexdigest()} for c in changed]},
        after={"backup_dir": str(backup_dir), "files": files, "memory_ids": plan.memory_ids},
        note=f"Applied {len(changed)} file change(s).",
    )
    return SyncResult(event_id=event_id, backup_dir=backup_dir, files=files, memory_ids=plan.memory_ids)


def rollback_event(
    conn: sqlite3.Connection, event_id: str, *, actor: str = "user"
) -> list[str]:
    event = db.get_event(conn, event_id)
    if event is None:
        raise ValueError(f"event not found: {event_id}")
    if event.action != "sync":
        raise ValueError("only sync events can be rolled back")
    try:
        payload = json.loads(event.after_json)
    except json.JSONDecodeError as exc:
        raise ValueError("sync event has no usable backup metadata") from exc
    files = payload.get("files", [])
    if not files:
        raise ValueError("sync event has no backed-up files")
    restored: dict[str, str] = {}
    for item in files:
        path = Path(str(item["path"]))
        backup = Path(str(item["backup"]))
        if not backup.exists():
            raise ValueError(f"backup is missing: {backup}")
        original = backup.read_text(encoding="utf-8")
        _atomic_write(path, original)
        digest = hashlib.sha256(original.encode("utf-8")).hexdigest()
        db.upsert_source_file(
            conn,
            path,
            digest=digest,
            mtime=int(path.stat().st_mtime * 1000),
            parser="markdown",
        )
        restored[str(path)] = digest
    db.insert_event(
        conn,
        memory_id=None,
        action="rollback",
        actor=actor,
        before={"rollback_of": event_id},
        after={"files": restored},
        note=f"Restored {len(restored)} file(s) from backup.",
    )
    return list(restored)
