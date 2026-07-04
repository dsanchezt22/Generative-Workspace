from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from src.main import app

from tests.conftest import gen_result

VALID_RAW = '{"title":"T","components":[{"id":"x","type":"text_input","label":"X"}]}'
_VALID_RESULT = gen_result(VALID_RAW)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def client2():
    with TestClient(app) as c:
        yield c


def _ensure_session(client):
    client.get("/api/pages")  # creates session
    return client


# ---------------------------------------------------------------------------
# Page CRUD
# ---------------------------------------------------------------------------


def test_list_pages_returns_default(client):
    resp = client.get("/api/pages")
    assert resp.status_code == 200
    pages = resp.json()
    assert len(pages) == 1
    assert pages[0]["name"] == "Main"


def test_create_page(client):
    _ensure_session(client)
    resp = client.post("/api/pages", json={"name": "Work"})
    assert resp.status_code == 201
    assert resp.json()["name"] == "Work"
    pages = client.get("/api/pages").json()
    assert len(pages) == 2


def test_create_page_rejects_empty_name(client):
    _ensure_session(client)
    resp = client.post("/api/pages", json={"name": "  "})
    assert resp.status_code == 422


def test_rename_page(client):
    _ensure_session(client)
    page_id = client.get("/api/pages").json()[0]["id"]
    resp = client.patch(f"/api/pages/{page_id}", json={"name": "Life"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "Life"


def test_rename_unknown_page_returns_404(client):
    _ensure_session(client)
    resp = client.patch("/api/pages/nope", json={"name": "X"})
    assert resp.status_code == 404


def test_delete_page_removes_it(client):
    _ensure_session(client)
    client.post("/api/pages", json={"name": "Work"})
    pages = client.get("/api/pages").json()
    assert len(pages) == 2
    second_id = pages[1]["id"]
    resp = client.delete(f"/api/pages/{second_id}")
    assert resp.status_code == 204
    assert len(client.get("/api/pages").json()) == 1


def test_delete_last_page_returns_409(client):
    _ensure_session(client)
    page_id = client.get("/api/pages").json()[0]["id"]
    resp = client.delete(f"/api/pages/{page_id}")
    assert resp.status_code == 409


def test_pages_scoped_to_session(client, client2):
    _ensure_session(client)
    client.post("/api/pages", json={"name": "Work"})
    # client2 has its own session — only sees its own default page
    pages2 = client2.get("/api/pages").json()
    assert len(pages2) == 1


def test_update_page_icon_only_leaves_name_untouched(client):
    _ensure_session(client)
    page_id = client.get("/api/pages").json()[0]["id"]
    resp = client.patch(f"/api/pages/{page_id}", json={"icon": "🚀"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["icon"] == "🚀"
    assert body["name"] == "Main"


def test_update_page_no_fields_returns_unchanged(client):
    """An empty patch body touches no columns — the route falls back to a plain
    read (db.get_page) instead of running an UPDATE."""
    _ensure_session(client)
    page_id = client.get("/api/pages").json()[0]["id"]
    resp = client.patch(f"/api/pages/{page_id}", json={})
    assert resp.status_code == 200
    assert resp.json()["id"] == page_id
    assert resp.json()["name"] == "Main"


def test_update_page_sets_parent(client):
    _ensure_session(client)
    parent_id = client.get("/api/pages").json()[0]["id"]
    child = client.post("/api/pages", json={"name": "Child"}).json()
    resp = client.patch(f"/api/pages/{child['id']}", json={"parent_id": parent_id})
    assert resp.status_code == 200
    assert resp.json()["parent_id"] == parent_id


def test_update_page_rejects_self_parenting(client):
    _ensure_session(client)
    page_id = client.get("/api/pages").json()[0]["id"]
    resp = client.patch(f"/api/pages/{page_id}", json={"parent_id": page_id})
    assert resp.status_code == 409


def test_update_page_rejects_cycle(client):
    _ensure_session(client)
    root = client.get("/api/pages").json()[0]["id"]
    child = client.post("/api/pages", json={"name": "Child", "parent_id": root}).json()
    grandchild = client.post(
        "/api/pages", json={"name": "Grandchild", "parent_id": child["id"]}
    ).json()
    # Making root a child of its own grandchild would create a cycle.
    resp = client.patch(f"/api/pages/{root}", json={"parent_id": grandchild["id"]})
    assert resp.status_code == 409


def test_update_page_rejects_blank_name(client):
    _ensure_session(client)
    page_id = client.get("/api/pages").json()[0]["id"]
    resp = client.patch(f"/api/pages/{page_id}", json={"name": "   "})
    assert resp.status_code == 422


def test_reorder_pages_updates_position(client):
    _ensure_session(client)
    first = client.get("/api/pages").json()[0]
    second = client.post("/api/pages", json={"name": "Second"}).json()
    reordered = client.post(
        "/api/pages/reorder", json={"ordered_ids": [second["id"], first["id"]]}
    ).json()
    assert [p["id"] for p in reordered] == [second["id"], first["id"]]


# ---------------------------------------------------------------------------
# Module-page scoping
# ---------------------------------------------------------------------------


def test_modules_belong_to_active_page(client):
    _ensure_session(client)
    page1_id = client.get("/api/pages").json()[0]["id"]
    page2 = client.post("/api/pages", json={"name": "Work"}).json()

    with patch("src.services.orchestrator.llm.generate", return_value=_VALID_RESULT):
        m1 = client.post(f"/api/modules/generate?page_id={page1_id}", json={"prompt": "p1"}).json()
        m2 = client.post(
            f"/api/modules/generate?page_id={page2['id']}", json={"prompt": "p2"}
        ).json()

    assert m1["module"]["page_id"] == page1_id
    assert m2["module"]["page_id"] == page2["id"]

    page1_modules = client.get(f"/api/modules?page_id={page1_id}").json()
    page2_modules = client.get(f"/api/modules?page_id={page2['id']}").json()
    assert len(page1_modules) == 1
    assert len(page2_modules) == 1


def test_list_modules_without_page_returns_all(client):
    _ensure_session(client)
    page1_id = client.get("/api/pages").json()[0]["id"]
    page2 = client.post("/api/pages", json={"name": "Work"}).json()

    with patch("src.services.orchestrator.llm.generate", return_value=_VALID_RESULT):
        client.post(f"/api/modules/generate?page_id={page1_id}", json={"prompt": "p1"})
        client.post(f"/api/modules/generate?page_id={page2['id']}", json={"prompt": "p2"})

    all_modules = client.get("/api/modules").json()
    assert len(all_modules) == 2


# ---------------------------------------------------------------------------
# Portal placement (R-502/R-504) + orphan-safe delete (R-503)
# ---------------------------------------------------------------------------


def test_portal_position_defaults_null(client):
    _ensure_session(client)
    child = client.post("/api/pages", json={"name": "Child"}).json()
    assert child["portal_x"] is None
    assert child["portal_y"] is None


def test_portal_position_persists(client):
    """A child's portal placement persists on the page row (R-504) and reads back
    through the list, not just the PATCH echo."""
    _ensure_session(client)
    parent = client.get("/api/pages").json()[0]["id"]
    child = client.post("/api/pages", json={"name": "Child", "parent_id": parent}).json()
    resp = client.patch(f"/api/pages/{child['id']}", json={"portal_x": 120.5, "portal_y": -40.0})
    assert resp.status_code == 200
    assert resp.json()["portal_x"] == 120.5
    assert resp.json()["portal_y"] == -40.0
    reread = next(p for p in client.get("/api/pages").json() if p["id"] == child["id"])
    assert reread["portal_x"] == 120.5
    assert reread["portal_y"] == -40.0


def test_portal_position_owner_scoped(client, client2):
    """R-903: owner B can't set owner A's page portal — the PATCH 404s and A's
    page is untouched."""
    _ensure_session(client)
    a_page = client.post("/api/pages", json={"name": "A"}).json()
    _ensure_session(client2)
    resp = client2.patch(f"/api/pages/{a_page['id']}", json={"portal_x": 9.0, "portal_y": 9.0})
    assert resp.status_code == 404
    reread = next(p for p in client.get("/api/pages").json() if p["id"] == a_page["id"])
    assert reread["portal_x"] is None
    assert reread["portal_y"] is None


def test_delete_parent_reparents_children_to_grandparent(client):
    """R-503: deleting a mid-tree parent moves its children UP to the grandparent,
    never orphaning them (an orphan → parent_id points at a deleted row → it
    vanishes from the sidebar tree, which renders from root)."""
    _ensure_session(client)
    root = client.get("/api/pages").json()[0]["id"]
    parent = client.post("/api/pages", json={"name": "Parent", "parent_id": root}).json()
    child = client.post("/api/pages", json={"name": "Child", "parent_id": parent["id"]}).json()

    assert client.delete(f"/api/pages/{parent['id']}").status_code == 204

    pages = {p["id"]: p for p in client.get("/api/pages").json()}
    assert parent["id"] not in pages  # deleted
    assert child["id"] in pages  # survived
    assert pages[child["id"]]["parent_id"] == root  # reparented to grandparent


def test_delete_top_level_parent_reparents_children_to_root(client):
    """A top-level parent (parent_id NULL) → its children reparent to root (NULL),
    so they surface as top-level pages rather than orphaning."""
    _ensure_session(client)
    top = client.post("/api/pages", json={"name": "Top"}).json()  # parent_id None
    child = client.post("/api/pages", json={"name": "Child", "parent_id": top["id"]}).json()

    assert client.delete(f"/api/pages/{top['id']}").status_code == 204

    pages = {p["id"]: p for p in client.get("/api/pages").json()}
    assert top["id"] not in pages
    assert child["id"] in pages
    assert pages[child["id"]]["parent_id"] is None  # reparented to root


def test_delete_parent_keeps_child_modules_intact(client):
    """Reparent-not-cascade is non-destructive: a surviving child keeps its
    modules (only the DELETED page's own modules cascade)."""
    _ensure_session(client)
    root = client.get("/api/pages").json()[0]["id"]
    parent = client.post("/api/pages", json={"name": "Parent", "parent_id": root}).json()
    child = client.post("/api/pages", json={"name": "Child", "parent_id": parent["id"]}).json()

    with patch("src.services.orchestrator.llm.generate", return_value=_VALID_RESULT):
        client.post(f"/api/modules/generate?page_id={child['id']}", json={"prompt": "p"})

    assert client.delete(f"/api/pages/{parent['id']}").status_code == 204
    child_modules = client.get(f"/api/modules?page_id={child['id']}").json()
    assert len(child_modules) == 1


def test_page_module_counts_owner_scoped(client, client2):
    """The portal preview's cheap count is a grouped COUNT, owner-scoped (R-903)."""
    _ensure_session(client)
    page = client.get("/api/pages").json()[0]["id"]
    with patch("src.services.orchestrator.llm.generate", return_value=_VALID_RESULT):
        client.post(f"/api/modules/generate?page_id={page}", json={"prompt": "a"})
        client.post(f"/api/modules/generate?page_id={page}", json={"prompt": "b"})
    counts = client.get("/api/pages/counts").json()
    assert counts[page] == 2
    # client2 is a separate owner — sees none of client's counts.
    assert client2.get("/api/pages/counts").json() == {}


def test_migration_adds_portal_columns_idempotently(tmp_path):
    """A legacy pages table (no portal cols) gains portal_x/portal_y on migrate,
    and a second migrate pass is a no-op (a re-ALTER would raise 'duplicate
    column name'). Uses its OWN tmp DB (never the shared _db_path()) so it can't
    perturb the concurrent-migration race test's isolation."""
    import sqlite3

    from src import db as dbmod

    conn = sqlite3.connect(tmp_path / "legacy.db")
    try:
        # Simulate a pre-portal DB: pages WITHOUT the portal columns, then the
        # rest of the schema (pages' CREATE IF NOT EXISTS is skipped → stays legacy).
        conn.execute(
            "CREATE TABLE pages (id TEXT PRIMARY KEY, session_id TEXT NOT NULL,"
            " name TEXT NOT NULL, icon TEXT, parent_id TEXT,"
            " position INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)"
        )
        conn.executescript(dbmod._SCHEMA)
        dbmod._migrate(conn)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(pages)").fetchall()}
        assert {"portal_x", "portal_y"} <= cols
        dbmod._migrate(conn)  # idempotent second pass — must not raise
    finally:
        conn.close()
