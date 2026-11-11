from __future__ import annotations

import difflib
import hashlib
import os
import re
import shutil
import stat
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .config import Config
from .ingest.markdown import discover_markdown_files, parse_markdown_blocks


@dataclass(slots=True)
class AnchorResult:
    path: Path
    count: int
    diff: str = ""
    applied: bool = False
    backup: Path | None = None
    errors: list[str] = field(default_factory=list)


def anchor_text(text: str, path: Path, root: Path) -> tuple[str, int]:
    records, blocks = parse_markdown_blocks(path, root)
    by_line = {}
    for record in records:
        try:
            line = int(record.source_ref.rsplit(":", 1)[1])
        except (IndexError, ValueError):
            continue
        by_line[line] = record
    lines = text.splitlines()
    edits: list[tuple[int, int, list[str]]] = []
    for block in blocks:
        if block.anchored or block.kind == "instruction_command":
            continue
        record = by_line.get(block.line_no)
        if record is None:
            continue
        start = block.start_line
        end = block.end_line
        original = lines[start:end]
        if not original:
            continue
        indent_match = re.match(r"\s*", original[0])
        indent = indent_match.group(0) if indent_match else ""
        new_block = [
            f"{indent}<!-- memsift:id={record.id} -->",
            *original,
            f"{indent}<!-- /memsift:id={record.id} -->",
        ]
        edits.append((start, end, new_block))
    if not edits:
        return text, 0
    edits.sort(key=lambda item: item[0], reverse=True)
    new_lines = list(lines)
    for start, end, replacement in edits:
        new_lines[start:end] = replacement
    result = "\n".join(new_lines)
    if text.endswith("\n"):
        result += "\n"
    return result, len(edits)


def _atomic_write(path: Path, text: str) -> None:
    mode = path.stat().st_mode
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".memsift.tmp", dir=str(path.parent)
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, stat.S_IMODE(mode))
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def add_anchors(
    path: Path,
    *,
    root: Path | None = None,
    config: Config | None = None,
    apply: bool = False,
) -> AnchorResult:
    path = path.expanduser().resolve()
    root = (root or (path.parent if path.is_file() else path)).resolve()
    cfg = config or Config.load()
    result = AnchorResult(path=path, count=0)
    files = discover_markdown_files(path)
    if not files:
        result.errors.append(f"no Markdown files found: {path}")
        return result
    total = 0
    all_diffs: list[str] = []
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_dir: Path | None = None
    for file_path in files:
        try:
            original = file_path.read_text(encoding="utf-8")
        except OSError as exc:
            result.errors.append(f"{file_path}: {exc}")
            continue
        try:
            updated, count = anchor_text(original, file_path, root)
        except ValueError as exc:
            result.errors.append(f"{file_path}: {exc}")
            continue
        if count == 0:
            continue
        total += count
        all_diffs.append(
            "".join(
                difflib.unified_diff(
                    original.splitlines(keepends=True),
                    updated.splitlines(keepends=True),
                    fromfile=str(file_path),
                    tofile=f"{file_path} (anchored)",
                )
            )
        )
        if apply:
            cfg.ensure_dirs()
            if backup_dir is None:
                anchor_backups = cfg.backups_dir / "anchors"
                anchor_backups.mkdir(parents=True, exist_ok=True)
                backup_dir = Path(tempfile.mkdtemp(prefix=f"{stamp}-", dir=anchor_backups))
            backup = backup_dir / str(file_path.resolve()).lstrip("/")
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file_path, backup)
            _atomic_write(file_path, updated)
            result.backup = backup_dir
    result.count = total
    result.diff = "\n".join(all_diffs)
    result.applied = apply
    return result


def anchor_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
