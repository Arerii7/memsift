from __future__ import annotations

from pathlib import Path

from memsift import db
from memsift.config import Config
from memsift.detect import run_detectors
from memsift.ingest.markdown import ingest_markdown, parse_markdown
from memsift.models import MemoryRecord, now_ms
from memsift.normalize import normalize_claim


def test_markdown_parse_preserves_provenance(dirty_project: Path) -> None:
    path = dirty_project / "MEMORY.md"
    records = parse_markdown(path, dirty_project)
    assert len(records) == 10
    anchor = next(record for record in records if record.id == "ms_anchor_dup")
    assert anchor.claim == "We use SQLite for the app database."
    assert anchor.source_ref.endswith("MEMORY.md:19")
    assert anchor.topic_key == "stack/database"
    assert "We use Postgres" in records[0].claim
    assert all(record.scope.startswith("project:") for record in records)


def test_rescan_is_idempotent(conn, cfg: Config, dirty_project: Path) -> None:
    first = ingest_markdown(conn, [dirty_project], cfg, mark_missing=True)
    first_ids = {record.id for record in db.all_memories(conn)}
    second = ingest_markdown(conn, [dirty_project], cfg, mark_missing=True)
    second_ids = {record.id for record in db.all_memories(conn)}
    assert first.records == second.records == 10
    assert first_ids == second_ids
    assert len(second_ids) == 10


def test_full_text_search(conn, cfg: Config, dirty_project: Path) -> None:
    ingest_markdown(conn, [dirty_project], cfg)
    results = db.search_memories(conn, "Postgres")
    assert results
    assert any("Postgres" in record.claim for record in results)


def test_dirty_fixture_finds_expected_kinds(conn, cfg: Config, dirty_project: Path) -> None:
    ingest_markdown(conn, [dirty_project], cfg)
    report = run_detectors(conn, cfg)
    assert report.by_kind["duplicate"] >= 2
    assert report.by_kind["conflict"] >= 2
    assert report.by_kind["stale"] == 1
    assert report.by_kind["secret"] == 1


def test_clean_fixture_has_no_findings(conn, cfg: Config, clean_project: Path) -> None:
    ingest_markdown(conn, [clean_project], cfg)
    report = run_detectors(conn, cfg)
    assert report.total == 0, report.by_kind


def test_missing_source_becomes_orphan(conn, cfg: Config, tmp_path: Path) -> None:
    missing = tmp_path / "gone.md"
    record = MemoryRecord(
        id="ms_orphan_test",
        claim="This came from nowhere.",
        norm_claim=normalize_claim("This came from nowhere."),
        body="This came from nowhere.",
        topic_key=None,
        scope=f"project:{tmp_path}",
        source_kind="markdown",
        source_ref=f"{missing}:1",
        source_hash="abc",
        created_at=now_ms(),
        updated_at=now_ms(),
        last_seen_at=now_ms(),
        confidence=0.5,
    )
    db.upsert_memory(conn, record)
    report = run_detectors(conn, cfg)
    assert report.by_kind.get("orphan") == 1


def test_terminal_status_survives_rescan(conn, cfg: Config, dirty_project: Path) -> None:
    ingest_markdown(conn, [dirty_project], cfg)
    record = next(item for item in db.all_memories(conn) if item.id == "ms_anchor_dup")
    from memsift import actions

    actions.archive_memory(conn, record.id)
    conn.commit()
    ingest_markdown(conn, [dirty_project], cfg)
    assert db.get_memory(conn, record.id).status == "archived"


def test_rescan_marks_removed_block_as_orphan_without_false_conflict(conn, cfg: Config, tmp_path: Path) -> None:
    source = tmp_path / "MEMORY.md"
    source.write_text("- We use SQLite.\n")
    ingest_markdown(conn, [tmp_path], cfg)
    previous = db.all_memories(conn)[0]
    source.write_text("- We use Postgres.\n")
    ingest_markdown(conn, [tmp_path], cfg)
    report = run_detectors(conn, cfg)
    assert not [f for f in report.findings if f.kind == "conflict"]
    assert db.get_memory(conn, previous.id).status == "orphan"
    assert any(record.claim == "We use Postgres." for record in db.all_memories(conn))


