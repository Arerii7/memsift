from __future__ import annotations

import json
from pathlib import Path

from memsift import db
from memsift.config import Config
from memsift.detect import run_detectors
from memsift.detect.scoring import refresh_confidence
from memsift.export import export_json, export_markdown
from memsift.ingest.markdown import ingest_markdown


def test_export_markdown_and_json_hide_secrets(conn, cfg: Config, tmp_path: Path) -> None:
    project = tmp_path / "mixed"
    project.mkdir()
    (project / "MEMORY.md").write_text(
        "# Memory\n\n## Facts\n\n"
        "- We use SQLite.\n"
        "- OPENAI_API_KEY=sk-proj-abcdefghijklmnop1234\n",
        encoding="utf-8",
    )
    ingest_markdown(conn, [project], cfg)
    run_detectors(conn, cfg)
    conn.commit()

    markdown = export_markdown(conn)
    assert "# memsift memory export" in markdown
    assert "<!-- memsift:id=" in markdown
    assert "- We use SQLite." in markdown
    assert "sk-proj" not in markdown

    payload = json.loads(export_json(conn))
    assert payload
    assert all("sk-proj" not in item["claim"] + item["body"] for item in payload)
    scoped = json.loads(export_json(conn, scope=f"project:{project.resolve()}"))
    assert scoped == payload
    assert json.loads(export_json(conn, scope="project:/does/not/exist")) == []


def test_export_markdown_renders_paragraph_records(conn, cfg: Config, tmp_path: Path) -> None:
    project = tmp_path / "paragraph"
    project.mkdir()
    (project / "MEMORY.md").write_text(
        "# Notes\n\n## Context\n\nDeploy target is Vercel.\n",
        encoding="utf-8",
    )
    ingest_markdown(conn, [project], cfg)
    conn.commit()

    markdown = export_markdown(conn)
    assert "Deploy target is Vercel." in markdown
    assert "## " in markdown


def test_refresh_confidence_uses_record_fields(conn, cfg: Config, dirty_project: Path) -> None:
    ingest_markdown(conn, [dirty_project], cfg)
    record = db.all_memories(conn)[0]
    score = refresh_confidence(record)
    assert 0.0 <= score <= 1.0
