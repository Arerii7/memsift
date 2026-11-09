from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from memsift import db
from memsift.config import Config
from memsift.detect import run_detectors
from memsift.ingest.markdown import ingest_markdown
from memsift.web.app import create_app


def _seed(cfg: Config, project: Path) -> None:
    connection = db.connect(cfg.db_path)
    try:
        ingest_markdown(connection, [project], cfg)
        run_detectors(connection, cfg)
        connection.commit()
    finally:
        connection.close()


def test_dashboard_and_queue_render(cfg: Config, dirty_project: Path) -> None:
    _seed(cfg, dirty_project)
    client = TestClient(create_app(home=cfg.home))
    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert "Sift the signal" in dashboard.text
    queue = client.get("/queue")
    assert queue.status_code == 200
    assert "Review queue" in queue.text
    filtered = client.get("/queue?kind=conflict")
    assert filtered.status_code == 200
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["ok"] is True


def test_detail_merge_and_actions(cfg: Config, dirty_project: Path) -> None:
    _seed(cfg, dirty_project)
    connection = db.connect(cfg.db_path)
    try:
        records = db.all_memories(connection)
        first, second = records[0], records[1]
    finally:
        connection.close()
    client = TestClient(create_app(home=cfg.home))
    detail = client.get(f"/memory/{first.id}")
    assert detail.status_code == 200
    merge = client.get(f"/merge?a={first.id}&b={second.id}")
    assert merge.status_code == 200
    response = client.post(
        "/merge",
        data={"canonical": first.id, "other": second.id, "claim": "One canonical claim."},
        follow_redirects=False,
    )
    assert response.status_code == 303
    connection = db.connect(cfg.db_path)
    try:
        assert db.get_memory(connection, first.id).claim == "One canonical claim."
        assert db.get_memory(connection, second.id).status == "archived"
    finally:
        connection.close()


def test_settings_and_sync_pages(cfg: Config, dirty_project: Path) -> None:
    _seed(cfg, dirty_project)
    client = TestClient(create_app(home=cfg.home))
    assert client.get("/settings").status_code == 200
    sync_page = client.get("/sync")
    assert sync_page.status_code == 200
    assert "Sync preview" in sync_page.text