def test_same_memory_in_two_projects_keeps_separate_sources(conn, cfg: Config, tmp_path: Path) -> None:
    roots = [tmp_path / "first", tmp_path / "second"]
    for root in roots:
        root.mkdir()
        (root / "MEMORY.md").write_text("- We use SQLite.\n")
    ingest_markdown(conn, roots, cfg)
    records = db.all_memories(conn)
    assert len(records) == 2
    assert {record.scope for record in records} == {f"project:{root}" for root in roots}
    ids = {record.id for record in records}
    first = next(record for record in records if record.scope == f"project:{roots[0]}")
    db.update_memory_fields(conn, first.id, status="archived", sync_action="delete")
    ingest_markdown(conn, roots, cfg)
    assert {record.id for record in db.all_memories(conn)} == ids
    assert db.get_memory(conn, first.id).status == "archived"
    assert db.get_memory(conn, first.id).sync_action == "delete"


def test_deleted_pending_update_is_retained_and_marked_orphan(conn, cfg: Config, tmp_path: Path) -> None:
    from memsift import actions

    source = tmp_path / "MEMORY.md"
    source.write_text("- We use SQLite.\n")
    ingest_markdown(conn, [tmp_path], cfg)
    record = db.all_memories(conn)[0]
    actions.edit_memory(conn, record.id, claim="Use a new database.")
    source.write_text("- We use Postgres.\n")
    ingest_markdown(conn, [tmp_path], cfg)
    run_detectors(conn, cfg)
    retained = db.get_memory(conn, record.id)
    assert retained.claim == "Use a new database."
    assert retained.sync_action == "update"
    assert retained.status == "orphan"


def test_duplicate_anchor_id_does_not_overwrite_other_project(conn, cfg: Config, tmp_path: Path) -> None:
    roots = [tmp_path / "first", tmp_path / "second"]
    for root in roots:
        root.mkdir()
        (root / "MEMORY.md").write_text("<!-- memsift:id=ms_same -->\n- Fact.\n<!-- /memsift:id=ms_same -->\n")
    ingest_markdown(conn, [roots[0]], cfg)
    stats = ingest_markdown(conn, [roots[1]], cfg)
    assert stats.errors
    assert db.get_memory(conn, "ms_same").source_ref.startswith(str(roots[0]))


def test_restored_block_keeps_id_and_pending_edit(conn, cfg: Config, tmp_path: Path) -> None:
    from memsift import actions

    source = tmp_path / "MEMORY.md"
    source.write_text("- We use SQLite.\n")
    ingest_markdown(conn, [tmp_path], cfg)
    record = db.all_memories(conn)[0]
    actions.edit_memory(conn, record.id, claim="Use a new database.")
    source.write_text("- We use Postgres.\n")
    ingest_markdown(conn, [tmp_path], cfg)
    source.write_text("- We use SQLite.\n")
    ingest_markdown(conn, [tmp_path], cfg)
    restored = db.get_memory(conn, record.id)
    assert restored.source_present
    assert restored.claim == "Use a new database."
    assert restored.sync_action == "update"
    assert restored.status == "active"


def test_existing_database_migrates_without_changing_record(tmp_path: Path) -> None:
    import sqlite3

    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.executescript(db.SCHEMA)
    connection.execute(
        "INSERT INTO memories (id, claim, norm_claim, body, scope, source_kind, source_ref, "
        "source_hash, created_at, updated_at, last_seen_at, confidence, status, sync_action) "
        "VALUES ('old', 'old claim', 'old', 'old body', 'project:/tmp', 'markdown', "
        "'/tmp/MEMORY.md:1', 'hash', 1, 1, 1, 0.5, 'archived', 'delete')"
    )
    connection.commit()
    connection.close()
    connection = db.connect(path)
    try:
        record = db.get_memory(connection, "old")
        assert record.source_present
        assert record.status == "archived"
        assert record.sync_action == "delete"
    finally:
        connection.close()


