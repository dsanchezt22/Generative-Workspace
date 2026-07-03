"""Snapshot lifecycle: create -> list -> restore -> delete.

A point-in-time capture of a page's modules. Covers both the db.py layer
directly and the /api/pages/{page_id}/snapshots + /api/snapshots/{id} routes.
"""

import pytest
from fastapi.testclient import TestClient
from src import db
from src.main import app
from src.schema import ModuleConfig, TextInput


def _cfg(title: str) -> ModuleConfig:
    return ModuleConfig(title=title, components=[TextInput(id="a", label="A")])


# ---------------------------------------------------------------------------
# db-level
# ---------------------------------------------------------------------------


def test_create_snapshot_captures_current_modules():
    db.init_db()
    sid = db.ensure_session(None)
    page = db.ensure_default_page(sid)
    db.insert_module(sid, _cfg("A"), page_id=page.id)
    db.insert_module(sid, _cfg("B"), page_id=page.id)

    snap = db.create_snapshot(sid, page.id, "Before cleanup")
    assert snap.label == "Before cleanup"
    assert snap.module_count == 2
    assert snap.page_id == page.id


def test_create_snapshot_stores_label_verbatim():
    db.init_db()
    sid = db.ensure_session(None)
    page = db.ensure_default_page(sid)
    # The db layer stores the label as given — the "Snapshot" default for a blank
    # label is a ROUTE concern (see test_create_snapshot_defaults_label_when_blank),
    # not a db one. A blank label stays blank here.
    snap = db.create_snapshot(sid, page.id, "")
    assert snap.label == ""
    assert snap.module_count == 0


def test_list_snapshots_scoped_to_page_and_ordered_desc():
    db.init_db()
    sid = db.ensure_session(None)
    p1 = db.ensure_default_page(sid)
    p2 = db.create_page(sid, "Other")
    db.create_snapshot(sid, p1.id, "first")
    db.create_snapshot(sid, p1.id, "second")
    db.create_snapshot(sid, p2.id, "on p2")

    p1_snaps = db.list_snapshots(sid, p1.id)
    assert [s.label for s in p1_snaps] == ["second", "first"]  # newest first
    assert len(db.list_snapshots(sid, p2.id)) == 1
    assert len(db.list_snapshots(sid)) == 3  # no filter = whole session


def test_restore_snapshot_replaces_live_modules():
    db.init_db()
    sid = db.ensure_session(None)
    page = db.ensure_default_page(sid)
    kept = db.insert_module(sid, _cfg("Kept"), page_id=page.id)
    snap = db.create_snapshot(sid, page.id, "checkpoint")

    # Mutate the live page after the snapshot: delete the original, add a new one.
    db.delete_module(sid, kept.id)
    db.insert_module(sid, _cfg("Added later"), page_id=page.id)
    assert [m.config.title for m in db.list_modules(sid, page.id)] == ["Added later"]

    ok = db.restore_snapshot(sid, snap.id)
    assert ok is True
    restored_titles = [m.config.title for m in db.list_modules(sid, page.id)]
    assert restored_titles == ["Kept"]  # back to the snapshot's state


def test_restore_unknown_snapshot_returns_false():
    db.init_db()
    sid = db.ensure_session(None)
    assert db.restore_snapshot(sid, "not-a-real-id") is False


def test_restore_snapshot_scoped_to_session():
    db.init_db()
    s1 = db.ensure_session(None)
    s2 = db.ensure_session(None)
    page = db.ensure_default_page(s1)
    snap = db.create_snapshot(s1, page.id, "s1 snapshot")
    assert db.restore_snapshot(s2, snap.id) is False  # wrong session


def test_delete_snapshot_removes_it():
    db.init_db()
    sid = db.ensure_session(None)
    page = db.ensure_default_page(sid)
    snap = db.create_snapshot(sid, page.id, "temp")
    assert db.delete_snapshot(sid, snap.id) is True
    assert db.list_snapshots(sid, page.id) == []


def test_delete_unknown_snapshot_returns_false():
    db.init_db()
    sid = db.ensure_session(None)
    assert db.delete_snapshot(sid, "nope") is False


def test_list_snapshots_tolerates_corrupt_data_json(monkeypatch, tmp_path):
    """A snapshot row with unparseable data_json still lists (module_count=0)
    instead of blowing up the whole listing."""
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    sid = db.ensure_session(None)
    page = db.ensure_default_page(sid)
    with db._conn() as c:
        c.execute(
            "INSERT INTO snapshots (id, session_id, page_id, label, data_json, created_at) "
            "VALUES ('bad-snap', ?, ?, 'corrupt', 'not json', '2024-01-01T00:00:00')",
            (sid, page.id),
        )
    snaps = db.list_snapshots(sid, page.id)
    assert [s.module_count for s in snaps if s.id == "bad-snap"] == [0]


# ---------------------------------------------------------------------------
# route-level
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def second_client():
    with TestClient(app) as c:
        yield c


def _page_id(client) -> str:
    return client.get("/api/pages").json()[0]["id"]


def test_snapshot_routes_full_lifecycle(client):
    page_id = _page_id(client)
    client.post(
        "/api/modules",
        json={
            "configs": [
                {"title": "Keep", "components": [{"id": "a", "type": "text_input", "label": "A"}]}
            ]
        },
        params={"page_id": page_id},
    )

    created = client.post(f"/api/pages/{page_id}/snapshots", json={"label": "v1"})
    assert created.status_code == 201
    snap = created.json()
    assert snap["label"] == "v1"
    assert snap["module_count"] == 1

    listed = client.get(f"/api/pages/{page_id}/snapshots").json()
    assert len(listed) == 1 and listed[0]["id"] == snap["id"]

    # Mutate the page, then restore — the added module must disappear.
    client.post(
        "/api/modules",
        json={
            "configs": [
                {
                    "title": "Extra",
                    "components": [{"id": "b", "type": "text_input", "label": "B"}],
                }
            ]
        },
        params={"page_id": page_id},
    )
    assert len(client.get(f"/api/modules?page_id={page_id}").json()) == 2

    restore = client.post(f"/api/snapshots/{snap['id']}/restore")
    assert restore.status_code == 204
    remaining = client.get(f"/api/modules?page_id={page_id}").json()
    assert [m["config"]["title"] for m in remaining] == ["Keep"]

    delete = client.delete(f"/api/snapshots/{snap['id']}")
    assert delete.status_code == 204
    assert client.get(f"/api/pages/{page_id}/snapshots").json() == []


def test_create_snapshot_defaults_label_when_blank(client):
    page_id = _page_id(client)
    resp = client.post(f"/api/pages/{page_id}/snapshots", json={"label": "   "})
    assert resp.status_code == 201
    assert resp.json()["label"] == "Snapshot"


def test_restore_unknown_snapshot_returns_404(client):
    resp = client.post("/api/snapshots/does-not-exist/restore")
    assert resp.status_code == 404


def test_delete_unknown_snapshot_returns_404(client):
    resp = client.delete("/api/snapshots/does-not-exist")
    assert resp.status_code == 404


def test_snapshots_scoped_to_session(client, second_client):
    page_id = _page_id(client)
    created = client.post(f"/api/pages/{page_id}/snapshots", json={"label": "mine"}).json()
    # A different session cannot restore or delete it.
    assert second_client.post(f"/api/snapshots/{created['id']}/restore").status_code == 404
    assert second_client.delete(f"/api/snapshots/{created['id']}").status_code == 404
