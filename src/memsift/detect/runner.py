from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from .. import db
from ..config import Config
from ..models import Finding, MemoryRecord, now_ms
from .conflicts import detect_conflicts
from .duplicates import detect_duplicates
from .npm_scripts import detect_missing_scripts
from .orphans import detect_orphans
from .sensitive import detect_secrets
from .stale import detect_stale

_STATUS_PRIORITY = {
    "duplicate": 1,
    "stale": 2,
    "orphan": 3,
    "conflict": 4,
}


@dataclass(slots=True)
class DetectorReport:
    total: int = 0
    by_kind: dict[str, int] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    started_at: int = field(default_factory=now_ms)
    finished_at: int = field(default_factory=now_ms)

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "by_kind": dict(self.by_kind),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


def _status_for(findings: list[Finding]) -> dict[str, tuple[int, str]]:
    result: dict[str, tuple[int, str]] = {}
    for finding in findings:
        kind = finding.kind
        priority = _STATUS_PRIORITY.get(kind)
        if not priority:
            continue
        for memory_id in {finding.memory_id, finding.related_id}:
            if not memory_id:
                continue
            current = result.get(memory_id)
            if current is None or priority > current[0]:
                result[memory_id] = (priority, kind)
    return result


def run_detectors(conn: sqlite3.Connection, config: Config | None = None) -> DetectorReport:
    started = now_ms()
    cfg = config or Config.load()
    records = db.all_memories(conn)
    # Let the current scan decide issue statuses again; terminal choices survive.
    for record in records:
        if record.status in {"duplicate", "conflict", "stale", "orphan"}:
            db.update_memory_fields(conn, record.id, status="active")
    records = db.all_memories(conn)
    candidates: list[MemoryRecord] = [
        record for record in records if record.source_present and record.status not in {"archived", "forgotten", "rejected"}
    ]
    memories = [record for record in candidates if record.block_kind != "instruction_command"]

    db.prepare_findings(conn)
    detected: list[Finding] = []
    detected.extend(detect_duplicates(memories))
    detected.extend(detect_conflicts(memories))
    detected.extend(detect_stale(memories, ttl_days=cfg.ttl_days))
    detected.extend(detect_orphans([record for record in records if record.block_kind != "instruction_command"]))
    detected.extend(detect_secrets(candidates))
    detected.extend(detect_missing_scripts(candidates))

    findings: list[Finding] = []
    for finding in detected:
        db.insert_finding(conn, finding)
        current = db.get_finding(conn, finding.id)
        if current is not None and current.status == "open":
            findings.append(finding)
            if finding.kind in {"duplicate", "conflict"} and finding.related_id:
                db.add_link(
                    conn, finding.memory_id, finding.related_id, finding.kind, finding.score
                )

    terminal = {record.id for record in records if record.status in {"archived", "forgotten", "rejected"}}
    statuses = _status_for(findings)
    for memory_id, (_priority, status) in statuses.items():
        if memory_id not in terminal:
            db.update_memory_fields(conn, memory_id, status=status)

    secret_ids = {finding.memory_id for finding in detected if finding.kind == "secret"}
    for record in records:
        if record.id in secret_ids and record.sensitivity != "secret":
            db.update_memory_fields(conn, record.id, sensitivity="secret")

    report = DetectorReport(
        total=len(findings),
        by_kind=_counts(findings),
        findings=findings,
        started_at=started,
        finished_at=now_ms(),
    )
    db.record_detector_run(
        conn,
        started_at=report.started_at,
        finished_at=report.finished_at,
        stats=report.as_dict(),
    )
    return report


def _counts(findings: list[Finding]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.kind] = counts.get(finding.kind, 0) + 1
    return counts
