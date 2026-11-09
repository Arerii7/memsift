from __future__ import annotations

from pathlib import Path

from ..models import Finding, MemoryRecord, now_ms, stable_id
from ..normalize import date_only, redact_text


def _root_for(record: MemoryRecord) -> Path | None:
    if record.scope.startswith("project:"):
        return Path(record.scope.split(":", 1)[1]).expanduser()
    if record.source_kind == "markdown" and record.source_ref:
        raw = record.source_ref.rsplit(":", 1)[0]
        return Path(raw).expanduser().parent
    return None


def _resolve(root: Path | None, value: str) -> Path:
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return candidate
    return (root or Path.cwd()) / candidate


def detect_stale(records: list[MemoryRecord], *, ttl_days: int = 0) -> list[Finding]:
    findings: list[Finding] = []
    now = now_ms()
    for record in records:
        if record.status in {"archived", "forgotten", "rejected"}:
            continue
        root = _root_for(record)
        missing: list[str] = []
        for ref in record.files:
            if not _resolve(root, ref).exists():
                missing.append(ref)
        expired = bool(ttl_days and (now - record.updated_at) > ttl_days * 86_400_000)
        if not missing and not expired:
            continue
        if missing:
            detail = "Referenced path(s) no longer exist: " + ", ".join(missing)
            title = f"Stale reference: {redact_text(missing[0])[:90]}"
            score = 0.8
        else:
            detail = f"Record is older than the configured TTL of {ttl_days} days."
            title = f"Expired: {redact_text(record.claim)[:80]}"
            score = 0.55
        if expired and missing:
            detail += f" Also older than {ttl_days} days (updated {date_only(record.updated_at)})."
        findings.append(
            Finding(
                id=stable_id("fd", "stale", record.id, "|".join(sorted(missing)), expired),
                memory_id=record.id,
                kind="stale",
                severity="medium",
                score=score,
                title=title,
                detail=detail,
                created_at=now,
            )
        )
    return findings
