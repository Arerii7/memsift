from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any

TERMINAL_STATUSES = {"archived", "rejected", "forgotten"}
ISSUE_STATUSES = {"duplicate", "conflict", "stale", "orphan"}


def now_ms() -> int:
    return int(time.time() * 1000)


def stable_id(prefix: str, *parts: object) -> str:
    digest = hashlib.sha256("\x1f".join(str(p) for p in parts).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:16]}"


def json_list(value: list[str] | None) -> str:
    return json.dumps(value or [], ensure_ascii=False)


def parse_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(item) for item in data] if isinstance(data, list) else []


@dataclass(slots=True)
class MemoryRecord:
    id: str
    claim: str
    norm_claim: str
    body: str
    topic_key: str | None
    scope: str
    source_kind: str
    source_ref: str
    source_hash: str
    session_id: str | None = None
    message_id: str | None = None
    created_at: int = field(default_factory=now_ms)
    updated_at: int = field(default_factory=now_ms)
    last_seen_at: int = field(default_factory=now_ms)
    confidence: float = 0.7
    status: str = "active"
    supersedes: str | None = None
    superseded_by: str | None = None
    files: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    sensitivity: str = "normal"
    pinned: bool = False
    sync_action: str = "none"
    block_kind: str = "paragraph"
    source_present: bool = True

    def to_row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "claim": self.claim,
            "norm_claim": self.norm_claim,
            "body": self.body,
            "topic_key": self.topic_key,
            "scope": self.scope,
            "source_kind": self.source_kind,
            "source_ref": self.source_ref,
            "source_hash": self.source_hash,
            "session_id": self.session_id,
            "message_id": self.message_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_seen_at": self.last_seen_at,
            "confidence": self.confidence,
            "status": self.status,
            "supersedes": self.supersedes,
            "superseded_by": self.superseded_by,
            "files_json": json_list(self.files),
            "tags_json": json_list(self.tags),
            "sensitivity": self.sensitivity,
            "pinned": int(self.pinned),
            "sync_action": self.sync_action,
            "block_kind": self.block_kind,
            "source_present": int(self.source_present),
        }

    @classmethod
    def from_row(cls, row: Any) -> MemoryRecord:
        return cls(
            id=row["id"],
            claim=row["claim"],
            norm_claim=row["norm_claim"],
            body=row["body"],
            topic_key=row["topic_key"],
            scope=row["scope"],
            source_kind=row["source_kind"],
            source_ref=row["source_ref"],
            source_hash=row["source_hash"],
            session_id=row["session_id"],
            message_id=row["message_id"],
            created_at=int(row["created_at"]),
            updated_at=int(row["updated_at"]),
            last_seen_at=int(row["last_seen_at"]),
            confidence=float(row["confidence"]),
            status=row["status"],
            supersedes=row["supersedes"],
            superseded_by=row["superseded_by"],
            files=parse_json_list(row["files_json"]),
            tags=parse_json_list(row["tags_json"]),
            sensitivity=row["sensitivity"],
            pinned=bool(row["pinned"]),
            sync_action=row["sync_action"],
            block_kind=row["block_kind"],
            source_present=bool(row["source_present"]),
        )


@dataclass(slots=True)
class Finding:
    id: str
    memory_id: str
    kind: str
    severity: str
    score: float
    title: str
    detail: str = ""
    related_id: str | None = None
    status: str = "open"
    created_at: int = field(default_factory=now_ms)


@dataclass(slots=True)
class Event:
    id: str
    memory_id: str | None
    action: str
    actor: str
    at: int = field(default_factory=now_ms)
    before_json: str = "{}"
    after_json: str = "{}"
    note: str = ""