def test_moved_anchor_keeps_identity_and_pending_action(conn, cfg: Config, tmp_path: Path) -> None:
    from memsift import actions

    first = tmp_path / "A.md"
    second = tmp_path / "B.md"
    anchored = "<!-- memsift:id=ms_move -->\n- A fact.\n<!-- /memsift:id=ms_move -->\n"
    first.write_text(anchored)
    ingest_markdown(conn, [tmp_path], cfg)
    actions.archive_memory(conn, "ms_move")
    second.write_text(anchored)
    first.write_text("# Empty\n")
    stats = ingest_markdown(conn, [second, first], cfg)
    assert not stats.errors
    moved = db.get_memory(conn, "ms_move")
    assert moved.source_ref.startswith(str(second))
    assert moved.status == "archived"
    assert moved.sync_action == "delete"
    assert moved.source_present


def test_renamed_anchored_file_is_reconciled(conn, cfg: Config, tmp_path: Path) -> None:
    first = tmp_path / "A.md"
    second = tmp_path / "B.md"
    first.write_text("<!-- memsift:id=ms_move -->\n- A fact.\n<!-- /memsift:id=ms_move -->\n")
    ingest_markdown(conn, [tmp_path], cfg)
    first.rename(second)
    stats = ingest_markdown(conn, [tmp_path], cfg)
    assert not stats.errors
    assert db.get_memory(conn, "ms_move").source_ref.startswith(str(second))


def test_removed_duplicate_does_not_reassign_archived_decision(conn, cfg: Config, tmp_path: Path) -> None:
    from memsift import actions

    source = tmp_path / "MEMORY.md"
    source.write_text("- Same fact.\n- Same fact.\n")
    ingest_markdown(conn, [tmp_path], cfg)
    records = sorted(db.all_memories(conn), key=lambda record: record.source_ref)
    actions.archive_memory(conn, records[0].id)
    source.write_text("- Same fact.\n")
    stats = ingest_markdown(conn, [tmp_path], cfg)
    assert stats.errors
    assert db.get_memory(conn, records[0].id).status == "archived"
    assert db.get_memory(conn, records[0].id).sync_action == "delete"
    assert not db.get_memory(conn, records[0].id).source_present
    assert not db.get_memory(conn, records[1].id).source_present
    assert not [r for r in db.all_memories(conn) if r.source_present]
    assert ingest_markdown(conn, [tmp_path], cfg).errors
    source.write_text("<!-- memsift:id=fresh -->\n- Same fact.\n<!-- /memsift:id=fresh -->\n")
    assert not ingest_markdown(conn, [tmp_path], cfg).errors
    assert db.get_memory(conn, "fresh").status == "active"
    assert db.get_memory(conn, records[0].id).status == "archived"


def test_removed_duplicate_does_not_reassign_pending_edit(conn, cfg: Config, tmp_path: Path) -> None:
    from memsift import actions

    source = tmp_path / "MEMORY.md"
    source.write_text("- Same fact.\n- Same fact.\n")
    ingest_markdown(conn, [tmp_path], cfg)
    records = sorted(db.all_memories(conn), key=lambda record: record.source_ref)
    actions.edit_memory(conn, records[0].id, claim="Edited fact.")
    source.write_text("- Same fact.\n")
    stats = ingest_markdown(conn, [tmp_path], cfg)
    assert stats.errors
    assert db.get_memory(conn, records[0].id).claim == "Edited fact."
    assert db.get_memory(conn, records[0].id).sync_action == "update"
    assert not db.get_memory(conn, records[0].id).source_present
