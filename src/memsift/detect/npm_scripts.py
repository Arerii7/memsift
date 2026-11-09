from __future__ import annotations

import json
import re
from pathlib import Path

from ..models import Finding, MemoryRecord, stable_id
from ..normalize import redact_text

SCRIPT = re.compile(r"\bnpm\s+run\s+([A-Za-z0-9_][A-Za-z0-9_:.-]*)")


def detect_missing_scripts(records: list[MemoryRecord]) -> list[Finding]:
    findings = []
    for record in records:
        if record.source_kind != "markdown" or not record.scope.startswith("project:"):
            continue
        path = Path(record.source_ref.rsplit(":", 1)[0])
        if path.name.lower() not in {"agents.md", "claude.md"}:
            continue
        scripts = {
            match.group(1)
            for line in record.body.splitlines()
            if not re.search(r"\bcd\s+", line)
            for match in SCRIPT.finditer(line)
        }
        if not scripts:
            continue
        root = Path(record.scope.removeprefix("project:"))
        directory = path.parent
        while directory != root and directory.is_relative_to(root) and not (directory / "package.json").is_file():
            directory = directory.parent
        manifest = directory / "package.json"
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            available = data.get("scripts", {})
            if not isinstance(available, dict):
                continue
        except (OSError, ValueError, AttributeError):
            continue
        for script in sorted(scripts - available.keys()):
            safe_script = redact_text(script)
            match = next(m for m in SCRIPT.finditer(record.body) if m.group(1) == script)
            base_line = int(record.source_ref.rsplit(":", 1)[1])
            line = base_line + record.body[:match.start()].count("\n")
            findings.append(Finding(
                id=stable_id("fd", "stale_script", record.id, script),
                memory_id=record.id, kind="stale_script", severity="medium", score=0.8,
                title=f"Missing npm script: {safe_script}",
                detail=redact_text(f"npm run {script} is not in {manifest}; review {path}:{line}."),
            ))
    return findings
