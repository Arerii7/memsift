from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

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


def test_anchor_fenced_memory_is_recognized_on_rescan(tmp_path: Path, cfg: Config) -> None:
    target = tmp_path / "MEMORY.md"
    target.write_text("```memory\nUse SQLite.\n```\n", encoding="utf-8")
    assert add_anchors(target, config=cfg, apply=True).count == 1
    records, blocks = parse_markdown_blocks(target, tmp_path)
    assert len(records) == 1
    assert records[0].claim == "Use SQLite."
    assert blocks[0].anchored


def test_anchor_backup_is_private_when_backup_parent_is_public(clean_project: Path, cfg: Config) -> None:
    import stat

    cfg.backups_dir.chmod(0o755)
    result = add_anchors(clean_project, config=cfg, apply=True)
    assert stat.S_IMODE(result.backup.stat().st_mode) == 0o700


def test_sync_commit_failure_restores_source(conn, cfg: Config, dirty_project: Path) -> None:
    import sqlite3

    class FailingCommit:
        def __getattr__(self, name):
            return getattr(conn, name)

        def commit(self):
            raise sqlite3.OperationalError("disk full")

    ingest_markdown(conn, [dirty_project], cfg)
    actions.archive_memory(conn, "ms_anchor_dup")
    conn.commit()
    target = dirty_project / "MEMORY.md"
    before = target.read_bytes()
    with pytest.raises(sqlite3.OperationalError):
        apply_sync(FailingCommit(), plan_sync(conn), cfg)
    assert target.read_bytes() == before


def test_rollback_refuses_to_discard_new_pending_edit(conn, cfg: Config, dirty_project: Path) -> None:
    ingest_markdown(conn, [dirty_project], cfg)
    actions.edit_memory(conn, "ms_anchor_dup", claim="First edit")
    conn.commit()
    result = apply_sync(conn, plan_sync(conn), cfg)
    actions.edit_memory(conn, "ms_anchor_dup", claim="Second edit")
    conn.commit()
    with pytest.raises(ValueError, match="pending"):
        rollback_event(conn, result.event_id)
    assert db.get_memory(conn, "ms_anchor_dup").claim == "Second edit"
    assert db.get_memory(conn, "ms_anchor_dup").sync_action == "update"


def test_sync_and_rollback_preserve_crlf_bytes(conn, cfg: Config, tmp_path: Path) -> None:
    target = tmp_path / "MEMORY.md"
    original = b"# Facts\r\n\r\n<!-- memsift:id=a -->\r\n- Old.\r\n<!-- /memsift:id=a -->\r\n\r\n- Keep.\r\n"
    target.write_bytes(original)
    ingest_markdown(conn, [target], cfg)
    actions.archive_memory(conn, "a")
    conn.commit()
    result = apply_sync(conn, plan_sync(conn), cfg)
    conn.commit()
    assert target.read_bytes() == b"# Facts\r\n\r\n- Keep.\r\n"
    rollback_event(conn, result.event_id)
    assert target.read_bytes() == original


def test_rollback_refuses_file_edited_after_sync(conn, cfg: Config, dirty_project: Path) -> None:
    ingest_markdown(conn, [dirty_project], cfg)
    actions.archive_memory(conn, "ms_anchor_dup")
    conn.commit()
    result = apply_sync(conn, plan_sync(conn), cfg)
    conn.commit()
    target = dirty_project / "MEMORY.md"
    edited = target.read_bytes() + b"Manual edit\n"
    target.write_bytes(edited)
    with pytest.raises(ValueError, match="changed"):
        rollback_event(conn, result.event_id)
    assert target.read_bytes() == edited


def test_failed_sync_restores_file_when_database_write_fails(conn, cfg: Config, dirty_project: Path) -> None:
    target = dirty_project / "MEMORY.md"
    original = target.read_bytes()
    ingest_markdown(conn, [dirty_project], cfg)
    actions.archive_memory(conn, "ms_anchor_dup")
    conn.commit()
    with patch("memsift.sync.db.upsert_source_file", side_effect=OSError("disk error")), pytest.raises(OSError):
        apply_sync(conn, plan_sync(conn), cfg)
    assert target.read_bytes() == original


def test_rollback_restores_memory_in_index(conn, cfg: Config, dirty_project: Path) -> None:
    ingest_markdown(conn, [dirty_project], cfg)
    actions.archive_memory(conn, "ms_anchor_dup")
    conn.commit()
    result = apply_sync(conn, plan_sync(conn), cfg)
    conn.commit()
    rollback_event(conn, result.event_id)
    conn.commit()
    ingest_markdown(conn, [dirty_project], cfg)
    assert db.get_memory(conn, "ms_anchor_dup").status == "active"


def test_rollback_restores_previous_edited_claim(conn, cfg: Config, tmp_path: Path) -> None:
    target = tmp_path / "MEMORY.md"
    original = b"<!-- memsift:id=a -->\r\n- Old.\r\n<!-- /memsift:id=a -->\r\n"
    target.write_bytes(original)
    ingest_markdown(conn, [target], cfg)
    actions.edit_memory(conn, "a", claim="New.")
    conn.commit()
    result = apply_sync(conn, plan_sync(conn), cfg)
    conn.commit()
    assert target.read_bytes() == original.replace(b"Old.", b"New.")
    rollback_event(conn, result.event_id)
    assert db.get_memory(conn, "a").claim == "Old."
    assert target.read_bytes() == original


def test_failed_sync_event_restores_file(conn, cfg: Config, dirty_project: Path) -> None:
    target = dirty_project / "MEMORY.md"
    original = target.read_bytes()
    ingest_markdown(conn, [dirty_project], cfg)
    actions.archive_memory(conn, "ms_anchor_dup")
    conn.commit()
    with patch("memsift.sync.db.insert_event", side_effect=OSError("disk error")), pytest.raises(OSError):
        apply_sync(conn, plan_sync(conn), cfg)
    assert target.read_bytes() == original


def test_sync_backup_directory_is_private(conn, cfg: Config, dirty_project: Path) -> None:
    cfg.backups_dir.chmod(0o755)
    ingest_markdown(conn, [dirty_project], cfg)
    actions.archive_memory(conn, "ms_anchor_dup")
    conn.commit()
    result = apply_sync(conn, plan_sync(conn), cfg)
    assert result.backup_dir.stat().st_mode & 0o777 == 0o700
