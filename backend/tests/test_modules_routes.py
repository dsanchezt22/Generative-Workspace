import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from src import llm
from src.main import app
from src.schema import LLMError, ModuleConfig, TextInput

VALID_RAW = json.dumps(
    {
        "title": "Workout Log",
        "components": [{"id": "exercise", "type": "text_input", "label": "Exercise"}],
    }
)


def _gr(text: str) -> llm.GenResult:
    return llm.GenResult(text=text, provider="stub", model="stub")


@pytest.fixture(autouse=True)
def _force_non_stub():
    """These tests mock orchestrator.llm.generate to assert API behavior, so the
    orchestrator must take its real (non-stub) path instead of short-circuiting
    to offline templates."""
    with patch("src.services.orchestrator.llm.is_stub_mode", return_value=False):
        yield


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
    with patch("src.services.orchestrator.llm.generate", return_value=_gr(VALID_RAW)):
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
        return_value=_gr('{"refusal": "Out of scope."}'),
    ):
        resp = client.post("/api/modules/generate", json={"prompt": "build a 3D movie"})
    assert resp.status_code == 422
    assert resp.json()["detail"]["refusal"] == "Out of scope."


def test_list_modules_is_scoped_to_session(client, second_client):
    with patch("src.services.orchestrator.llm.generate", return_value=_gr(VALID_RAW)):
        client.post("/api/modules/generate", json={"prompt": "track my workouts"})
    assert client.get("/api/modules").json()
    assert second_client.get("/api/modules").json() == []


def test_patch_module_updates_config(client):
    with patch("src.services.orchestrator.llm.generate", return_value=_gr(VALID_RAW)):
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
    with patch("src.services.orchestrator.llm.generate", return_value=_gr(VALID_RAW)):
        created = client.post("/api/modules/generate", json={"prompt": "track my workouts"}).json()
    module_id = created["module"]["id"]
    resp = client.delete(f"/api/modules/{module_id}")
    assert resp.status_code == 204
    assert client.get("/api/modules").json() == []


def test_delete_unknown_module_returns_404(client):
    resp = client.delete("/api/modules/nope")
    assert resp.status_code == 404


def test_generate_surfaces_llm_failure_as_503(client):
    with patch(
        "src.services.orchestrator.llm.generate",
        side_effect=LLMError("429 prepayment credits depleted"),
    ):
        resp = client.post("/api/modules/generate", json={"prompt": "track my workouts"})
    assert resp.status_code == 503
    assert "unavailable" in resp.json()["detail"].lower()


def test_delete_is_scoped_to_session(client, second_client):
    with patch("src.services.orchestrator.llm.generate", return_value=_gr(VALID_RAW)):
        created = client.post("/api/modules/generate", json={"prompt": "track my workouts"}).json()
    module_id = created["module"]["id"]
    # A different session must not be able to delete it.
    assert second_client.delete(f"/api/modules/{module_id}").status_code == 404
    assert len(client.get("/api/modules").json()) == 1


def test_undo_endpoint_reverts_module(client):
    with patch("src.services.orchestrator.llm.generate", return_value=_gr(VALID_RAW)):
        created = client.post("/api/modules/generate", json={"prompt": "track my workouts"}).json()
    module_id = created["module"]["id"]
    renamed = ModuleConfig(title="Renamed", components=[TextInput(id="exercise", label="Exercise")])
    client.patch(f"/api/modules/{module_id}", json={"config": renamed.model_dump()})

    resp = client.post(f"/api/modules/{module_id}/undo")
    assert resp.status_code == 200
    assert resp.json()["config"]["title"] == "Workout Log"


def test_undo_with_nothing_to_undo_returns_409(client):
    with patch("src.services.orchestrator.llm.generate", return_value=_gr(VALID_RAW)):
        created = client.post("/api/modules/generate", json={"prompt": "track my workouts"}).json()
    module_id = created["module"]["id"]
    resp = client.post(f"/api/modules/{module_id}/undo")
    assert resp.status_code == 409


