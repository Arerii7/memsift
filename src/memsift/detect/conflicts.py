from __future__ import annotations

from collections import defaultdict

from ..models import Finding, MemoryRecord, now_ms, stable_id
from ..normalize import date_only, jaccard, redact_text


def detect_conflicts(records: list[MemoryRecord]) -> list[Finding]:
    groups: dict[tuple[str, str], list[MemoryRecord]] = defaultdict(list)
    for record in records:
        if record.status in {"archived", "forgotten", "rejected"}:
            continue
        if not record.topic_key:
            continue
        groups[(record.scope, record.topic_key)].append(record)

    findings: list[Finding] = []
    for (scope, topic), group in groups.items():
        if len(group) < 2:
            continue
        for index, left in enumerate(group):
            for right in group[index + 1 :]:
                if left.norm_claim == right.norm_claim:
                    continue
                if jaccard(left.claim, right.claim) >= 0.8:
                    # Wording variants belong in the duplicate queue, not conflict.
                    continue
                older, newer = sorted((left, right), key=lambda item: item.created_at)
                newer = right if older.id == left.id else left
                older = left if older.id == left.id else right
                if older.created_at == newer.created_at:
                    older, newer = sorted((left, right), key=lambda item: item.id)
                findings.append(
                    Finding(
                        id=stable_id("fd", "conflict", topic, older.id, newer.id),
                        memory_id=older.id,
                        related_id=newer.id,
                        kind="conflict",
                        severity="high",
                        score=0.9,
                        title=f"Conflict on {topic}: {redact_text(older.claim)[:70]}",
                        detail=(
                            f"{topic}: \"{redact_text(older.claim)[:160]}\" "
                            f"({date_only(older.created_at)}) vs "
                            f"\"{redact_text(newer.claim)[:160]}\" "
                            f"({date_only(newer.created_at)}). Scope: {scope}."
                        ),
                        created_at=now_ms(),
                    )
                )
    return findings
