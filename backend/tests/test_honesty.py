"""R-403/R-1104: degradation is visible, never cached, never a fake success."""

import pytest
from fastapi.testclient import TestClient
from src import llm
from src.main import app
from src.schema import LLMError, RefusalError


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_cascade_fallback_is_flagged_degraded(monkeypatch):
    monkeypatch.setenv("TRUS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("TRUS_LLM_BASE_URL", "http://localhost:1")  # unreachable
    monkeypatch.setenv("GEMINI_API_KEY", "")  # no gemini → stub fallback
    monkeypatch.setattr(
        llm, "_openai_chat", lambda *a, **k: (_ for _ in ()).throw(LLMError("down"))
    )
    result = llm.generate("track my calories", expect_array=True)
    assert result.degraded is True
    assert result.provider == "stub"
    assert result.text  # still returns usable fallback content


def test_degraded_results_never_enter_the_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TRUS_CACHE", "on")
    from src import db
    from src.services import orchestrator

    monkeypatch.setattr(
        llm,
        "generate",
        lambda *a, **k: llm.GenResult(
            text='[{"refusal": "x"}]', provider="stub", model="stub", degraded=True
        ),
    )
    monkeypatch.setattr(llm, "is_stub_mode", lambda: False)
    with pytest.raises(RefusalError):
        orchestrator.generate_modules("plan my week")  # refusal parse → raises
    assert db.cache_stats()["entries"] == 0  # nothing degraded was stored


def test_stub_mode_refine_is_honest_not_silent(monkeypatch):
    from src.schema import ModuleConfig
    from src.services import orchestrator
    from src.stub_templates import pick_template

    monkeypatch.setattr(llm, "is_stub_mode", lambda: True)
    config = ModuleConfig.model_validate(pick_template("track water"))
    with pytest.raises(LLMError):
        orchestrator.refine_module(config, "add a notes field")


def test_refine_route_returns_422_not_500_on_clarifying_question(client, monkeypatch):
    """R-304 AC: build/ask/refuse each surfaced distinctly — no crash paths."""
    from src.schema import ClarifyingQuestion
    from src.services import orchestrator

    created = client.post(
        "/api/modules",
        json={
            "configs": [
                {
                    "title": "T",
                    "icon": "activity",
                    "components": [{"id": "n", "type": "number_input", "label": "N"}],
                }
            ]
        },
    )
    module_id = created.json()[0]["id"]

    def ask(*a, **k):
        raise ClarifyingQuestion("Which units?")

    monkeypatch.setattr(orchestrator, "refine_module", ask)
    r = client.post(f"/api/modules/{module_id}/refine", json={"prompt": "make it better"})
    assert r.status_code == 422
    assert r.json()["detail"]["question"] == "Which units?"
