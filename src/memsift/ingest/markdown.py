from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .. import db
from ..config import Config, project_scope
from ..models import MemoryRecord, now_ms, stable_id
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

START_ANCHOR = re.compile(r"^\s*<!--\s*memsift:id=(?P<id>[A-Za-z0-9_.-]+)\s*-->\s*$")
END_ANCHOR = re.compile(r"^\s*<!--\s*/memsift:id=(?P<id>[A-Za-z0-9_.-]+)\s*-->\s*$")
ANY_ANCHOR = re.compile(r"^\s*<!--\s*/?memsift:id=")

_BULLET = re.compile(r"^(?P<indent>\s*)(?:[-*+]|\d+[.)])\s+(?P<text>.+?)\s*$")
_HEADING = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<text>.+?)\s*#*\s*$")
_MEMORY_HEADINGS = (
    "memory",
    "memories",
    "facts",
    "preferences",
    "decisions",
    "learned",
    "notes",
    "context",
    "profile",
    "rules",
    "instructions",
    "about",
    "project",
    "память",
    "факты",
    "предпочтения",
    "решения",
    "заметки",
    "контекст",
    "правила",
)
_MEMORY_FILENAMES = {"memory.md", "agents.md", "claude.md", "memories.md"}
_SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    "site-packages",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".memsift",
}


@dataclass(slots=True)
class MarkdownBlock:
    claim: str
    body: str
    start_line: int  # 0-based, marker line when anchored
    end_line: int  # exclusive
    content_start: int  # first body line
    content_end: int  # exclusive
    kind: str = "paragraph"
    heading: str = ""
    explicit_id: str | None = None
    explicit: bool = False
    line_no: int = 1

    @property
    def anchored(self) -> bool:
        return bool(self.explicit_id)


def discover_markdown_files(path: Path, *, skipped: list[Path] | None = None) -> list[Path]:
    path = path.expanduser().resolve()
    if path.is_file():
        return [path] if path.suffix.lower() in {".md", ".markdown", ".mdx"} else []
    if not path.exists():
        return []
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(path):
        if skipped is not None:
            skipped.extend(Path(dirpath) / name for name in dirnames if name.startswith(".") and name != ".opencode")
        dirnames[:] = [
            name
            for name in dirnames
            if name not in _SKIP_DIRS
            and not (name.startswith(".") and name != ".opencode")
        ]
        # Outside .opencode/memory, hidden subtrees are not memory.
        current = Path(dirpath)
        parts = current.relative_to(path).parts if current != path else ()
        if parts and parts[-1] == ".opencode":
            dirnames[:] = [name for name in dirnames if name == "memory"]
            continue
        if ".opencode" in parts and "memory" not in parts:
            dirnames[:] = []
            continue
        for name in filenames:
            if name.lower().endswith((".md", ".markdown", ".mdx")):
                found.append((current / name).resolve())
    return sorted(set(found))


def _heading_allowed(filename: str, relpath: str, heading: str) -> bool:
    lower_name = filename.lower()
    if lower_name in _MEMORY_FILENAMES:
        return True
    normalized = relpath.replace("\\", "/").lower()
    if ".opencode/memory" in normalized or "/memory/" in normalized:
        return True
    words = heading.lower()
    return any(word in words for word in _MEMORY_HEADINGS)


def _kind_for(lines: list[str]) -> str:
    if not lines:
        return "paragraph"
    first = lines[0]
    if _BULLET.match(first):
        return "bullet"
    if first.startswith(">"):
        return "quote"
    if first.startswith("```"):
        return "line"
    return "paragraph"


def _trim_body(lines: list[str]) -> list[str]:
    while lines and not lines[0].strip():
        lines = lines[1:]
    while lines and not lines[-1].strip():
        lines = lines[:-1]
    return lines


