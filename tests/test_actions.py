from __future__ import annotations

from pathlib import Path

from memsift import actions, db
from memsift.config import Config
from memsift.detect import run_detectors
from memsift.ingest.markdown import ingest_markdown


def test_merge_archives_other_and_records_event(conn, cfg: Config, dirty_project: Path) -> None:
    ingest_markdown(conn, [dirty_project], cfg)
    records = [record for record in db.all_memories(conn) if "SQLite" in record.claim]
    canonical, other = records[0], records[1]
    merged, event_id = actions.merge_memories(
        conn, canonical.id, other.id, claim="We use SQLite 3 for the app database."
    )
    conn.commit()
    assert merged.claim == "We use SQLite 3 for the app database."
    assert merged.status == "active"
    assert merged.sync_action == "update"
    assert db.get_memory(conn, other.id).status == "archived"
    assert db.get_memory(conn, other.id).superseded_by == canonical.id
    event = db.get_event(conn, event_id)
    assert event is not None and event.action == "merge"


def test_archive_forget_pin_restore(conn, cfg: Config, dirty_project: Path) -> None:
    ingest_markdown(conn, [dirty_project], cfg)
    record = db.all_memories(conn)[0]
    actions.pin_memory(conn, record.id)
    assert db.get_memory(conn, record.id).pinned is True
    actions.archive_memory(conn, record.id)
    assert db.get_memory(conn, record.id).status == "archived"
    assert db.get_memory(conn, record.id).sync_action == "delete"
    actions.restore_memory(conn, record.id)
    assert db.get_memory(conn, record.id).status == "active"
    assert db.get_memory(conn, record.id).sync_action == "none"
    actions.forget_memory(conn, record.id)
    assert db.get_memory(conn, record.id).status == "forgotten"


def test_approve_and_reject_findings(conn, cfg: Config, dirty_project: Path) -> None:
    ingest_markdown(conn, [dirty_project], cfg)
    run_detectors(conn, cfg)
    findings = db.list_findings(conn)
    assert findings
    actions.approve_finding(conn, findings[0].id)
    assert db.get_finding(conn, findings[0].id).status == "resolved"
    actions.reject_finding(conn, findings[1].id)
    assert db.get_finding(conn, findings[1].id).status == "dismissed"
    report = run_detectors(conn, cfg)
    assert db.get_finding(conn, findings[1].id).status == "dismissed"
    assert findings[1].id not in {finding.id for finding in report.findings}


def test_supersede_points_old_to_new(conn, cfg: Config, dirty_project: Path) -> None:
    ingest_markdown(conn, [dirty_project], cfg)
    records = db.all_memories(conn)
    old, new = records[0], records[1]
    action_id = actions.supersede_memory(conn, old.id, new.id)
    assert db.get_memory(conn, old.id).superseded_by == new.id
    assert db.get_memory(conn, old.id).status == "archived"
    assert db.get_memory(conn, new.id).supersedes == old.id
    assert db.get_event(conn, action_id).action == "supersede"
