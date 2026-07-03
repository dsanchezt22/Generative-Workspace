"""POST /api/modules/generate_from_file.

R-211: a file upload must be grounded in the document's actual content. When the
active model configuration cannot read a file (offline/stub, or an openai-compat
endpoint that can't take documents), the route refuses honestly (422) instead of
silently degrading to a generic keyword template while claiming success.
"""

import json

import pytest
from fastapi.testclient import TestClient
from src import llm
from src.main import app
from src.services import orchestrator


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_generate_from_file_stub_mode_refuses_honestly(client):
    """R-211: in stub mode the model never read the file, so the upload is refused
    (422) — nothing is persisted and no 'Created …' turn is logged as a fake success."""
    resp = client.post(
        "/api/modules/generate_from_file",
        files={"file": ("workouts.txt", b"some file content", "text/plain")},
        data={"prompt": "track my workouts"},
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert "refusal" in detail
    assert "current model configuration" in detail["refusal"]
    # Nothing was written to the canvas …
    assert client.get("/api/modules").json() == []
    # … and no fake "Created …" assistant turn was logged.
    convo = client.get("/api/conversations").json()
    assert not any(m["text"].startswith("Created ") for m in convo if m["role"] == "assistant")


def test_generate_from_file_defaults_prompt_to_filename(client, monkeypatch):
    """A blank prompt defaults the instruction to the filename — and that filename
    must actually reach the generation prompt (not just be echoed back)."""
    captured: dict = {}

    def fake_generate_from_file(user_message, system, data, mime):
        captured["user_message"] = user_message
        return json.dumps(
            [{"title": "Meals", "components": [{"id": "cal", "type": "kpi", "label": "Calories"}]}]
        )

    monkeypatch.setattr(llm, "is_stub_mode", lambda: False)
    monkeypatch.setattr(llm, "generate_from_file", fake_generate_from_file)

    resp = client.post(
        "/api/modules/generate_from_file",
        files={"file": ("meals.png", b"\x89PNG\r\n", "image/png")},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["module"] is not None
    # The filename reached the actual generation prompt sent to the model.
    assert "meals.png" in captured["user_message"]


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


def test_generate_from_file_small_file_reads_fully(client, monkeypatch):
    """F3: the read-cap (15MB+1) must not truncate a normal small upload."""
    monkeypatch.setattr(llm, "is_stub_mode", lambda: False)
    monkeypatch.setattr(
        llm,
        "generate_from_file",
        lambda *a, **k: json.dumps(
            [{"title": "OK", "components": [{"id": "a", "type": "text_input", "label": "A"}]}]
        ),
    )
    resp = client.post(
        "/api/modules/generate_from_file",
        files={"file": ("small.txt", b"tiny content", "text/plain")},
        data={"prompt": "make a tool"},
    )
    assert resp.status_code == 200, resp.text


def test_generate_from_file_non_stub_empty_sentinel_refuses(client, monkeypatch):
    """When the model config can't read the file it returns the '{}' sentinel →
    honest 422 refusal, nothing persisted."""
    monkeypatch.setattr(llm, "is_stub_mode", lambda: False)
    monkeypatch.setattr(llm, "generate_from_file", lambda *a, **k: "{}")

    resp = client.post(
        "/api/modules/generate_from_file",
        files={"file": ("report.pdf", b"%PDF-1.4 ...", "application/pdf")},
        data={"prompt": "build tools from this"},
    )
    assert resp.status_code == 422, resp.text
    assert "refusal" in resp.json()["detail"]
    assert client.get("/api/modules").json() == []


def test_generate_from_file_non_stub_happy_path_persists_and_grounds(client, monkeypatch):
    """A live model that actually reads the file returns modules grounded in it →
    200, persisted onto the canvas, and the conversation logs the filename."""
    grounded = json.dumps(
        [
            {
                "title": "Q3 Expenses",
                "components": [
                    {
                        "id": "rows",
                        "type": "table",
                        "label": "Line items",
                        "columns": ["Item", "USD"],
                    }
                ],
            }
        ]
    )
    monkeypatch.setattr(llm, "is_stub_mode", lambda: False)
    monkeypatch.setattr(llm, "generate_from_file", lambda *a, **k: grounded)

    resp = client.post(
        "/api/modules/generate_from_file",
        files={"file": ("expenses.csv", b"Item,USD\nCoffee,4", "text/csv")},
        data={"prompt": "turn this into a tracker"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["module"]["config"]["title"] == "Q3 Expenses"
    # Persisted, not just returned.
    assert len(client.get("/api/modules").json()) == 1
    convo = client.get("/api/conversations").json()
    assert any("expenses.csv" in m["text"] for m in convo if m["role"] == "user")


def test_generate_from_file_route_module_is_reachable():
    """Guard: the route module imports the orchestrator symbol it delegates to."""
    assert hasattr(orchestrator, "generate_modules_from_file")