def parse_blocks(text: str, *, filename: str = "", relpath: str = "") -> list[MarkdownBlock]:
    lines = text.splitlines()
    blocks: list[MarkdownBlock] = []
    seen_ids: set[str] = set()
    heading_stack: list[tuple[int, str]] = []
    i = 0
    in_frontmatter = bool(lines and lines[0].strip() == "---")
    if in_frontmatter:
        i = 1
        while i < len(lines) and lines[i].strip() != "---":
            i += 1
        i = min(i + 1, len(lines))

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        anchor = START_ANCHOR.match(line)
        if anchor:
            marker_index = i
            explicit_id = anchor.group("id")
            j = i + 1
            end_marker = None
            while j < len(lines):
                if END_ANCHOR.match(lines[j]):
                    end_marker = j
                    break
                if START_ANCHOR.match(lines[j]):
                    break
                j += 1
            raw_content = lines[i + 1 : (end_marker if end_marker is not None else j)]
            leading_blank = 0
            while leading_blank < len(raw_content) and not raw_content[leading_blank].strip():
                leading_blank += 1
            content = _trim_body(raw_content)
            block_end = (end_marker + 1) if end_marker is not None else j
            i = max(block_end, i + 1)
            if not content or explicit_id in seen_ids:
                continue
            seen_ids.add(explicit_id)
            content_start = marker_index + 1 + leading_blank
            content_end = content_start + len(content)
            blocks.append(
                MarkdownBlock(
                    claim=clean_claim(content[0]),
                    body="\n".join(content),
                    start_line=marker_index,
                    end_line=block_end,
                    content_start=content_start,
                    content_end=content_end,
                    kind=_kind_for(content),
                    heading=" / ".join(item[1] for item in heading_stack),
                    explicit_id=explicit_id,
                    explicit=True,
                    line_no=content_start + 1,
                )
            )
            continue

        if stripped.startswith("```"):
            lang = stripped[3:].strip().lower()
            j = i + 1
            changed_directory = False
            while j < len(lines) and not lines[j].strip().startswith("```"):
                anchor = START_ANCHOR.match(lines[j]) if lang in {"memory", "memories", "memsift"} else None
                if anchor:
                    end = j + 1
                    while end < len(lines) and not lines[end].strip().startswith("```") and not END_ANCHOR.match(lines[end]):
                        end += 1
                    closing = END_ANCHOR.match(lines[end]) if end < len(lines) else None
                    content = _trim_body(lines[j + 1:end])
                    explicit_id = anchor.group("id")
                    if closing and closing.group("id") == explicit_id and content and explicit_id not in seen_ids:
                        first = next(k for k in range(j + 1, end) if lines[k].strip())
                        blocks.append(MarkdownBlock(
                            claim=clean_claim(content[0]), body="\n".join(content),
                            start_line=j, end_line=end + 1, content_start=first,
                            content_end=first + len(content), kind="line",
                            heading=" / ".join(item[1] for item in heading_stack),
                            explicit_id=explicit_id, explicit=True, line_no=first + 1,
                        ))
                        seen_ids.add(explicit_id)
                        j = end + 1
                        continue
                changed_directory = changed_directory or bool(re.search(r"\bcd\s+", lines[j]))
                instruction_command = (
                    filename.lower() in {"agents.md", "claude.md"}
                    and lang in {"", "bash", "sh", "shell"}
                    and not changed_directory
                    and re.search(r"\bnpm\s+run\s+[\w:.-]+", lines[j])
                )
                if (lang in {"memory", "memories", "memsift"} and lines[j].strip()) or instruction_command:
                    body = lines[j].strip()
                    blocks.append(
                        MarkdownBlock(
                            claim=clean_claim(body),
                            body=body,
                            start_line=j,
                            end_line=j + 1,
                            content_start=j,
                            content_end=j + 1,
                            kind="instruction_command" if instruction_command else "line",
                            heading=" / ".join(item[1] for item in heading_stack),
                            explicit=True,
                            line_no=j + 1,
                        )
                    )
                j += 1
            i = min(j + 1, len(lines))
            continue

        heading = _HEADING.match(line)
        if heading:
            level = len(heading.group("hashes"))
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, heading.group("text").strip()))
            i += 1
            continue

        if not stripped or stripped in {"---", "***", "___"}:
            i += 1
            continue
        if stripped.startswith("<!--"):
            i += 1
            continue

        bullet = _BULLET.match(line)
        if bullet:
            base_indent = len(bullet.group("indent"))
            j = i + 1
            while j < len(lines):
                candidate = lines[j]
                if not candidate.strip():
                    break
                if START_ANCHOR.match(candidate) or candidate.lstrip().startswith("```"):
                    break
                if _HEADING.match(candidate):
                    break
                next_bullet = _BULLET.match(candidate)
                if next_bullet and len(next_bullet.group("indent")) <= base_indent:
                    break
                if not candidate[:1].isspace() and candidate.strip():
                    # A new unindented paragraph ends the item.
                    break
                j += 1
            content = _trim_body(lines[i:j])
            i = max(j, i + 1)
            if not content:
                continue
            first = _BULLET.match(content[0])
            claim_text = first.group("text") if first else content[0]
            blocks.append(
                MarkdownBlock(
                    claim=clean_claim(claim_text),
                    body="\n".join(content),
                    start_line=i - len(content),
                    end_line=i,
                    content_start=i - len(content),
                    content_end=i,
                    kind="bullet",
                    heading=" / ".join(item[1] for item in heading_stack),
                    explicit=False,
                    line_no=i - len(content) + 1,
                )
            )
            continue

        explicit_marker = re.match(
            r"^\s*(?:remember|decision|preference|fact|note|memory)\s*[:=]\s*",
            line,
            re.IGNORECASE,
        )
        if explicit_marker or _heading_allowed(filename, relpath, " / ".join(h for _, h in heading_stack)):
            j = i + 1
            while j < len(lines):
                candidate = lines[j]
                if not candidate.strip():
                    break
                if START_ANCHOR.match(candidate) or candidate.lstrip().startswith("```"):
                    break
                if _HEADING.match(candidate) or _BULLET.match(candidate):
                    break
                if candidate.strip().startswith(("|", "<!--")):
                    break
                j += 1
            content = _trim_body(lines[i:j])
            i = max(j, i + 1)
            if not content:
                continue
            blocks.append(
                MarkdownBlock(
                    claim=clean_claim(content[0]),
                    body="\n".join(content),
                    start_line=i - len(content),
                    end_line=i,
                    content_start=i - len(content),
                    content_end=i,
                    kind=_kind_for(content),
                    heading=" / ".join(item[1] for item in heading_stack),
                    explicit=bool(explicit_marker),
                    line_no=i - len(content) + 1,
                )
            )
            continue

        i += 1

    return blocks


