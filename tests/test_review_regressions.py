from __future__ import annotations

import hashlib
import html
import re

import pytest
from fastapi.testclient import TestClient

from memsift import actions, db
from memsift.anchor import add_anchors
from memsift.ingest.markdown import ingest_markdown, parse_blocks
from memsift.sync import apply_sync, plan_sync, rollback_event
from memsift.web.app import create_app


@pytest.fixture()
def source(tmp_path, cfg, conn):
    project = tmp_path / "project"
    project.mkdir()
    path = project / "MEMORY.md"
    path.write_text(
        "<!-- memsift:id=a -->\n- Keep backups.\n  Keep seven copies.\n<!-- /memsift:id=a -->\n\n"
        "<!-- memsift:id=b -->\n- Prefer tea.\n<!-- /memsift:id=b -->\n\n"
        "<!-- memsift:id=c -->\n- Prefer coffee.\n<!-- /memsift:id=c -->\n"
    )
    ingest_markdown(conn, [project], cfg)
    conn.commit()
    return path


def form_value(page: str, name: str) -> str:
    match = re.search(rf'name="{name}" value="([^"]*)"', page)
    assert match, f"Missing form field: {name}"
    return html.unescape(match.group(1))


@pytest.mark.parametrize("ending", ["", "<!-- /memsift:id=wrong -->\n", "<!-- memsift:id=b -->\n"])
def test_malformed_anchor_is_not_writable(ending):
    text = "<!-- memsift:id=a -->\n- A fact.\n" + ending + "\n# Other content\nKeep me.\n"
    with pytest.raises(ValueError, match="anchor"):
        parse_blocks(text, filename="MEMORY.md")


def test_invalid_anchor_is_reported_without_rewriting_file(tmp_path, cfg, conn):
    path = tmp_path / "MEMORY.md"
    text = "<!-- memsift:id=a -->\n- A fact.\n\n# Other content\nKeep me.\n"
    path.write_text(text)
    assert ingest_markdown(conn, [path], cfg).errors
    assert not db.all_memories(conn)
    assert add_anchors(path, config=cfg, apply=True).errors
    assert path.read_text() == text


def test_sync_skips_invalid_anchor_even_when_source_hash_matches(source, cfg, conn):
    text = source.read_text().replace("<!-- /memsift:id=a -->", "<!-- /memsift:id=wrong -->")
    source.write_text(text)
    db.set_source_hash(conn, "a", hashlib.sha256(text.encode()).hexdigest())
    actions.archive_memory(conn, "a")
    conn.commit()
    plan = plan_sync(conn)
    assert not plan.changed
    assert plan.skipped
    assert source.read_text() == text


@pytest.mark.parametrize("claim", [None, "Keep daily backups."])
def test_merge_preserves_canonical_continuation(source, cfg, conn, claim):
    actions.merge_memories(conn, "a", "b", claim=claim)
    conn.commit()
    apply_sync(conn, plan_sync(conn), cfg)
    assert "  Keep seven copies.\n" in source.read_text()
    assert db.get_memory(conn, "a").body.splitlines()[1] == "  Keep seven copies."


def test_edit_preserves_record_continuation(source, conn):
    actions.edit_memory(conn, "a", claim="Keep daily backups.")
    assert db.get_memory(conn, "a").body == "- Keep daily backups.\n  Keep seven copies."


@pytest.mark.parametrize("canonical,other", [("a", "b"), ("b", "a")])
def test_merge_refuses_secret_records_before_changing_either(source, conn, canonical, other):
    actions.edit_memory(conn, "a", claim="api_key=sk-proj-abcdefghijklmnop1234")
    before = [record.to_row() for record in db.all_memories(conn)]
    with pytest.raises(ValueError, match="secret"):
        actions.merge_memories(conn, canonical, other, claim="[REDACTED]")
    assert [record.to_row() for record in db.all_memories(conn)] == before


def test_secret_cannot_be_edited_through_web_post(source, cfg, conn):
    actions.edit_memory(conn, "a", claim="api_key=sk-proj-abcdefghijklmnop1234")
    conn.commit()
    client = TestClient(create_app(home=cfg.home), base_url="http://localhost")
    page = client.get("/memory/a").text
    response = client.post("/memory/a/action", data={
        "csrf_token": form_value(page, "csrf_token"), "action": "edit", "claim": "[REDACTED]",
    }, follow_redirects=False)
    assert "error=" in response.headers["location"]
    assert db.get_memory(conn, "a").sensitivity == "secret"


