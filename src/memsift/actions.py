from __future__ import annotations

import sqlite3
from typing import Any

from . import db
from .models import MemoryRecord, now_ms
from .normalize import (
    extract_file_refs,
    infer_topic,
    normalize_claim,
    redact_text,
    score_confidence,
    sensitivity_for,
)


def snapshot(record: MemoryRecord) -> dict[str, Any]:
    secret = record.sensitivity == "secret"
    return {
        "id": record.id,
        "claim": redact_text(record.claim) if secret else record.claim,
        "body": redact_text(record.body) if secret else record.body,
        "topic_key": record.topic_key,
        "scope": record.scope,
        "status": record.status,
        "pinned": record.pinned,
        "sync_action": record.sync_action,
        "superseded_by": record.superseded_by,
        "sensitivity": record.sensitivity,
    }


def get_or_raise(conn: sqlite3.Connection, memory_id: str) -> MemoryRecord:
    record = db.get_memory(conn, memory_id)
    if record is None:
        raise ValueError(f"memory not found: {memory_id}")
    return record


def _format_claim(kind: str, claim: str) -> str:
    if kind == "bullet":
        return f"- {claim}"
    if kind == "quote":
        return f"> {claim}"
    return claim


def _sync_delete_action(record: MemoryRecord) -> str:
    return "delete" if record.source_kind == "markdown" else "none"


def archive_memory(
    conn: sqlite3.Connection, memory_id: str, *, actor: str = "user", note: str = ""
) -> str:
    record = get_or_raise(conn, memory_id)
    before = snapshot(record)
    db.update_memory_fields(
        conn,
        memory_id,
        status="archived",
        sync_action=_sync_delete_action(record),
        updated_at=now_ms(),
    )
    return db.insert_event(
        conn,
        memory_id=memory_id,
        action="archive",
        actor=actor,
        before=before,
        after={"status": "archived", "sync_action": _sync_delete_action(record)},
        note=note,
    )


def forget_memory(
    conn: sqlite3.Connection, memory_id: str, *, actor: str = "user", note: str = ""
) -> str:
    record = get_or_raise(conn, memory_id)
    before = snapshot(record)
    db.update_memory_fields(
        conn,
        memory_id,
        status="forgotten",
        sync_action=_sync_delete_action(record),
        updated_at=now_ms(),
    )
    return db.insert_event(
        conn,
        memory_id=memory_id,
        action="forget",
        actor=actor,
        before=before,
        after={"status": "forgotten", "sync_action": _sync_delete_action(record)},
        note=note,
    )


def pin_memory(conn: sqlite3.Connection, memory_id: str, *, actor: str = "user") -> str:
    record = get_or_raise(conn, memory_id)
    before = snapshot(record)
    db.update_memory_fields(conn, memory_id, pinned=1, updated_at=now_ms())
    return db.insert_event(
        conn,
        memory_id=memory_id,
        action="pin",
        actor=actor,
        before=before,
        after={"pinned": True},
    )


def restore_memory(conn: sqlite3.Connection, memory_id: str, *, actor: str = "user") -> str:
    record = get_or_raise(conn, memory_id)
    before = snapshot(record)
    db.update_memory_fields(
        conn,
        memory_id,
        status="active",
        sync_action="none",
        superseded_by=None,
        updated_at=now_ms(),
    )
    return db.insert_event(
        conn,
        memory_id=memory_id,
        action="restore",
        actor=actor,
        before=before,
        after={"status": "active", "sync_action": "none"},
        note="Restored database status. If the source block was already removed, restore from a backup.",
    )


def edit_memory(
    conn: sqlite3.Connection,
    memory_id: str,
    *,
    claim: str | None = None,
    body: str | None = None,
    actor: str = "user",
) -> str:
    record = get_or_raise(conn, memory_id)
    before = snapshot(record)
    new_claim = (claim if claim is not None else record.claim).strip()
    new_body = body if body is not None else _format_claim(record.block_kind, new_claim)
    if claim is not None and body is None:
        new_body = _format_claim(record.block_kind, new_claim)
    files = extract_file_refs(new_body)
    topic = infer_topic(new_body)
    sensitivity = sensitivity_for(new_body)
    confidence = score_confidence(
        source_kind=record.source_kind,
        claim=new_claim,
        explicit=True,
        pinned=record.pinned,
        topic_key=topic,
        files=files,
        created_at=record.created_at,
    )
    db.update_memory_fields(
        conn,
        memory_id,
        claim=new_claim,
        norm_claim=normalize_claim(new_claim),
        body=new_body,
        topic_key=topic,
        files_json=__import__("json").dumps(files),
        sensitivity=sensitivity,
        confidence=confidence,
        status="active",
        sync_action="update" if record.source_kind == "markdown" else "none",
        updated_at=now_ms(),
    )
    return db.insert_event(
        conn,
        memory_id=memory_id,
        action="edit",
        actor=actor,
        before=before,
        after=snapshot(get_or_raise(conn, memory_id)),
    )