def _block_to_record(
    block: MarkdownBlock,
    *,
    path: Path,
    root: Path,
    text_hash: str,
    occurrence: int,
    mtime_ms: int,
) -> MemoryRecord:
    try:
        relpath = str(path.relative_to(root))
    except ValueError:
        relpath = path.name
    topic = infer_topic(block.body)
    files = extract_file_refs(block.body)
    sensitivity = sensitivity_for(block.body)
    claim = clean_claim(block.claim)
    memory_id = stable_memory_id(
        "markdown",
        relpath,
        claim,
        occurrence,
        explicit=block.explicit_id,
    )
    confidence = score_confidence(
        source_kind="markdown",
        claim=claim,
        explicit=block.explicit,
        topic_key=topic,
        files=files,
        created_at=mtime_ms,
    )
    tags = ["heading:" + block.heading] if block.heading else []
    return MemoryRecord(
        id=memory_id,
        claim=claim,
        norm_claim=normalize_claim(claim),
        body=block.body,
        topic_key=topic,
        scope=project_scope(root),
        source_kind="markdown",
        source_ref=f"{path}:{block.line_no}",
        source_hash=text_hash,
        created_at=mtime_ms,
        updated_at=mtime_ms,
        last_seen_at=now_ms(),
        confidence=confidence,
        files=files,
        tags=tags,
        sensitivity=sensitivity,
        block_kind=block.kind,
    )


