from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from memsift.cli import app

runner = CliRunner()


def test_cli_init_scan_doctor_list_show(home: Path, monkeypatch, dirty_project: Path) -> None:
    monkeypatch.setenv("MEMSIFT_HOME", str(home))
    result = runner.invoke(app, ["init", "--path", str(dirty_project)])
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["scan"])
    assert result.exit_code == 0, result.output
    assert "Findings" in result.output

    result = runner.invoke(app, ["doctor", "--format", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["records"] == 10
    assert payload["findings"]

    result = runner.invoke(app, ["list", "--json"])
    assert result.exit_code == 0, result.output
    records = json.loads(result.output)
    assert len(records) == 10
    memory_id = records[0]["id"]

    result = runner.invoke(app, ["show", memory_id, "--json"])
    assert result.exit_code == 0, result.output
    shown = json.loads(result.output)
    assert shown["memory"]["id"] == memory_id

    result = runner.invoke(app, ["export", "--format", "md"])
    assert result.exit_code == 0, result.output
    assert "# memsift memory export" in result.output
    assert "sk-proj" not in result.output


def test_sync_reports_skipped_changed_file(home: Path, monkeypatch, dirty_project: Path) -> None:
    monkeypatch.setenv("MEMSIFT_HOME", str(home))
    assert runner.invoke(app, ["init", "--path", str(dirty_project)]).exit_code == 0
    assert runner.invoke(app, ["scan"]).exit_code == 0
    assert runner.invoke(app, ["archive", "ms_anchor_dup"]).exit_code == 0
    target = dirty_project / "MEMORY.md"
    target.write_text(target.read_text(encoding="utf-8") + "\nManual edit.\n", encoding="utf-8")

    result = runner.invoke(app, ["sync"])

    assert "changed since" in result.output
    assert "Nothing approved to sync" not in result.output