def merge_memories(
    conn: sqlite3.Connection,
    canonical_id: str,
    other_id: str,
    *,
    claim: str | None = None,
    actor: str = "user",
) -> tuple[MemoryRecord, str]:
    if canonical_id == other_id:
        raise ValueError("cannot merge a memory with itself")
    canonical = get_or_raise(conn, canonical_id)
    other = get_or_raise(conn, other_id)
    before_canonical = snapshot(canonical)
    before_other = snapshot(other)
    new_claim = (claim or canonical.claim).strip()
    new_body = _format_claim(canonical.block_kind, new_claim)
    files = extract_file_refs(new_body)
    topic = infer_topic(new_body)
    confidence = max(
        canonical.confidence,
        score_confidence(
            source_kind=canonical.source_kind,
            claim=new_claim,
            explicit=True,
            pinned=canonical.pinned,
            topic_key=topic,
            files=files,
            created_at=canonical.created_at,
        ),
    )
    db.update_memory_fields(
        conn,
        canonical_id,
        claim=new_claim,
        norm_claim=normalize_claim(new_claim),
        body=new_body,
        topic_key=topic,
        files_json=__import__("json").dumps(files),
        sensitivity=sensitivity_for(new_body),
        confidence=confidence,
        status="active",
        sync_action="update" if canonical.source_kind == "markdown" else "none",
        updated_at=now_ms(),
    )
    db.update_memory_fields(
        conn,
        other_id,
        status="archived",
        superseded_by=canonical_id,
        sync_action=_sync_delete_action(other),
        updated_at=now_ms(),
    )
    conn.execute(
        "UPDATE findings SET status = 'resolved' WHERE (memory_id IN (?, ?) OR related_id IN (?, ?))",
        (canonical_id, other_id, canonical_id, other_id),
    )
    event_id = db.insert_event(
        conn,
        memory_id=canonical_id,
        action="merge",
        actor=actor,
        before={"canonical": before_canonical, "other": before_other},
        after={"canonical": snapshot(get_or_raise(conn, canonical_id)), "merged_id": other_id},
        note="Merged and archived the non-canonical record.",
    )
    return get_or_raise(conn, canonical_id), event_id


def supersede_memory(
    conn: sqlite3.Connection,
    old_id: str,
    new_id: str,
    *,
    actor: str = "user",
) -> str:
    if old_id == new_id:
        raise ValueError("cannot supersede a memory with itself")
    old = get_or_raise(conn, old_id)
    new = get_or_raise(conn, new_id)
    before = {"old": snapshot(old), "new": snapshot(new)}
    db.update_memory_fields(
        conn,
        old_id,
        status="archived",
        superseded_by=new_id,
        sync_action=_sync_delete_action(old),
        updated_at=now_ms(),
    )
    db.update_memory_fields(conn, new_id, supersedes=old_id, status="active", updated_at=now_ms())
    conn.execute(
        "UPDATE findings SET status = 'resolved' WHERE (memory_id IN (?, ?) OR related_id IN (?, ?))",
        (old_id, new_id, old_id, new_id),
    )
    return db.insert_event(
        conn,
        memory_id=old_id,
        action="supersede",
        actor=actor,
        before=before,
        after={"old_status": "archived", "superseded_by": new_id},
    )


def approve_finding(
    conn: sqlite3.Connection, finding_id: str, *, actor: str = "user"
) -> str:
    finding = db.get_finding(conn, finding_id)
    if finding is None:
        raise ValueError(f"finding not found: {finding_id}")
    db.resolve_finding(conn, finding_id, "resolved")
    return db.insert_event(
        conn,
        memory_id=finding.memory_id,
        action="approve",
        actor=actor,
        before={"finding": finding_id, "kind": finding.kind, "status": finding.status},
        after={"finding_status": "resolved"},
        note=f"Approved {finding.kind} finding.",
    )


def reject_finding(conn: sqlite3.Connection, finding_id: str, *, actor: str = "user") -> str:
    finding = db.get_finding(conn, finding_id)
    if finding is None:
        raise ValueError(f"finding not found: {finding_id}")
    db.resolve_finding(conn, finding_id, "dismissed")
    record = db.get_memory(conn, finding.memory_id)
    if record and record.status == finding.kind:
        db.update_memory_fields(conn, record.id, status="active")
    if finding.related_id:
        related = db.get_memory(conn, finding.related_id)
        if related and related.status == finding.kind:
            db.update_memory_fields(conn, related.id, status="active")
    return db.insert_event(
        conn,
        memory_id=finding.memory_id,
        action="reject",
        actor=actor,
        before={"finding": finding_id, "kind": finding.kind, "status": finding.status},
        after={"finding_status": "dismissed"},
        note=f"Dismissed {finding.kind} finding as a false positive.",
    )
