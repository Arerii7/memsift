from __future__ import annotations

from pathlib import Path

from ..models import Finding, MemoryRecord, now_ms, stable_id


def detect_orphans(records: list[MemoryRecord]) -> list[Finding]:
    findings: list[Finding] = []
    for record in records:
        if record.status in {"archived", "forgotten", "rejected"}:
            continue
        reason = ""
        if not record.source_present:
            reason = "The memory block is no longer present in its source file."
        elif not record.source_ref:
            reason = "No provenance: source reference is empty."
        elif record.source_kind == "opencode" and not (record.session_id and record.message_id):
            reason = "Imported from a session without session/message IDs."
        elif record.source_kind == "markdown":
            source_path = record.source_ref.rsplit(":", 1)[0]
            if not Path(source_path).expanduser().exists():
                reason = f"Source file no longer exists: {source_path}"
        if not reason:
            continue
        findings.append(
            Finding(
                id=stable_id("fd", "orphan", record.id),
                memory_id=record.id,
                kind="orphan",
                severity="medium",
                score=0.65,
                title=f"Orphan: {record.claim[:90]}",
                detail=reason,
                created_at=now_ms(),
            )
        )
    return findings