def test_history_endpoint_lists_versions(client):
    with patch("src.services.orchestrator.llm.generate", return_value=_gr(VALID_RAW)):
        created = client.post("/api/modules/generate", json={"prompt": "track my workouts"}).json()
    module_id = created["module"]["id"]
    renamed = ModuleConfig(title="Renamed", components=[TextInput(id="exercise", label="Exercise")])
    client.patch(f"/api/modules/{module_id}", json={"config": renamed.model_dump()})

    history = client.get(f"/api/modules/{module_id}/history").json()
    assert [v["config"]["title"] for v in history] == ["Workout Log", "Renamed"]


REFINED_RAW = json.dumps(
    {
        "title": "Workout Log",
        "components": [
            {"id": "exercise", "type": "text_input", "label": "Exercise"},
            {"id": "rest_day", "type": "checkbox", "label": "Rest day"},
        ],
    }
)


def test_refine_endpoint_updates_module(client):
    with patch("src.services.orchestrator.llm.generate", return_value=_gr(VALID_RAW)):
        created = client.post("/api/modules/generate", json={"prompt": "track my workouts"}).json()
    module_id = created["module"]["id"]

    with patch("src.services.orchestrator.llm.generate", return_value=_gr(REFINED_RAW)):
        resp = client.post(
            f"/api/modules/{module_id}/refine", json={"prompt": "add a rest day checkbox"}
        )
    assert resp.status_code == 200, resp.text
    comps = resp.json()["config"]["components"]
    assert any(c["type"] == "checkbox" for c in comps)


def test_refine_endpoint_rejects_empty_prompt(client):
    with patch("src.services.orchestrator.llm.generate", return_value=_gr(VALID_RAW)):
        created = client.post("/api/modules/generate", json={"prompt": "track my workouts"}).json()
    module_id = created["module"]["id"]
    resp = client.post(f"/api/modules/{module_id}/refine", json={"prompt": "  "})
    assert resp.status_code == 422


def test_refine_endpoint_returns_404_for_unknown_module(client):
    resp = client.post("/api/modules/nope/refine", json={"prompt": "add a checkbox"})
    assert resp.status_code == 404


def test_refine_endpoint_surfaces_refusal_as_422(client):
    with patch("src.services.orchestrator.llm.generate", return_value=_gr(VALID_RAW)):
        created = client.post("/api/modules/generate", json={"prompt": "track my workouts"}).json()
    module_id = created["module"]["id"]
    with patch(
        "src.services.orchestrator.llm.generate",
        return_value=_gr('{"refusal": "Cannot embed video."}'),
    ):
        resp = client.post(f"/api/modules/{module_id}/refine", json={"prompt": "embed a video"})
    assert resp.status_code == 422
    assert resp.json()["detail"]["refusal"] == "Cannot embed video."


def test_refine_creates_history_entry(client):
    with patch("src.services.orchestrator.llm.generate", return_value=_gr(VALID_RAW)):
        created = client.post("/api/modules/generate", json={"prompt": "track my workouts"}).json()
    module_id = created["module"]["id"]

    with patch("src.services.orchestrator.llm.generate", return_value=_gr(REFINED_RAW)):
        client.post(f"/api/modules/{module_id}/refine", json={"prompt": "add a rest day checkbox"})

    history = client.get(f"/api/modules/{module_id}/history").json()
    assert len(history) == 2


def test_refine_scoped_to_session(client, second_client):
    with patch("src.services.orchestrator.llm.generate", return_value=_gr(VALID_RAW)):
        created = client.post("/api/modules/generate", json={"prompt": "track my workouts"}).json()
    module_id = created["module"]["id"]
    resp = second_client.post(f"/api/modules/{module_id}/refine", json={"prompt": "add a checkbox"})
    assert resp.status_code == 404


METRIC_RAW = json.dumps(
    {
        "title": "Dashboard",
        "components": [
            {
                "id": "total_reps",
                "type": "metric",
                "label": "Total Reps",
                "formula": "sum",
                "source_component_id": "reps",
            }
        ],
    }
)


