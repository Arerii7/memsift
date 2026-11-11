from __future__ import annotations

import hashlib
from pathlib import Path

from memsift import db
from memsift.config import Config, project_scope
from memsift.ingest.opencode import extract_markers, ingest_opencode


def test_extract_markers_only_explicit() -> None:
    text = (
        "The weather is nice.\n"
        "remember: Use Postgres.\n"
        "Decision: use SQLite.\n"
        "```memory\n"
        "preference: dark mode\n"
        "plain inside fence\n"
        "```\n"
    )
    assert extract_markers(text) == [
        ("remember", "Use Postgres."),
        ("decision", "use SQLite."),
        ("preference", "dark mode"),
        ("memory", "plain inside fence"),
    ]


def test_opencode_import_is_read_only_and_project_scoped(
    conn, cfg: Config, opencode_db: Path
) -> None:
    before = hashlib.sha256(opencode_db.read_bytes()).hexdigest()
    stats = ingest_opencode(conn, opencode_db=opencode_db, project=Path("/tmp/project"), config=cfg)
    conn.commit()
    after = hashlib.sha256(opencode_db.read_bytes()).hexdigest()
    assert stats.records == 3
    assert stats.errors == []
    assert before == after
    records = db.all_memories(conn)
    assert len(records) == 3
    assert {record.claim for record in records} == {
        "Use Postgres for the database.",
        "use SQLite.",
        "Auth is Clerk.",
    }
    assert all(record.session_id for record in records)
    assert all(record.message_id for record in records)
    assert all(record.scope == project_scope(Path("/tmp/project")) for record in records)
    assert all("other project" not in record.claim for record in records)


def test_opencode_import_is_idempotent(conn, cfg: Config, opencode_db: Path) -> None:
    ingest_opencode(conn, opencode_db=opencode_db, project=Path("/tmp/project"), config=cfg)
    first = {record.id for record in db.all_memories(conn)}
    ingest_opencode(conn, opencode_db=opencode_db, project=Path("/tmp/project"), config=cfg)
    second = {record.id for record in db.all_memories(conn)}
    assert first == second
    assert len(second) == 3


def test_opencode_import_matches_symlinked_project(
    conn, cfg: Config, opencode_db: Path, tmp_path: Path
) -> None:
    link = tmp_path / "linked-project"
    link.symlink_to("/tmp/project")
    stats = ingest_opencode(conn, opencode_db=opencode_db, project=link, config=cfg)
    conn.commit()
    assert stats.records == 3
