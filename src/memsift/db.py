from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .models import Event, Finding, MemoryRecord, now_ms, stable_id

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    claim TEXT NOT NULL,
    norm_claim TEXT NOT NULL,
    body TEXT NOT NULL,
    topic_key TEXT,
    scope TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    session_id TEXT,
    message_id TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    last_seen_at INTEGER NOT NULL,
    confidence REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    supersedes TEXT,
    superseded_by TEXT,
    files_json TEXT NOT NULL DEFAULT '[]',
    tags_json TEXT NOT NULL DEFAULT '[]',
    sensitivity TEXT NOT NULL DEFAULT 'normal',
    pinned INTEGER NOT NULL DEFAULT 0,
    sync_action TEXT NOT NULL DEFAULT 'none',
    block_kind TEXT NOT NULL DEFAULT 'paragraph'
);
CREATE INDEX IF NOT EXISTS memories_status_idx ON memories(status);
CREATE INDEX IF NOT EXISTS memories_scope_idx ON memories(scope);
CREATE INDEX IF NOT EXISTS memories_topic_idx ON memories(topic_key);
CREATE INDEX IF NOT EXISTS memories_source_idx ON memories(source_kind, source_ref);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    memory_id TEXT,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    at INTEGER NOT NULL,
    before_json TEXT NOT NULL DEFAULT '{}',
    after_json TEXT NOT NULL DEFAULT '{}',
    note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS events_memory_idx ON events(memory_id, at);
CREATE INDEX IF NOT EXISTS events_at_idx ON events(at);

