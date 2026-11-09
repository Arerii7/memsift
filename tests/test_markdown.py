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
