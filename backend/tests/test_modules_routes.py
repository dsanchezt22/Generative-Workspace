import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.schema import ModuleConfig, TextInput

VALID_RAW = json.dumps({
    "title": "Workout Log",
    "components": [{"id": "exercise", "type": "text_input", "label": "Exercise"}],
})


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def second_client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_generate_returns_module_and_sets_session(client):
    with patch("src.services.orchestrator.llm.generate", return_value=VALID_RAW):
        resp = client.post("/api/modules/generate", json={"prompt": "track my workouts"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["module"]["config"]["title"] == "Workout Log"
    assert "trus_sid" in resp.cookies


def test_generate_rejects_empty_prompt(client):
    resp = client.post("/api/modules/generate", json={"prompt": "   "})
    assert resp.status_code == 422


def test_generate_surfaces_refusal_as_422(client):
    with patch(
        "src.services.orchestrator.llm.generate",
        return_value='{"refusal": "Out of scope."}',
    ):
        resp = client.post("/api/modules/generate", json={"prompt": "build a 3D movie"})
    assert resp.status_code == 422
    assert resp.json()["detail"]["refusal"] == "Out of scope."


def test_list_modules_is_scoped_to_session(client, second_client):
    with patch("src.services.orchestrator.llm.generate", return_value=VALID_RAW):
        client.post("/api/modules/generate", json={"prompt": "track my workouts"})
    assert client.get("/api/modules").json()
    assert second_client.get("/api/modules").json() == []


def test_patch_module_updates_config(client):
    with patch("src.services.orchestrator.llm.generate", return_value=VALID_RAW):
        created = client.post("/api/modules/generate", json={"prompt": "track my workouts"}).json()
    module_id = created["module"]["id"]

    new_config = ModuleConfig(
        title="Renamed",
        components=[TextInput(id="exercise", label="Exercise")],
    )
    resp = client.patch(f"/api/modules/{module_id}", json={"config": new_config.model_dump()})
    assert resp.status_code == 200, resp.text
    assert resp.json()["config"]["title"] == "Renamed"


def test_patch_unknown_module_returns_404(client):
    new_config = ModuleConfig(
        title="x",
        components=[TextInput(id="a", label="A")],
    )
    resp = client.patch("/api/modules/nope", json={"config": new_config.model_dump()})
    assert resp.status_code == 404


def test_delete_module_removes_it(client):
    with patch("src.services.orchestrator.llm.generate", return_value=VALID_RAW):
        created = client.post("/api/modules/generate", json={"prompt": "track my workouts"}).json()
    module_id = created["module"]["id"]
    resp = client.delete(f"/api/modules/{module_id}")
    assert resp.status_code == 204
    assert client.get("/api/modules").json() == []


def test_delete_unknown_module_returns_404(client):
    resp = client.delete("/api/modules/nope")
    assert resp.status_code == 404


def test_generate_surfaces_llm_failure_as_503(client):
    from src.schema import LLMError

    with patch(
        "src.services.orchestrator.llm.generate",
        side_effect=LLMError("429 prepayment credits depleted"),
    ):
        resp = client.post("/api/modules/generate", json={"prompt": "track my workouts"})
    assert resp.status_code == 503
    assert "unavailable" in resp.json()["detail"].lower()


def test_delete_is_scoped_to_session(client, second_client):
    with patch("src.services.orchestrator.llm.generate", return_value=VALID_RAW):
        created = client.post("/api/modules/generate", json={"prompt": "track my workouts"}).json()
    module_id = created["module"]["id"]
    # A different session must not be able to delete it.
    assert second_client.delete(f"/api/modules/{module_id}").status_code == 404
    assert len(client.get("/api/modules").json()) == 1
