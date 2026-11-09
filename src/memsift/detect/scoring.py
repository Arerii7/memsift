from __future__ import annotations

from ..models import MemoryRecord
from ..normalize import score_confidence


def refresh_confidence(record: MemoryRecord) -> float:
    return score_confidence(
        source_kind=record.source_kind,
        claim=record.claim,
        explicit=record.source_kind == "opencode" or bool(record.tags),
        pinned=record.pinned,
        topic_key=record.topic_key,
        files=record.files,
        created_at=record.created_at,
    )
