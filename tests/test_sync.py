from __future__ import annotations

from pathlib import Path

import pytest

from memsift import actions, db
from memsift.anchor import add_anchors
from memsift.config import Config
from memsift.ingest.markdown import ingest_markdown, parse_markdown_blocks
from memsift.sync import apply_sync, plan_sync, rollback_event


def test_anchor_makes_blocks_writable(clean_project: Path, cfg: Config) -> None:
    target = clean_project / "MEMORY.md"
    before = target.read_text(encoding="utf-8")
    result = add_anchors(clean_project, config=cfg, apply=True)
    after = target.read_text(encoding="utf-8")
    assert result.count == 5
    assert after != before
    assert "<!-- memsift:id=ms_" in after
    _, blocks = parse_markdown_blocks(target, clean_project)
    assert len(blocks) == 5
    assert all(block.anchored for block in blocks)
    assert result.backup is not None
    assert result.backup.exists()


def test_archive_apply_and_rollback_restores_bytes(
    conn, cfg: Config, dirty_project: Path
) -> None:
    add_anchors(dirty_project, config=cfg, apply=True)
    ingest_markdown(conn, [dirty_project], cfg)
    record = next(item for item in db.all_memories(conn) if item.id == "ms_anchor_dup")
    before = (dirty_project / "MEMORY.md").read_text(encoding="utf-8")
    actions.archive_memory(conn, record.id)
    conn.commit()

    plan = plan_sync(conn)
    assert plan.changed
    assert "ms_anchor_dup" in plan.memory_ids
    result = apply_sync(conn, plan, cfg)
    conn.commit()
    after = (dirty_project / "MEMORY.md").read_text(encoding="utf-8")
    assert "ms_anchor_dup" not in after
    assert "We use SQLite for the app database." in after
    assert result.backup_dir.exists()
    assert db.get_memory(conn, record.id).sync_action == "none"

    rollback_event(conn, result.event_id)
    conn.commit()
    assert (dirty_project / "MEMORY.md").read_text(encoding="utf-8") == before


def test_update_block_writes_new_claim(conn, cfg: Config, dirty_project: Path) -> None:
    add_anchors(dirty_project, config=cfg, apply=True)
    ingest_markdown(conn, [dirty_project], cfg)
    record = next(item for item in db.all_memories(conn) if item.claim == "Auth is Clerk.")
    actions.edit_memory(conn, record.id, claim="Auth is Clerk 2.")
    conn.commit()
    plan = plan_sync(conn)
    assert plan.changed
    apply_sync(conn, plan, cfg)
    conn.commit()
    text = (dirty_project / "MEMORY.md").read_text(encoding="utf-8")
    assert "Auth is Clerk 2." in text
    assert "Auth is Clerk." not in text


def test_unanchored_record_is_skipped(conn, cfg: Config, dirty_project: Path) -> None:
    ingest_markdown(conn, [dirty_project], cfg)
    record = next(item for item in db.all_memories(conn) if item.id != "ms_anchor_dup")
    actions.archive_memory(conn, record.id)
    conn.commit()
    plan = plan_sync(conn)
    assert not plan.changed
    assert any("no writable anchor" in item for item in plan.skipped)


def test_apply_without_changes_raises(conn, cfg: Config) -> None:
    plan = plan_sync(conn)
    try:
        apply_sync(conn, plan, cfg)
    except ValueError as exc:
        assert "nothing to sync" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_sync_refuses_file_changed_after_preview(conn, cfg: Config, dirty_project: Path) -> None:
    ingest_markdown(conn, [dirty_project], cfg)
    actions.archive_memory(conn, "ms_anchor_dup")
    conn.commit()
    plan = plan_sync(conn)
    target = dirty_project / "MEMORY.md"
    edited = target.read_text(encoding="utf-8") + "\nA later manual edit.\n"
    target.write_text(edited, encoding="utf-8")

    with pytest.raises(ValueError, match="changed"):
        apply_sync(conn, plan, cfg)

    assert target.read_text(encoding="utf-8") == edited
    assert db.get_memory(conn, "ms_anchor_dup").sync_action == "delete"


def test_sync_skips_file_edited_since_scan(conn, cfg: Config, dirty_project: Path) -> None:
    ingest_markdown(conn, [dirty_project], cfg)
    actions.archive_memory(conn, "ms_anchor_dup")
    target = dirty_project / "MEMORY.md"
    edited = target.read_text(encoding="utf-8").replace(
        "We use SQLite for the app database.", "We use Postgres for the app database."
    )
    target.write_text(edited, encoding="utf-8")

    plan = plan_sync(conn)

    assert not plan.changed
    assert any("changed since" in message for message in plan.skipped)
    assert target.read_text(encoding="utf-8") == edited