def test_generate_module_with_metric_component(client):
    with patch("src.services.orchestrator.llm.generate", return_value=_gr(METRIC_RAW)):
        resp = client.post("/api/modules/generate", json={"prompt": "dashboard"})
    assert resp.status_code == 200, resp.text
    comp = resp.json()["module"]["config"]["components"][0]
    assert comp["type"] == "metric"
    assert comp["formula"] == "sum"
    assert comp["source_component_id"] == "reps"


def test_workspace_insights_returns_module(client):
    with patch("src.services.orchestrator.llm.generate", return_value=_gr(VALID_RAW)):
        client.post("/api/modules/generate", json={"prompt": "workout"})
        client.post("/api/modules/generate", json={"prompt": "meals"})

    with patch("src.services.orchestrator.llm.generate", return_value=_gr(METRIC_RAW)):
        resp = client.post("/api/workspace/insights")
    assert resp.status_code == 200, resp.text
    assert resp.json()["module"]["config"]["title"] == "Dashboard"


def test_workspace_insights_requires_modules(client):
    resp = client.post("/api/workspace/insights")
    assert resp.status_code == 422


def test_workspace_insights_scoped_to_session(client, second_client):
    with patch("src.services.orchestrator.llm.generate", return_value=_gr(VALID_RAW)):
        client.post("/api/modules/generate", json={"prompt": "workout"})
        client.post("/api/modules/generate", json={"prompt": "meals"})
    # second_client has no modules — should get 422
    resp = second_client.post("/api/workspace/insights")
    assert resp.status_code == 422


def test_generate_passes_existing_modules_context(client):
    with patch("src.services.orchestrator.llm.generate", return_value=_gr(VALID_RAW)) as mock_gen:
        client.post("/api/modules/generate", json={"prompt": "workout"})
        client.post("/api/modules/generate", json={"prompt": "another module"})
    # Second call should have received context with existing modules
    second_call_prompt = mock_gen.call_args_list[1][0][0]
    assert "Existing modules" in second_call_prompt


