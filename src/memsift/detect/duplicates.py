from __future__ import annotations

from collections import defaultdict

from ..models import Finding, MemoryRecord, now_ms, stable_id
from ..normalize import jaccard, redact_text, token_set


def _canonical(items: list[MemoryRecord]) -> MemoryRecord:
    return max(items, key=lambda item: (item.pinned, item.created_at, item.confidence))


def _finding(record: MemoryRecord, canonical: MemoryRecord, score: float, reason: str) -> Finding:
    claim = redact_text(record.claim)[:100]
    return Finding(
        id=stable_id("fd", "duplicate", record.id, canonical.id),
        memory_id=record.id,
        related_id=canonical.id,
        kind="duplicate",
        severity="medium",
        score=round(score, 3),
        title=f"Duplicate: {claim}",
        detail=(
            f"{reason} Canonical candidate: {redact_text(canonical.claim)[:120]} "
            f"({canonical.source_ref})."
        ),
        created_at=now_ms(),
    )


def detect_duplicates(records: list[MemoryRecord]) -> list[Finding]:
    candidates = [record for record in records if record.status not in {"archived", "forgotten"}]
    findings: list[Finding] = []
    handled_pairs: set[tuple[str, str]] = set()

    by_norm: dict[str, list[MemoryRecord]] = defaultdict(list)
    for record in candidates:
        by_norm[record.norm_claim].append(record)

    for group in by_norm.values():
        if len(group) < 2:
            continue
        canonical = _canonical(group)
        for index, left in enumerate(group):
            for right in group[index + 1 :]:
                handled_pairs.add(tuple(sorted((left.id, right.id))))
        for record in group:
            if record.id == canonical.id:
                continue
            findings.append(_finding(record, canonical, 1.0, "Exact normalized claim match."))

    # Inverted index keeps near-duplicate comparison away from full O(n^2).
    index: dict[str, list[MemoryRecord]] = defaultdict(list)
    for record in candidates:
        for token in token_set(record.claim):
            index[token].append(record)

    seen: set[tuple[str, str]] = set()
    for _token, bucket in index.items():
        if len(bucket) < 2:
            continue
        for idx, left in enumerate(bucket):
            for right in bucket[idx + 1 :]:
                pair = tuple(sorted((left.id, right.id)))
                if pair in handled_pairs or pair in seen or left.id == right.id:
                    continue
                seen.add(pair)
                longest = max(len(left.claim), len(right.claim))
                if longest and min(len(left.claim), len(right.claim)) / longest < 0.45:
                    continue
                score = jaccard(left.claim, right.claim)
                if score < 0.8:
                    continue
                canonical = _canonical([left, right])
                record = right if canonical.id == left.id else left
                findings.append(
                    _finding(record, canonical, score, f"Near duplicate (Jaccard {score:.2f}).")
                )
    return findings