def parse_markdown_blocks(path: Path, root: Path) -> tuple[list[MemoryRecord], list[MarkdownBlock]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        relpath = str(path.relative_to(root))
    except ValueError:
        relpath = str(path)
    blocks = parse_blocks(text, filename=path.name, relpath=relpath)
    text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    mtime_ms = int(path.stat().st_mtime * 1000)
    counts: dict[str, int] = {}
    records: list[MemoryRecord] = []
    for block in blocks:
        key = normalize_claim(block.claim)
        occurrence = counts.get(key, 0)
        counts[key] = occurrence + 1
        if not block.claim.strip():
            continue
        records.append(
            _block_to_record(
                block,
                path=path.resolve(),
                root=root.resolve(),
                text_hash=text_hash,
                occurrence=occurrence,
                mtime_ms=mtime_ms,
            )
        )
    return records, blocks


def parse_markdown(path: Path, root: Path) -> list[MemoryRecord]:
    return parse_markdown_blocks(path, root)[0]


def _source_lines(conn: sqlite3.Connection, paths: list[Path]) -> None:
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            mtime = int(path.stat().st_mtime * 1000)
        except OSError:
            continue
        db.upsert_source_file(conn, path, digest=digest, mtime=mtime, parser="markdown")


def ingest_markdown(
    conn: sqlite3.Connection,
    paths: list[Path],
    config: Config,
    *,
    mark_missing: bool = False,
) -> IngestStats:
    stats = IngestStats()
    seen_records: set[str] = set()
    processed_files: set[Path] = set()
    existing_paths: list[Path] = []
    old_ids_by_path: dict[str, set[str]] = {}
    for record in db.all_memories(conn):
        if record.source_kind == "markdown":
            old_ids_by_path.setdefault(record.source_ref.rsplit(":", 1)[0], set()).add(record.id)
    for raw_path in paths:
        path = raw_path.expanduser().resolve()
        if not path.exists():
            stats.errors.append(f"path not found: {path}")
            continue
        files = discover_markdown_files(path)
        root = path if path.is_dir() else path.parent
        if path.is_dir() and not files:
            stats.errors.append(f"no Markdown files under: {path}")
        for file_path in files:
            if file_path in processed_files:
                continue
            processed_files.add(file_path)
            existing_paths.append(file_path)
            try:
                records, blocks = parse_markdown_blocks(file_path, root)
            except OSError as exc:
                stats.errors.append(f"{file_path}: {exc}")
                continue
            stats.files += 1
            stats.paths.append(file_path)
            explicit_ids = {block.explicit_id for block in blocks if block.explicit_id}
            found_ids: set[str] = set()
            for record in records:
                existing = db.get_memory(conn, record.id)
                if existing and existing.source_ref.rsplit(":", 1)[0] != str(file_path):
                    if record.id in explicit_ids:
                        old_path = Path(existing.source_ref.rsplit(":", 1)[0])
                        try:
                            old_text = old_path.read_text(encoding="utf-8", errors="replace")
                        except FileNotFoundError:
                            old_text = ""
                        except OSError as exc:
                            stats.errors.append(f"{file_path}: cannot verify previous anchor at {old_path}: {exc}")
                            stats.skipped += 1
                            continue
                        if any(
                            (match := START_ANCHOR.match(line)) and match.group("id") == record.id
                            for line in old_text.splitlines()
                        ):
                            stats.errors.append(f"{file_path}: duplicate anchor id {record.id} already used by {existing.source_ref}")
                            stats.skipped += 1
                            continue
                    else:
                        record.id = stable_id("ms", "markdown", str(file_path), record.id)
                        existing = db.get_memory(conn, record.id)
                        if existing and existing.source_ref.rsplit(":", 1)[0] != str(file_path):
                            stats.errors.append(f"{file_path}: memory id collision {record.id}")
                            stats.skipped += 1
                            continue
                found_ids.add(record.id)
                if record.id in seen_records:
                    stats.skipped += 1
                    continue
                seen_records.add(record.id)
                db.upsert_memory(conn, record)
                stats.records += 1
            missing_ids = old_ids_by_path.get(str(file_path), set()) - found_ids
            conn.executemany(
                "UPDATE memories SET source_present = 0, status = CASE "
                "WHEN status IN ('archived', 'forgotten', 'rejected') THEN status ELSE 'orphan' END "
                "WHERE id = ? AND substr(source_ref, 1, length(?)) = ?",
                [(item, f"{file_path}:", f"{file_path}:") for item in missing_ids],
            )
    _source_lines(conn, existing_paths)
    if mark_missing and existing_paths:
        db.delete_missing_markdown_records(conn, existing_paths=existing_paths)
    db.insert_event(
        conn,
        memory_id=None,
        action="ingest",
        actor="cli",
        after=stats.as_dict(),
        note="markdown ingest",
    )
    return stats