def test_generate_returns_question_when_clarification_needed(client):
    with patch(
        "src.services.orchestrator.llm.generate",
        return_value=_gr('{"question": "How many meals per day?"}'),
    ):
        resp = client.post("/api/modules/generate", json={"prompt": "track food"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["module"] is None
    assert "meals" in body["question"].lower()


def test_generate_with_combined_prompt_produces_module(client):
    with patch("src.services.orchestrator.llm.generate", return_value=_gr(VALID_RAW)):
        resp = client.post(
            "/api/modules/generate",
            json={"prompt": "track food — 3 meals per day"},
        )
    assert resp.status_code == 200
    assert resp.json()["module"] is not None


# ---------------------------------------------------------------------------
# Preview-then-accept: POST /modules/preview proposes without persisting;
# POST /modules persists what the caller accepts.
# ---------------------------------------------------------------------------


def test_preview_does_not_persist_modules(client):
    with patch("src.services.orchestrator.llm.generate", return_value=_gr(VALID_RAW)):
        resp = client.post("/api/modules/preview", json={"prompt": "track my workouts"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["module"] is None  # preview never returns a stored module
    assert body["previews"][0]["title"] == "Workout Log"
    # Nothing was written to the canvas.
    assert client.get("/api/modules").json() == []


def test_accept_preview_persists_modules(client):
    with patch("src.services.orchestrator.llm.generate", return_value=_gr(VALID_RAW)):
        previewed = client.post("/api/modules/preview", json={"prompt": "track my workouts"}).json()
    assert client.get("/api/modules").json() == []  # still nothing persisted

    accepted = client.post(
        "/api/modules",
        json={"configs": previewed["previews"], "prompt": "track my workouts"},
    )
    assert accepted.status_code == 201
    stored = accepted.json()
    assert stored[0]["config"]["title"] == "Workout Log"
    assert len(client.get("/api/modules").json()) == 1

    # The accepted prompt is logged as a conversation turn.
    convo = client.get("/api/conversations").json()
    assert any(m["text"] == "track my workouts" for m in convo)


def test_preview_rejects_empty_prompt(client):
    resp = client.post("/api/modules/preview", json={"prompt": "   "})
    assert resp.status_code == 422


def test_preview_returns_question_when_clarification_needed(client):
    with patch(
        "src.services.orchestrator.llm.generate",
        return_value=_gr('{"question": "How many meals per day?"}'),
    ):
        resp = client.post("/api/modules/preview", json={"prompt": "track food"})
    assert resp.status_code == 200
    assert resp.json()["previews"] is None
    assert "meals" in resp.json()["question"].lower()


def test_preview_surfaces_refusal_as_422(client):
    with patch(
        "src.services.orchestrator.llm.generate",
        return_value=_gr('{"refusal": "Out of scope."}'),
    ):
        resp = client.post("/api/modules/preview", json={"prompt": "build a 3D movie"})
    assert resp.status_code == 422
    assert resp.json()["detail"]["refusal"] == "Out of scope."


def test_preview_surfaces_llm_failure_as_503(client):
    with patch(
        "src.services.orchestrator.llm.generate",
        side_effect=LLMError("429 prepayment credits depleted"),
    ):
        resp = client.post("/api/modules/preview", json={"prompt": "track my workouts"})
    assert resp.status_code == 503


def test_insert_modules_without_prompt_does_not_log(client):
    """No `prompt` on the accept payload → no conversation turn logged."""
    resp = client.post(
        "/api/modules",
        json={
            "configs": [
                {"title": "T", "components": [{"id": "a", "type": "text_input", "label": "A"}]}
            ]
        },
    )
    assert resp.status_code == 201
    convo = client.get("/api/conversations").json()
    assert not any(m["role"] == "user" for m in convo)


# ---------------------------------------------------------------------------
# Onboarding seed — no LLM cost, never reseeds an existing workspace.
# ---------------------------------------------------------------------------


def test_seed_onboarding_creates_starter_modules(client):
    resp = client.post("/api/onboarding/seed")
    assert resp.status_code == 200, resp.text
    seeded = resp.json()
    assert len(seeded) == 3
    titles = {m["config"]["title"] for m in seeded}
    assert "Today" in titles
    assert client.get("/api/modules").json()  # persisted


def test_seed_onboarding_does_not_reseed_existing_workspace(client):
    with patch("src.services.orchestrator.llm.generate", return_value=_gr(VALID_RAW)):
        client.post("/api/modules/generate", json={"prompt": "track my workouts"})
    assert len(client.get("/api/modules").json()) == 1

    seeded_again = client.post("/api/onboarding/seed").json()
    assert len(seeded_again) == 1  # unchanged, not reseeded
    assert len(client.get("/api/modules").json()) == 1


# ---------------------------------------------------------------------------
# Archive / restore / duplicate
# ---------------------------------------------------------------------------


def _insert_direct(client, title="Original") -> dict:
    resp = client.post(
        "/api/modules",
        json={
            "configs": [
                {"title": title, "components": [{"id": "a", "type": "text_input", "label": "A"}]}
            ]
        },
    )
    return resp.json()[0]


def test_archive_then_restore_module_via_routes(client):
    m = _insert_direct(client)
    archived = client.post(f"/api/modules/{m['id']}/archive")
    assert archived.status_code == 200
    assert archived.json()["archived"] is True
    assert client.get("/api/modules").json() == []
    assert [a["id"] for a in client.get("/api/modules/archived").json()] == [m["id"]]

    restored = client.post(f"/api/modules/{m['id']}/restore")
    assert restored.status_code == 200
    assert restored.json()["archived"] is False
    assert len(client.get("/api/modules").json()) == 1
    assert client.get("/api/modules/archived").json() == []


def test_archive_unknown_module_returns_404(client):
    assert client.post("/api/modules/nope/archive").status_code == 404


def test_restore_unknown_module_returns_404(client):
    assert client.post("/api/modules/nope/restore").status_code == 404


def test_duplicate_module_via_route(client):
    m = _insert_direct(client, "Original")
    dup = client.post(f"/api/modules/{m['id']}/duplicate")
    assert dup.status_code == 200
    assert dup.json()["config"]["title"] == "Original copy"
    assert dup.json()["id"] != m["id"]
    assert len(client.get("/api/modules").json()) == 2


def test_duplicate_unknown_module_returns_404(client):
    assert client.post("/api/modules/nope/duplicate").status_code == 404


# ---------------------------------------------------------------------------
# refine / insights — LLMError and RefusalError paths not covered elsewhere
# ---------------------------------------------------------------------------


def test_refine_endpoint_surfaces_llm_failure_as_503(client):
    with patch("src.services.orchestrator.llm.generate", return_value=_gr(VALID_RAW)):
        created = client.post("/api/modules/generate", json={"prompt": "track my workouts"}).json()
    module_id = created["module"]["id"]
    with patch(
        "src.services.orchestrator.llm.generate",
        side_effect=LLMError("endpoint unreachable"),
    ):
        resp = client.post(f"/api/modules/{module_id}/refine", json={"prompt": "add a field"})
    assert resp.status_code == 503


def test_workspace_insights_surfaces_refusal_as_422(client):
    with patch("src.services.orchestrator.llm.generate", return_value=_gr(VALID_RAW)):
        client.post("/api/modules/generate", json={"prompt": "workout"})
    with patch(
        "src.services.orchestrator.llm.generate",
        return_value=_gr(
            '{"refusal": "Not enough data across modules to synthesize a dashboard."}'
        ),
    ):
        resp = client.post("/api/workspace/insights")
    assert resp.status_code == 422
    assert "refusal" in resp.json()["detail"]


def test_workspace_insights_surfaces_llm_failure_as_503(client):
    with patch("src.services.orchestrator.llm.generate", return_value=_gr(VALID_RAW)):
        client.post("/api/modules/generate", json={"prompt": "workout"})
    with patch(
        "src.services.orchestrator.llm.generate",
        side_effect=LLMError("quota exceeded"),
    ):
        resp = client.post("/api/workspace/insights")
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# F5 — LLMError detail is sanitized: internal endpoint URLs and upstream response
# bodies embedded in the error must never reach the client (refine/insights used
# to pass str(e) straight through).
# ---------------------------------------------------------------------------


def test_refine_llm_error_detail_is_sanitized(client):
    with patch("src.services.orchestrator.llm.generate", return_value=_gr(VALID_RAW)):
        created = client.post("/api/modules/generate", json={"prompt": "track my workouts"}).json()
    module_id = created["module"]["id"]
    leak = "Could not reach the LLM endpoint at http://10.1.2.3:11434/v1: refused"
    with patch("src.services.orchestrator.llm.generate", side_effect=LLMError(leak)):
        resp = client.post(f"/api/modules/{module_id}/refine", json={"prompt": "add a field"})
    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert "10.1.2.3" not in detail
    assert "unreachable" in detail.lower()


def test_insights_llm_error_detail_is_sanitized(client):
    with patch("src.services.orchestrator.llm.generate", return_value=_gr(VALID_RAW)):
        client.post("/api/modules/generate", json={"prompt": "workout"})
    leak = "LLM endpoint returned HTTP 500: <html>trace 192.168.9.9 stack</html>"
    with patch("src.services.orchestrator.llm.generate", side_effect=LLMError(leak)):
        resp = client.post("/api/workspace/insights")
    assert resp.status_code == 503
    assert "192.168.9.9" not in resp.json()["detail"]


def test_generate_llm_error_detail_is_sanitized(client):
    leak = "Could not reach the LLM endpoint at http://192.0.2.7:8000/v1: refused"
    with patch("src.services.orchestrator.llm.generate", side_effect=LLMError(leak)):
        resp = client.post("/api/modules/generate", json={"prompt": "track my workouts"})
    assert resp.status_code == 503
    assert "192.0.2.7" not in resp.json()["detail"]
