"""POST /api/modules/generate_from_file.

Deliberately does NOT force non-stub mode (unlike test_modules_routes.py) —
the point is to exercise orchestrator.generate_modules_from_file's REAL stub-mode
behavior: it ignores the uploaded file entirely and falls back to
pick_system(prompt), same as the text-only decompose path. That is the actual
current behavior (read from src/services/orchestrator.py), not a RefusalError.
"""

import pytest
from fastapi.testclient import TestClient
from src.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_generate_from_file_stub_mode_uses_pick_system(client):
    resp = client.post(
        "/api/modules/generate_from_file",
        files={"file": ("workouts.txt", b"some file content", "text/plain")},
        data={"prompt": "track my workouts"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["module"]["config"]["title"] == "Workout Log"
    # Persisted onto the canvas, not just returned.
    assert len(client.get("/api/modules").json()) >= 1


def test_generate_from_file_defaults_prompt_to_filename_when_blank(client):
    resp = client.post(
        "/api/modules/generate_from_file",
        files={"file": ("meals.png", b"\x89PNG\r\n", "image/png")},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["module"] is not None


def test_generate_from_file_rejects_empty_file(client):
    resp = client.post(
        "/api/modules/generate_from_file",
        files={"file": ("empty.txt", b"", "text/plain")},
    )
    assert resp.status_code == 422


def test_generate_from_file_rejects_oversized_file(client):
    oversized = b"x" * (15 * 1024 * 1024 + 1)
    resp = client.post(
        "/api/modules/generate_from_file",
        files={"file": ("big.bin", oversized, "application/octet-stream")},
    )
    assert resp.status_code == 413


def test_generate_from_file_logs_conversation_with_filename(client):
    client.post(
        "/api/modules/generate_from_file",
        files={"file": ("workouts.txt", b"content", "text/plain")},
        data={"prompt": "track my workouts"},
    )
    convo = client.get("/api/conversations").json()
    assert any("workouts.txt" in m["text"] for m in convo if m["role"] == "user")
