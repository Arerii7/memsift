from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from memsift import actions
from memsift.cli import app
from memsift.config import Config
from memsift.ingest.markdown import ingest_markdown
from memsift.web.app import create_app


def test_sync_preview_redacts_context_secrets(conn, cfg, dirty_project, monkeypatch):
    ingest_markdown(conn, [dirty_project], cfg)
    actions.archive_memory(conn, "ms_anchor_dup")
    conn.commit()
    monkeypatch.setenv("MEMSIFT_HOME", str(cfg.home))
    secret = "sk-proj-abcdefghijklmnop1234"
    for args in (["sync"], ["sync", "--json"]):
        result = CliRunner().invoke(app, args)
        assert result.exit_code == 0
        assert secret not in result.output
        assert "REDACTED" in result.output
        if "--json" in args:
            assert json.loads(result.output)["changed"]
    page = TestClient(create_app(home=cfg.home), base_url="http://localhost").get("/sync")
    assert page.status_code == 200
    assert secret not in page.text
    assert "REDACTED" in page.text


def test_new_storage_is_private_without_changing_existing_home(tmp_path: Path):
    home = tmp_path / "existing"
    home.mkdir(mode=0o755)
    mode_before = stat.S_IMODE(home.stat().st_mode)
    previous = os.umask(0o022)
    try:
        cfg = Config(home=home)
        cfg.ensure_dirs()
        assert stat.S_IMODE(cfg.backups_dir.stat().st_mode) == 0o700
        assert stat.S_IMODE(home.stat().st_mode) == mode_before

        created = Config(home=tmp_path / "new")
        created.ensure_dirs()
        assert stat.S_IMODE(created.home.stat().st_mode) == 0o700
    finally:
        os.umask(previous)


def test_diff_hides_token_assignments_on_context_and_deleted_lines():
    from memsift.normalize import redact_diff

    secret = "abcdefghijklmnopqrs123"
    diff = f"--- a/file\n+++ b/file\n@@ -1 +1 @@\n MY_SERVICE_TOKEN={secret}\n-MY_SERVICE_TOKEN={secret}\n"
    assert secret not in redact_diff(diff)


def test_existing_backup_directory_is_made_private(tmp_path: Path):
    cfg = Config(home=tmp_path / 'existing')
    cfg.backups_dir.mkdir(parents=True, mode=0o755)
    cfg.backups_dir.chmod(0o755)
    cfg.ensure_dirs()
    assert stat.S_IMODE(cfg.backups_dir.stat().st_mode) == 0o700
