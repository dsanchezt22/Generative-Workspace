from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from src import llm
from src.main import app

VALID_RAW = '{"title":"T","components":[{"id":"x","type":"text_input","label":"X"}]}'
_VALID_RESULT = llm.GenResult(text=VALID_RAW, provider="test", model="test")


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