CREATE TABLE IF NOT EXISTS findings (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    related_id TEXT,
    kind TEXT NOT NULL,
    severity TEXT NOT NULL,
    score REAL NOT NULL,
    title TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS findings_kind_idx ON findings(kind, status);
CREATE INDEX IF NOT EXISTS findings_memory_idx ON findings(memory_id);
CREATE INDEX IF NOT EXISTS findings_related_idx ON findings(related_id);

CREATE TABLE IF NOT EXISTS links (
    from_id TEXT NOT NULL,
    to_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    score REAL NOT NULL,
    PRIMARY KEY (from_id, to_id, kind)
);

CREATE TABLE IF NOT EXISTS source_files (
    path TEXT PRIMARY KEY,
    hash TEXT NOT NULL,
    mtime INTEGER NOT NULL,
    parser TEXT NOT NULL DEFAULT 'markdown',
    last_scan INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS detector_runs (
    id TEXT PRIMARY KEY,
    started_at INTEGER NOT NULL,
    finished_at INTEGER NOT NULL,
    stats_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(claim, body, tags);

DROP TRIGGER IF EXISTS memories_ai;
DROP TRIGGER IF EXISTS memories_ad;
DROP TRIGGER IF EXISTS memories_au;

CREATE TRIGGER memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, claim, body, tags)
    VALUES (new.rowid, new.claim, new.body, new.tags_json);
END;

CREATE TRIGGER memories_ad AFTER DELETE ON memories BEGIN
    DELETE FROM memories_fts WHERE rowid = old.rowid;
END;

CREATE TRIGGER memories_au AFTER UPDATE ON memories BEGIN
    DELETE FROM memories_fts WHERE rowid = old.rowid;
    INSERT INTO memories_fts(rowid, claim, body, tags)
    VALUES (new.rowid, new.claim, new.body, new.tags_json);
END;
"""


def connect(path: str | Path) -> sqlite3.Connection:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def upsert_memory(conn: sqlite3.Connection, record: MemoryRecord) -> None:
    row = record.to_row()
    columns = ", ".join(row)
    placeholders = ", ".join(f":{key}" for key in row)
    conn.execute(
        f"""
        INSERT INTO memories ({columns}) VALUES ({placeholders})
        ON CONFLICT(id) DO UPDATE SET
            claim = CASE WHEN memories.sync_action = 'update'
                         THEN memories.claim ELSE excluded.claim END,
            norm_claim = CASE WHEN memories.sync_action = 'update'
                              THEN memories.norm_claim ELSE excluded.norm_claim END,
            body = CASE WHEN memories.sync_action = 'update'
                        THEN memories.body ELSE excluded.body END,
            topic_key = CASE WHEN memories.sync_action = 'update'
                             THEN memories.topic_key ELSE excluded.topic_key END,
            scope = excluded.scope,
            source_kind = excluded.source_kind,
            source_ref = excluded.source_ref,
            source_hash = excluded.source_hash,
            session_id = excluded.session_id,
            message_id = excluded.message_id,
            last_seen_at = excluded.last_seen_at,
            confidence = CASE WHEN memories.status IN ('archived', 'rejected', 'forgotten')
                              THEN memories.confidence ELSE excluded.confidence END,
            status = CASE WHEN memories.status IN ('archived', 'rejected', 'forgotten')
                          THEN memories.status ELSE excluded.status END,
            supersedes = COALESCE(memories.supersedes, excluded.supersedes),
            superseded_by = COALESCE(memories.superseded_by, excluded.superseded_by),
            files_json = CASE WHEN memories.sync_action = 'update'
                              THEN memories.files_json ELSE excluded.files_json END,
            sensitivity = CASE WHEN memories.sync_action = 'update'
                               THEN memories.sensitivity ELSE excluded.sensitivity END,
            pinned = MAX(memories.pinned, excluded.pinned),
            block_kind = CASE WHEN memories.sync_action = 'update'
                              THEN memories.block_kind ELSE excluded.block_kind END,
            updated_at = CASE WHEN memories.sync_action = 'update'
                              THEN memories.updated_at ELSE excluded.updated_at END
        """,
        row,
    )


def get_memory(conn: sqlite3.Connection, memory_id: str) -> MemoryRecord | None:
    row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
    return MemoryRecord.from_row(row) if row else None


def list_memories(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    scope: str | None = None,
    source_kind: str | None = None,
    limit: int = 200,
) -> list[MemoryRecord]:
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if scope:
        clauses.append("scope = ?")
        params.append(scope)
    if source_kind:
        clauses.append("source_kind = ?")
        params.append(source_kind)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    rows = conn.execute(
        f"SELECT * FROM memories {where} ORDER BY created_at DESC, id LIMIT ?", params
    ).fetchall()
    return [MemoryRecord.from_row(row) for row in rows]


def all_memories(conn: sqlite3.Connection) -> list[MemoryRecord]:
    rows = conn.execute("SELECT * FROM memories ORDER BY created_at ASC, id").fetchall()
    return [MemoryRecord.from_row(row) for row in rows]


def search_memories(conn: sqlite3.Connection, query: str, limit: int = 50) -> list[MemoryRecord]:
    terms = [term for term in query.replace('"', " ").split() if term]
    if not terms:
        return []
    match = " OR ".join(f'"{term}"' for term in terms)
    rows = conn.execute(
        """
        SELECT m.* FROM memories_fts f
        JOIN memories m ON m.rowid = f.rowid
        WHERE memories_fts MATCH ?
        ORDER BY rank
        LIMIT ?
        """,
        (match, limit),
    ).fetchall()
    return [MemoryRecord.from_row(row) for row in rows]


def insert_event(
    conn: sqlite3.Connection,
    *,
    memory_id: str | None,
    action: str,
    actor: str = "user",
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    note: str = "",
) -> str:
    event_id = stable_id("ev", action, memory_id or "", now_ms(), note)
    conn.execute(
        """
        INSERT INTO events (id, memory_id, action, actor, at, before_json, after_json, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            memory_id,
            action,
            actor,
            now_ms(),
            json.dumps(before or {}, ensure_ascii=False),
            json.dumps(after or {}, ensure_ascii=False),
            note,
        ),
    )
    return event_id


def get_event(conn: sqlite3.Connection, event_id: str) -> Event | None:
    row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    if not row:
        return None
    return Event(
        id=row["id"],
        memory_id=row["memory_id"],
        action=row["action"],
        actor=row["actor"],
        at=int(row["at"]),
        before_json=row["before_json"],
        after_json=row["after_json"],
        note=row["note"],
    )


def events_for(conn: sqlite3.Connection, memory_id: str, limit: int = 50) -> list[Event]:
    rows = conn.execute(
        "SELECT * FROM events WHERE memory_id = ? ORDER BY at DESC LIMIT ?",
        (memory_id, limit),
    ).fetchall()
    return [
        Event(
            id=row["id"],
            memory_id=row["memory_id"],
            action=row["action"],
            actor=row["actor"],
            at=int(row["at"]),
            before_json=row["before_json"],
            after_json=row["after_json"],
            note=row["note"],
        )
        for row in rows
    ]


def recent_events(conn: sqlite3.Connection, limit: int = 30) -> list[Event]:
    rows = conn.execute("SELECT * FROM events ORDER BY at DESC LIMIT ?", (limit,)).fetchall()
    return [
        Event(
            id=row["id"],
            memory_id=row["memory_id"],
            action=row["action"],
            actor=row["actor"],
            at=int(row["at"]),
            before_json=row["before_json"],
            after_json=row["after_json"],
            note=row["note"],
        )
        for row in rows
    ]


def prepare_findings(conn: sqlite3.Connection) -> None:
    """Reopen currently detected findings while preserving user decisions.

    Open findings become obsolete at the start of a run. If the same stable
    finding is detected again, `insert_finding` reopens it. Resolved/dismissed
    findings stay decided until the underlying IDs change.
    """
    conn.execute("UPDATE findings SET status = 'obsolete' WHERE status = 'open'")
    conn.execute("DELETE FROM links")


def clear_findings(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM findings")
    conn.execute("DELETE FROM links")


def insert_finding(conn: sqlite3.Connection, finding: Finding) -> None:
    conn.execute(
        """
        INSERT INTO findings
            (id, memory_id, related_id, kind, severity, score, title, detail, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            memory_id = excluded.memory_id,
            related_id = excluded.related_id,
            kind = excluded.kind,
            severity = excluded.severity,
            score = excluded.score,
            title = excluded.title,
            detail = excluded.detail,
            status = CASE WHEN findings.status IN ('resolved', 'dismissed')
                          THEN findings.status ELSE excluded.status END
        """,
        (
            finding.id,
            finding.memory_id,
            finding.related_id,
            finding.kind,
            finding.severity,
            finding.score,
            finding.title,
            finding.detail,
            finding.status,
            finding.created_at,
        ),
    )


def findings_for(conn: sqlite3.Connection, memory_id: str) -> list[Finding]:
    rows = conn.execute(
        "SELECT * FROM findings WHERE (memory_id = ? OR related_id = ?) "
        "AND status != 'obsolete' ORDER BY score DESC",
        (memory_id, memory_id),
    ).fetchall()
    return [_finding_from_row(row) for row in rows]


def list_findings(
    conn: sqlite3.Connection,
    *,
    kind: str | None = None,
    status: str = "open",
    limit: int = 500,
) -> list[Finding]:
    clauses = ["status = ?"]
    params: list[Any] = [status]
    if kind:
        clauses.append("kind = ?")
        params.append(kind)
    params.append(limit)
    rows = conn.execute(
        f"SELECT * FROM findings WHERE {' AND '.join(clauses)} ORDER BY score DESC, created_at DESC LIMIT ?",
        params,
    ).fetchall()
    return [_finding_from_row(row) for row in rows]


def get_finding(conn: sqlite3.Connection, finding_id: str) -> Finding | None:
    row = conn.execute("SELECT * FROM findings WHERE id = ?", (finding_id,)).fetchone()
    return _finding_from_row(row) if row else None


def _finding_from_row(row: sqlite3.Row) -> Finding:
    return Finding(
        id=row["id"],
        memory_id=row["memory_id"],
        related_id=row["related_id"],
        kind=row["kind"],
        severity=row["severity"],
        score=float(row["score"]),
        title=row["title"],
        detail=row["detail"],
        status=row["status"],
        created_at=int(row["created_at"]),
    )


def resolve_finding(conn: sqlite3.Connection, finding_id: str, status: str = "resolved") -> None:
    conn.execute("UPDATE findings SET status = ? WHERE id = ?", (status, finding_id))


def add_link(conn: sqlite3.Connection, from_id: str, to_id: str, kind: str, score: float) -> None:
    left, right = sorted((from_id, to_id))
    conn.execute(
        "INSERT OR REPLACE INTO links (from_id, to_id, kind, score) VALUES (?, ?, ?, ?)",
        (left, right, kind, score),
    )


def source_file(conn: sqlite3.Connection, path: Path) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM source_files WHERE path = ?", (str(path),)).fetchone()


def upsert_source_file(
    conn: sqlite3.Connection,
    path: Path,
    *,
    digest: str,
    mtime: int,
    parser: str = "markdown",
) -> None:
    conn.execute(
        """
        INSERT INTO source_files (path, hash, mtime, parser, last_scan)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
            hash = excluded.hash,
            mtime = excluded.mtime,
            parser = excluded.parser,
            last_scan = excluded.last_scan
        """,
        (str(path), digest, mtime, parser, now_ms()),
    )


def source_files(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM source_files ORDER BY path").fetchall()


def record_detector_run(
    conn: sqlite3.Connection, *, started_at: int, finished_at: int, stats: dict[str, Any]
) -> None:
    conn.execute(
        "INSERT INTO detector_runs (id, started_at, finished_at, stats_json) VALUES (?, ?, ?, ?)",
        (stable_id("run", started_at, finished_at), started_at, finished_at, json.dumps(stats)),
    )


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in conn.execute("SELECT status, COUNT(*) AS n FROM memories GROUP BY status"):
        result[row["status"]] = int(row["n"])
    return result


def finding_counts(conn: sqlite3.Connection, status: str = "open") -> dict[str, int]:
    result: dict[str, int] = {}
    for row in conn.execute(
        "SELECT kind, COUNT(*) AS n FROM findings WHERE status = ? GROUP BY kind", (status,)
    ):
        result[row["kind"]] = int(row["n"])
    return result


def update_memory_fields(conn: sqlite3.Connection, memory_id: str, **fields: Any) -> None:
    allowed = {
        "claim",
        "norm_claim",
        "body",
        "topic_key",
        "status",
        "supersedes",
        "superseded_by",
        "files_json",
        "tags_json",
        "sensitivity",
        "pinned",
        "sync_action",
        "confidence",
        "updated_at",
        "last_seen_at",
        "block_kind",
        "source_hash",
    }
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"unknown memory fields: {sorted(unknown)}")
    if not fields:
        return
    assignments = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [memory_id]
    conn.execute(f"UPDATE memories SET {assignments} WHERE id = ?", values)


def set_source_hash(conn: sqlite3.Connection, memory_id: str, digest: str) -> None:
    conn.execute("UPDATE memories SET source_hash = ? WHERE id = ?", (digest, memory_id))


def delete_missing_markdown_records(
    conn: sqlite3.Connection, *, existing_paths: Iterable[Path]
) -> int:
    """Mark Markdown records whose file vanished as orphans.

    This is deliberately conservative: called only for a full configured scan.
    """
    keep = {str(path) for path in existing_paths}
    rows = conn.execute(
        "SELECT id, source_ref FROM memories WHERE source_kind = 'markdown'"
    ).fetchall()
    changed = 0
    for row in rows:
        source_path = str(row["source_ref"]).rsplit(":", 1)[0]
        if source_path not in keep:
            conn.execute(
                "UPDATE memories SET status = 'orphan' WHERE id = ? AND status = 'active'",
                (row["id"],),
            )
            changed += 1
    return changed
