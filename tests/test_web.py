from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from memsift import actions, db
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


def _token(client: TestClient, path: str) -> str:
    text = client.get(path).text
    return re.search(r'name="csrf_token" value="([^"]+)"', text).group(1)


def test_dashboard_and_queue_render(cfg: Config, dirty_project: Path) -> None:
    _seed(cfg, dirty_project)
    client = TestClient(create_app(home=cfg.home), base_url="http://localhost")
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
    client = TestClient(create_app(home=cfg.home), base_url="http://localhost")
    detail = client.get(f"/memory/{first.id}")
    assert detail.status_code == 200
    merge = client.get(f"/merge?a={first.id}&b={second.id}")
    assert merge.status_code == 200
    token = re.search(r'name="csrf_token" value="([^"]+)"', merge.text).group(1)
    response = client.post(
        "/merge",
        data={"canonical": first.id, "other": second.id, "claim": "One canonical claim.", "csrf_token": token},
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
    client = TestClient(create_app(home=cfg.home), base_url="http://localhost")
    assert client.get("/settings").status_code == 200
    sync_page = client.get("/sync")
    assert sync_page.status_code == 200
    assert "Sync preview" in sync_page.text


def test_cross_site_post_cannot_change_memories(cfg: Config, dirty_project: Path) -> None:
    _seed(cfg, dirty_project)
    connection = db.connect(cfg.db_path)
    record = db.all_memories(connection)[0]
    connection.close()
    client = TestClient(create_app(home=cfg.home), base_url="http://localhost")
    response = client.post(
        f"/memory/{record.id}/action",
        data={"action": "archive"},
        headers={"origin": "https://attacker.example"},
    )
    assert response.status_code == 403
    connection = db.connect(cfg.db_path)
    assert db.get_memory(connection, record.id).status != "archived"
    connection.close()


def test_foreign_host_cannot_access_review_ui(cfg: Config) -> None:
    client = TestClient(create_app(home=cfg.home), base_url="http://localhost")
    response = client.get("/", headers={"host": "attacker.example:8787"})
    assert response.status_code == 400


def test_ipv6_loopback_host_can_access_review_ui(cfg: Config) -> None:
    client = TestClient(create_app(home=cfg.home), base_url="http://[::1]:8787")
    assert client.get("/").status_code == 200


def test_web_memory_actions_and_findings(cfg: Config, dirty_project: Path) -> None:
    _seed(cfg, dirty_project)
    connection = db.connect(cfg.db_path)
    try:
        record = db.all_memories(connection)[0]
        findings = db.list_findings(connection)
    finally:
        connection.close()
    client = TestClient(create_app(home=cfg.home), base_url="http://localhost")
    token = _token(client, f"/memory/{record.id}")

    for action in ("pin", "archive", "restore"):
        response = client.post(
            f"/memory/{record.id}/action",
            data={"action": action, "csrf_token": token},
            follow_redirects=False,
        )
        assert response.status_code == 303
    response = client.post(
        f"/memory/{record.id}/action",
        data={"action": "edit", "claim": "Edited claim.", "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    response = client.post(
        f"/memory/{record.id}/action",
        data={"action": "forget", "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303 and response.headers["location"] == "/queue"

    queue_token = _token(client, "/queue")
    for index, finding in enumerate(findings[:2]):
        endpoint = "approve" if index == 0 else "reject"
        response = client.post(
            f"/findings/{finding.id}/{endpoint}",
            data={"csrf_token": queue_token},
            follow_redirects=False,
        )
        assert response.status_code == 303

    connection = db.connect(cfg.db_path)
    try:
        assert db.get_memory(connection, record.id).status == "forgotten"
        assert db.get_finding(connection, findings[0].id).status == "resolved"
        assert db.get_finding(connection, findings[1].id).status == "dismissed"
    finally:
        connection.close()


def test_web_errors_and_sync_apply(cfg: Config, dirty_project: Path) -> None:
    _seed(cfg, dirty_project)
    client = TestClient(create_app(home=cfg.home), base_url="http://localhost")
    assert client.get("/memory/ms_missing").status_code == 404

    connection = db.connect(cfg.db_path)
    try:
        record = db.all_memories(connection)[0]
    finally:
        connection.close()
    token = _token(client, f"/memory/{record.id}")
    unknown = client.post(
        f"/memory/{record.id}/action",
        data={"action": "unknown", "csrf_token": token},
        follow_redirects=False,
    )
    assert unknown.status_code == 303 and "error" in unknown.headers["location"]
    empty_edit = client.post(
        f"/memory/{record.id}/action",
        data={"action": "edit", "claim": "  ", "csrf_token": token},
        follow_redirects=False,
    )
    assert empty_edit.status_code == 303 and "error" in empty_edit.headers["location"]

    merge_token = _token(client, "/merge")
    merge_error = client.post(
        "/merge",
        data={"canonical": "ms_missing", "other": "ms_other", "csrf_token": merge_token},
        follow_redirects=False,
    )
    assert merge_error.status_code == 303 and "error" in merge_error.headers["location"]

    assert client.get("/merge").status_code == 200
    connection = db.connect(cfg.db_path)
    try:
        actions.archive_memory(connection, "ms_anchor_dup")
        connection.commit()
    finally:
        connection.close()
    sync_token = _token(client, "/sync")
    refused = client.post(
        "/sync/apply", data={"csrf_token": sync_token}, follow_redirects=False
    )
    assert refused.status_code == 303 and "confirm" in refused.headers["location"]
    applied = client.post(
        "/sync/apply",
        data={"confirm": "yes", "csrf_token": sync_token},
        follow_redirects=False,
    )
    assert applied.status_code == 303 and "applied=1" in applied.headers["location"]
    assert "ms_anchor_dup" not in (dirty_project / "MEMORY.md").read_text(encoding="utf-8")
    assert client.get(applied.headers["location"]).status_code == 200
