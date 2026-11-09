import json
from pathlib import Path

from typer.testing import CliRunner

from memsift.cli import app

runner = CliRunner()


def test_sources_reports_files_sizes_and_skipped_directories(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("# Instructions\n- Test\n", encoding="utf-8")
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "CLAUDE.md").write_text("- hidden\n", encoding="utf-8")
    result = runner.invoke(app, ["sources", "--path", str(tmp_path), "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["files"][0]["lines"] == 2
    assert data["files"][0]["bytes"] == len(b"# Instructions\n- Test\n")
    assert any(item.endswith(".claude") for item in data["skipped_directories"])


def test_search_finds_indexed_records_and_redacts_secrets(home, monkeypatch, dirty_project):
    monkeypatch.setenv("MEMSIFT_HOME", str(home))
    assert runner.invoke(app, ["init", "--path", str(dirty_project)]).exit_code == 0
    assert runner.invoke(app, ["scan"]).exit_code == 0
    result = runner.invoke(app, ["search", "SQLite", "--json"])
    assert result.exit_code == 0, result.output
    records = json.loads(result.output)
    assert any("SQLite" in record["claim"] for record in records)
    assert all("source_ref" in record for record in records)
    secret = runner.invoke(app, ["search", "OPENAI_API_KEY", "--json"])
    assert secret.exit_code == 0, secret.output
    assert "sk-proj-abcdefghijklmnop1234" not in secret.output


def test_sources_includes_opencode_memory(tmp_path: Path) -> None:
    memory = tmp_path / '.opencode' / 'memory'
    memory.mkdir(parents=True)
    (memory / 'notes.md').write_text('- A memory\n')
    result = runner.invoke(app, ['sources', '--path', str(tmp_path), '--json'])
    assert result.exit_code == 0
    assert any(f['path'].endswith('notes.md') for f in json.loads(result.output)['files'])
