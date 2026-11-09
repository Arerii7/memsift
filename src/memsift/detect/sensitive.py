from __future__ import annotations

from ..models import Finding, MemoryRecord, now_ms, stable_id
from ..normalize import secret_matches


def detect_secrets(records: list[MemoryRecord]) -> list[Finding]:
    findings: list[Finding] = []
    for record in records:
        if record.status in {"archived", "forgotten", "rejected"}:
            continue
        matches = secret_matches(record.body)
        if not matches:
            continue
        names = sorted({name for name, pattern in _pattern_names() if pattern.search(record.body)})
        findings.append(
            Finding(
                id=stable_id("fd", "secret", record.id),
                memory_id=record.id,
                kind="secret",
                severity="high",
                score=0.98,
                title="Secret or private value detected",
                detail=(
                    "Potential secret material ("
                    + (", ".join(names) or "sensitive assignment")
                    + ") was redacted. It is hidden in the UI and excluded from export."
                ),
                created_at=now_ms(),
            )
        )
    return findings


def _pattern_names():
    from ..normalize import _SECRET_PATTERNS

    return _SECRET_PATTERNS
