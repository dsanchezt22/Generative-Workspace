import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from src import db
from src.main import app

VALID_RAW = json.dumps(
    {
        "title": "Workout Log",
        "icon": "🏋️",
        "accent": "emerald",
        "components": [{"id": "exercise", "type": "text_input", "label": "Exercise"}],
    }
)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# --- db-level ---


def test_add_and_list_messages_in_order():
    db.init_db()
    sid = db.ensure_session(None)
    db.add_message(sid, "user", "track my workouts", page_id="p1")
    db.add_message(sid, "assistant", "Created Workout Log", page_id="p1", module_id="m1")
    msgs = db.list_messages(sid, page_id="p1")
    assert [m.role for m in msgs] == ["user", "assistant"]
    assert msgs[0].text == "track my workouts"
    assert msgs[1].module_id == "m1"


def test_messages_scoped_by_page():
    db.init_db()
    sid = db.ensure_session(None)
    db.add_message(sid, "user", "on page 1", page_id="p1")
    db.add_message(sid, "user", "on page 2", page_id="p2")
    assert len(db.list_messages(sid, page_id="p1")) == 1
    assert len(db.list_messages(sid, page_id="p2")) == 1
    assert len(db.list_messages(sid)) == 2  # no filter = whole session


def test_clear_messages_for_page_only():
    db.init_db()
    sid = db.ensure_session(None)
    db.add_message(sid, "user", "a", page_id="p1")
    db.add_message(sid, "user", "b", page_id="p2")
    db.clear_messages(sid, page_id="p1")
    assert db.list_messages(sid, page_id="p1") == []
    assert len(db.list_messages(sid, page_id="p2")) == 1


# --- route-level ---


def test_generate_logs_a_conversation_turn(client):
    with patch("src.services.orchestrator.llm.generate", return_value=VALID_RAW):
        client.post("/api/modules/generate", json={"prompt": "track my workouts"})
    convo = client.get("/api/conversations").json()
    roles = [m["role"] for m in convo]
    assert "user" in roles and "assistant" in roles
    assert any(m["text"] == "track my workouts" for m in convo)


def test_clear_conversation_endpoint(client):
    with patch("src.services.orchestrator.llm.generate", return_value=VALID_RAW):
        client.post("/api/modules/generate", json={"prompt": "track my workouts"})
    assert client.get("/api/conversations").json()  # non-empty
    resp = client.delete("/api/conversations")
    assert resp.status_code == 204
    assert client.get("/api/conversations").json() == []


def test_conversation_is_scoped_to_session(client):
    with patch("src.services.orchestrator.llm.generate", return_value=VALID_RAW):
        client.post("/api/modules/generate", json={"prompt": "track my workouts"})
    with TestClient(app) as other:
        assert other.get("/api/conversations").json() == []
