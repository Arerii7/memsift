from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from .. import db
from ..config import Config, project_scope
from ..models import MemoryRecord, now_ms
from ..normalize import (
    clean_claim,
    extract_file_refs,
    infer_topic,
    normalize_claim,
    score_confidence,
    sensitivity_for,
    stable_memory_id,
)
from .base import IngestStats

MARKER = re.compile(r"^\s*(remember|decision|preference)\s*:\s*(.+?)\s*$", re.IGNORECASE)
FENCE_START = re.compile(r"^\s*```(?:memory|memories|memsift)\s*$", re.IGNORECASE)


def default_opencode_db() -> Path:
    return Path.home() / ".local" / "share" / "opencode" / "opencode.db"


def _message_text(message_type: str, data: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    if message_type == "user":
        text = data.get("text")
        if isinstance(text, str):
            texts.append(text)
        return texts
    content = data.get("content")
    if not isinstance(content, list):
        return texts
    for part in content:
        if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str):
            texts.append(part["text"])
    return texts


def extract_markers(text: str) -> list[tuple[str, str]]:
    markers: list[tuple[str, str]] = []
    in_memory_fence = False
    for line in text.splitlines():
        if FENCE_START.match(line):
            in_memory_fence = True
            continue
        if in_memory_fence:
            if line.strip().startswith("```"):
                in_memory_fence = False
                continue
            if line.strip():
                marker = MARKER.match(line)
                markers.append((marker.group(1).lower(), clean_claim(marker.group(2))) if marker else ("memory", clean_claim(line)))
            continue
        marker = MARKER.match(line)
        if marker and len(marker.group(2).strip()) >= 3:
            markers.append((marker.group(1).lower(), clean_claim(marker.group(2))))
    # A line can be both inside a fence and a marker; avoid duplicates only for
    # exactly identical claim+kind in the same message.
    return list(dict.fromkeys(markers))


def _session_rows(
    src: sqlite3.Connection, project: Path | None
) -> list[sqlite3.Row]:
    rows = src.execute(
        "SELECT id, directory, title, time_created FROM session_v2 "
        "ORDER BY time_created ASC, id"
    ).fetchall()
    if project is None:
        return rows

    def normalized(value: Path | str) -> str:
        return str(value).rstrip("/")

    def matches(directory: str, prefix: str) -> bool:
        return directory == prefix or directory.startswith(prefix + "/")

    # Session directories and the user's project path may differ by symlink
    # resolution (notably /tmp vs /private/tmp on macOS).
    prefixes = {normalized(project), normalized(project.resolve())}
    matched: list[sqlite3.Row] = []
    for row in rows:
        directory = normalized(str(row["directory"]))
        variants = {directory, normalized(Path(directory).resolve())}
        if any(matches(candidate, prefix) for candidate in variants for prefix in prefixes):
            matched.append(row)
    return matched


def ingest_opencode(
    conn: sqlite3.Connection,
    *,
    opencode_db: Path | None = None,
    project: Path | None = None,
    config: Config,
) -> IngestStats:
    stats = IngestStats()
    src_path = (opencode_db or default_opencode_db()).expanduser().resolve()
    if not src_path.exists():
        stats.errors.append(f"OpenCode database not found: {src_path}")
        return stats
    try:
        src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
        src.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        stats.errors.append(f"cannot open OpenCode database read-only: {exc}")
        return stats
    stats.files = 1
    stats.paths.append(src_path)
    try:
        sessions = _session_rows(src, project)
        for session in sessions:
            scope = project_scope(Path(session["directory"]))
            messages = src.execute(
                "SELECT id, session_id, type, seq, time_created, data "
                "FROM session_message WHERE session_id = ? ORDER BY seq ASC",
                (session["id"],),
            ).fetchall()
            for message in messages:
                try:
                    data = json.loads(message["data"])
                except (TypeError, json.JSONDecodeError):
                    stats.skipped += 1
                    continue
                if not isinstance(data, dict):
                    continue
                occurrences: dict[str, int] = {}
                for raw_text in _message_text(str(message["type"]), data):
                    for marker_kind, claim in extract_markers(raw_text):
                        if not claim:
                            continue
                        key = normalize_claim(claim)
                        occurrence = occurrences.get(key, 0)
                        occurrences[key] = occurrence + 1
                        created = int(message["time_created"])
                        body = f"{marker_kind}: {claim}"
                        topic = infer_topic(claim)
                        files = extract_file_refs(body)
                        source_ref = (
                            f"opencode:{message['session_id']}:{message['id']}:"
                            f"{occurrence + 1}"
                        )
                        memory_id = stable_memory_id(
                            "opencode",
                            source_ref,
                            claim,
                            occurrence,
                        )
                        record = MemoryRecord(
                            id=memory_id,
                            claim=claim,
                            norm_claim=key,
                            body=body,
                            topic_key=topic,
                            scope=scope,
                            source_kind="opencode",
                            source_ref=source_ref,
                            source_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
                            session_id=str(message["session_id"]),
                            message_id=str(message["id"]),
                            created_at=created,
                            updated_at=created,
                            last_seen_at=now_ms(),
                            confidence=score_confidence(
                                source_kind="opencode",
                                claim=claim,
                                explicit=True,
                                topic_key=topic,
                                files=files,
                                created_at=created,
                            ),
                            files=files,
                            tags=[f"marker:{marker_kind}"],
                            sensitivity=sensitivity_for(body),
                            block_kind="session",
                        )
                        db.upsert_memory(conn, record)
                        stats.records += 1
    except sqlite3.Error as exc:
        stats.errors.append(f"OpenCode read failed: {exc}")
    finally:
        src.close()
    db.insert_event(
        conn,
        memory_id=None,
        action="ingest",
        actor="cli",
        after=stats.as_dict(),
        note="opencode ingest (read-only)",
    )
    return stats