def test_successive_syncs_do_not_require_rescan(source, cfg, conn):
    actions.archive_memory(conn, "b")
    conn.commit()
    apply_sync(conn, plan_sync(conn), cfg)
    actions.edit_memory(conn, "a", claim="Keep daily backups.")
    conn.commit()
    plan = plan_sync(conn)
    assert plan.changed and not plan.skipped
    apply_sync(conn, plan, cfg)
    assert "Keep daily backups." in source.read_text()
    assert "Prefer tea." not in source.read_text()


def test_rollback_keeps_untouched_records_ready_for_sync(source, cfg, conn):
    actions.archive_memory(conn, "b")
    conn.commit()
    result = apply_sync(conn, plan_sync(conn), cfg)
    actions.archive_memory(conn, "c")
    conn.commit()
    rollback_event(conn, result.event_id)
    plan = plan_sync(conn)
    assert plan.changed and not plan.skipped
    apply_sync(conn, plan, cfg)
    assert "Prefer tea." in source.read_text()
    assert "Prefer coffee." not in source.read_text()


def test_web_apply_rejects_changes_added_after_preview(source, cfg, conn):
    actions.archive_memory(conn, "b")
    conn.commit()
    client = TestClient(create_app(home=cfg.home), base_url="http://localhost")
    page = client.get("/sync").text
    actions.archive_memory(conn, "c")
    conn.commit()
    before = source.read_bytes()
    response = client.post("/sync/apply", data={
        "csrf_token": form_value(page, "csrf_token"), "confirm": "yes",
        "preview_hash": form_value(page, "preview_hash"),
    }, follow_redirects=False)
    assert "error=" in response.headers["location"]
    assert source.read_bytes() == before
    assert db.get_memory(conn, "b").sync_action == "delete"
    assert db.get_memory(conn, "c").sync_action == "delete"


def test_web_apply_requires_preview_identity(source, cfg, conn):
    actions.archive_memory(conn, "b")
    conn.commit()
    client = TestClient(create_app(home=cfg.home), base_url="http://localhost")
    page = client.get("/sync").text
    before = source.read_bytes()
    response = client.post("/sync/apply", data={
        "csrf_token": form_value(page, "csrf_token"), "confirm": "yes",
    }, follow_redirects=False)
    assert "error=" in response.headers["location"]
    assert source.read_bytes() == before


def test_merge_form_submits_only_the_displayed_pair(source, cfg):
    client = TestClient(create_app(home=cfg.home), base_url="http://localhost")
    page = client.get("/merge?a=b&b=c").text
    assert form_value(page, "canonical") == "b"
    assert form_value(page, "other") == "c"
    assert form_value(page, "claim") == "Prefer tea."


@pytest.mark.parametrize("endpoint", ["approve", "reject"])
def test_unknown_finding_returns_not_found(source, cfg, endpoint):
    client = TestClient(create_app(home=cfg.home), base_url="http://localhost", raise_server_exceptions=False)
    page = client.get("/memory/a").text
    response = client.post(f"/findings/missing/{endpoint}", data={
        "csrf_token": form_value(page, "csrf_token"),
    })
    assert response.status_code == 404


def test_secret_merge_page_has_no_write_form(source, cfg, conn):
    actions.edit_memory(conn, "a", claim="api_key=sk-proj-abcdefghijklmnop1234")
    conn.commit()
    client = TestClient(create_app(home=cfg.home), base_url="http://localhost")
    page = client.get("/merge?a=a&b=b").text
    assert 'method="post" action="/merge"' not in page
    assert 'name="claim"' not in page
    assert "sk-proj-abcdefghijklmnop1234" not in page


def test_preview_refuses_a_new_edit_to_the_same_record(source, cfg, conn):
    actions.edit_memory(conn, "a", claim="First edit.")
    conn.commit()
    client = TestClient(create_app(home=cfg.home), base_url="http://localhost")
    page = client.get("/sync").text
    actions.edit_memory(conn, "a", claim="Second edit.")
    conn.commit()
    original = source.read_bytes()
    response = client.post("/sync/apply", data={
        "csrf_token": form_value(page, "csrf_token"), "confirm": "yes",
        "preview_hash": form_value(page, "preview_hash"),
    }, follow_redirects=False)
    assert "error=" in response.headers["location"]
    assert source.read_bytes() == original
    assert db.get_memory(conn, "a").claim == "Second edit."


def test_nested_anchor_inside_memory_fence_cannot_delete_other_content(tmp_path, cfg, conn):
    path = tmp_path / "MEMORY.md"
    text = (
        "```memory\n<!-- memsift:id=a -->\nA fact.\n"
        "<!-- memsift:id=b -->\nUnrelated memory.\n<!-- /memsift:id=a -->\n```\n"
    )
    path.write_text(text)
    stats = ingest_markdown(conn, [path], cfg)
    assert stats.errors
    assert not db.all_memories(conn)
    assert add_anchors(path, config=cfg, apply=True).errors
    assert path.read_text() == text
