from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from memsift.cli import app

runner = CliRunner()


def _invoke(args: list[str], expected: int = 0):
    result = runner.invoke(app, args)
    assert result.exit_code == expected, result.output
    return result


def _records() -> list[dict[str, object]]:
    return json.loads(_invoke(["list", "--json"]).output)


def _init_scan(home: Path, monkeypatch, project: Path) -> None:
    monkeypatch.setenv("MEMSIFT_HOME", str(home))
    _invoke(["init", "--path", str(project)])
    _invoke(["scan"])


def test_sync_apply_and_rollback_workflow(home: Path, monkeypatch, dirty_project: Path) -> None:
    _init_scan(home, monkeypatch, dirty_project)
    _invoke(["anchor", "--path", str(dirty_project), "--apply", "--yes"])
    _invoke(["scan"])
    _invoke(["sync"])  # nothing approved yet
    _invoke(["archive", "ms_anchor_dup"])

    preview = _invoke(["sync", "--json"])
    payload = json.loads(preview.output)
    assert payload["changed"] is True
    assert "ms_anchor_dup" in payload["memory_ids"]
    assert "REDACTED" in payload["diff"]

    applied = _invoke(["sync", "--apply", "--yes"])
    assert "synced" in applied.output

    events = json.loads(_invoke(["history", "--json"]).output)
    sync_event = next(event for event in events if event["action"] == "sync")
    _invoke(["rollback", sync_event["id"], "--yes"])
    assert "ms_anchor_dup" in (dirty_project / "MEMORY.md").read_text(encoding="utf-8")


def test_record_action_commands(home: Path, monkeypatch, dirty_project: Path) -> None:
    _init_scan(home, monkeypatch, dirty_project)
    ids = [str(record["id"]) for record in _records()]
    assert len(ids) >= 6

    assert "pinned" in _invoke(["pin", ids[0]]).output
    assert "restored" in _invoke(["restore", ids[0]]).output
    assert "forgotten" in _invoke(["forget", ids[1]]).output
    assert "merged" in _invoke(["merge", ids[2], ids[3], "--claim", "Merged claim."]).output
    assert "superseded" in _invoke(["supersede", ids[4], ids[5]]).output


def test_table_outputs_and_export(home: Path, monkeypatch, dirty_project: Path, tmp_path: Path) -> None:
    _init_scan(home, monkeypatch, dirty_project)
    _invoke(["doctor"])
    _invoke(["list", "--limit", "3"])
    _invoke(["show", _records()[0]["id"]])
    _invoke(["history"])
    _invoke(["search", "SQLite"])
    _invoke(["sources", "--path", str(dirty_project)])
    _invoke(["version"])

    exported = _invoke(["export", "--format", "json"])
    assert isinstance(json.loads(exported.output), list)
    output = tmp_path / "nested" / "export.md"
    _invoke(["export", "--format", "md", "--output", str(output)])
    assert output.exists()
    assert "# memsift memory export" in output.read_text(encoding="utf-8")


def test_anchor_preview_without_writing(home: Path, monkeypatch, clean_project: Path) -> None:
    monkeypatch.setenv("MEMSIFT_HOME", str(home))
    _invoke(["init", "--path", str(clean_project)])
    before = (clean_project / "MEMORY.md").read_text(encoding="utf-8")
    preview = _invoke(["anchor", "--path", str(clean_project)])
    assert "dry run" in preview.output
    assert (clean_project / "MEMORY.md").read_text(encoding="utf-8") == before


def test_opencode_scan_and_import(home: Path, monkeypatch, opencode_db: Path) -> None:
    monkeypatch.setenv("MEMSIFT_HOME", str(home))
    _invoke(["init", "--no-source"])
    imported = _invoke(
        ["import", "opencode", "--project", "/tmp/project", "--db", str(opencode_db), "--json"]
    )
    payload = json.loads(imported.output)
    assert payload["ingest"]["records"] == 3

    scanned = _invoke(
        [
            "scan",
            "--source",
            "opencode",
            "--project",
            "/tmp/project",
            "--db",
            str(opencode_db),
            "--json",
        ]
    )
    assert json.loads(scanned.output)["detectors"]["total"] >= 0


def test_cli_error_paths(home: Path, monkeypatch, dirty_project: Path, tmp_path: Path) -> None:
    monkeypatch.setenv("MEMSIFT_HOME", str(home))
    _invoke(["init", "--path", str(dirty_project)])
    _invoke(["scan"])

    missing = _invoke(["show", "ms_missing"], expected=1)
    assert "not found" in missing.output
    assert "error" in _invoke(["merge", "ms_missing", "ms_other"], expected=1).output
    assert "error" in _invoke(["export", "--format", "yaml"], expected=1).output
    assert "error" in _invoke(["import", "unknown"], expected=1).output
    assert "error" in _invoke(["rollback", "ev_missing", "--yes"], expected=1).output
    assert "error" in _invoke(["review", "--host", "0.0.0.0"], expected=1).output
    assert "error" in _invoke(["init", "--path", str(tmp_path / "missing")], expected=1).output
