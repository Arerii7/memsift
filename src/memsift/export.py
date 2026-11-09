from __future__ import annotations

import json
import sqlite3
from typing import Any

from . import db
from .models import MemoryRecord
from .normalize import redact_text


def _clean_records(conn: sqlite3.Connection, scope: str | None = None) -> list[MemoryRecord]:
    records = db.list_memories(conn, scope=scope, limit=10_000)
    return [
        record
        for record in records
        if record.status == "active" and record.sensitivity != "secret"
    ]


def export_markdown(conn: sqlite3.Connection, scope: str | None = None) -> str:
    records = _clean_records(conn, scope)
    lines = [
        "# memsift memory export",
        "",
        f"<!-- {len(records)} active, non-secret record(s) -->",
        "",
    ]
    by_topic: dict[str, list[MemoryRecord]] = {}
    for record in records:
        by_topic.setdefault(record.topic_key or "uncategorized", []).append(record)
    for topic in sorted(by_topic):
        lines.append(f"## {topic}")
        lines.append("")
        for record in sorted(by_topic[topic], key=lambda item: (item.created_at, item.id)):
            lines.append(f"<!-- memsift:id={record.id} -->")
            if record.block_kind == "bullet":
                lines.append(f"- {record.claim}")
            else:
                lines.append(record.claim)
            lines.append(f"<!-- /memsift:id={record.id} -->")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def export_json(conn: sqlite3.Connection, scope: str | None = None) -> str:
    payload: list[dict[str, Any]] = []
    for record in _clean_records(conn, scope):
        payload.append(
            {
                "id": record.id,
                "claim": redact_text(record.claim),
                "body": redact_text(record.body),
                "topic_key": record.topic_key,
                "scope": record.scope,
                "source_kind": record.source_kind,
                "source_ref": record.source_ref,
                "created_at": record.created_at,
                "updated_at": record.updated_at,
                "confidence": record.confidence,
                "status": record.status,
                "files": record.files,
                "tags": record.tags,
            }
        )
    return json.dumps(payload, ensure_ascii=False, indent=2)
