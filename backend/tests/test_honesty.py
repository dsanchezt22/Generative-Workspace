"""R-403/R-1104: degradation is visible, never cached, never a fake success."""

import json

import pytest
from fastapi.testclient import TestClient
from src import llm
from src.main import app
from src.schema import LLMError

from tests.conftest import fake_generate


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


_VALID_MODULES_RAW = json.dumps(
    [
        {
            "title": "Itinerary",
            "icon": "plane",
            "accent": "sky",
            "components": [{"id": "days", "type": "calendar", "label": "Days"}],
        },
    ]
)


def test_degraded_results_never_enter_the_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TRUS_CACHE", "on")
    from src import db
    from src.services import orchestrator

    monkeypatch.setattr(llm, "generate", fake_generate(_VALID_MODULES_RAW, degraded=True))
    monkeypatch.setattr(llm, "is_stub_mode", lambda: False)
    mods = orchestrator.generate_modules("plan my degraded week")  # succeeds — parses fine
    assert mods[0].title == "Itinerary"
    assert db.cache_stats()["entries"] == 0  # nothing degraded was stored


def test_non_degraded_results_do_enter_the_cache(monkeypatch, tmp_path):
    """Positive control for the guard above: a definitely-non-degraded call stores."""
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TRUS_CACHE", "on")
    from src import db
    from src.services import orchestrator

    monkeypatch.setattr(llm, "generate", fake_generate(_VALID_MODULES_RAW))
    monkeypatch.setattr(llm, "is_stub_mode", lambda: False)
    mods = orchestrator.generate_modules("plan my clean week")
    assert mods[0].title == "Itinerary"
    assert db.cache_stats()["entries"] == 1


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


def test_insights_route_returns_422_not_500_on_clarifying_question(client, monkeypatch):
    """Mirrors test_refine_route_returns_422_not_500_on_clarifying_question, for
    POST /api/workspace/insights."""
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
    assert created.json()  # a module is on the canvas

    def ask(*a, **k):
        raise ClarifyingQuestion("Which metric?")

    monkeypatch.setattr(orchestrator, "synthesize_workspace", ask)
    r = client.post("/api/workspace/insights")
    assert r.status_code == 422
    assert r.json()["detail"]["question"] == "Which metric?"


# ---------------------------------------------------------------------------
# R-403 on the vision/capture path — the studio auto-seed must not be fooled by
# a degraded TRANSFORM-stage call even when capability coverage still scores
# "high" (see backend/tests/test_capture.py for the un-degraded counterparts).
# ---------------------------------------------------------------------------

_CAPTURE_PNG = b"\x89PNG\r\n\x1a\n"  # bytes are irrelevant — vision is mocked

_CAPTURE_IR = {
    "schema": "trus-capture-ir/1",
    "app_kind": "calorie tracker",
    "summary": "A calorie tracker with a food diary.",
    "nodes": [
        {
            "id": "n1",
            "ui_type": "food_table",
            "role": "table",
            "label": "Food diary",
            "columns": ["Food", "Calories"],
        },
    ],
    "capabilities": ["log a food entry"],
}

_CAPTURE_CONFIG = {
    "title": "Calorie Tracker",
    "components": [
        {"id": "food", "type": "table", "label": "Food diary", "columns": ["Food", "Calories"]},
    ],
}


def test_degraded_capture_is_never_auto_seeded(client, monkeypatch):
    """R-403: capture_layout → transform_ir → llm.generate() can cascade-degrade.
    A degraded TRANSFORM result must never join the shared generation seed pool,
    even when capability coverage still scores "high"."""
    from src import semantic_cache

    monkeypatch.setenv("TRUS_LLM_PROVIDER", "stub")
    monkeypatch.delenv("TRUS_LLM_BASE_URL", raising=False)

    monkeypatch.setattr(llm, "vision_capture", lambda *a, **k: json.dumps(_CAPTURE_IR))
    monkeypatch.setattr(llm, "generate", fake_generate(json.dumps(_CAPTURE_CONFIG), degraded=True))

    r = client.post(
        "/api/studio/use-cases/calorie/capture",
        files={"file": ("ui.png", _CAPTURE_PNG, "image/png")},
    )
    assert r.status_code == 200
    ly = r.json()
    # would have auto-seeded if not degraded — proves the guard is load-bearing
    assert ly["capture_meta"]["capture_quality"] == "high"

    mode, _ = semantic_cache.lookup("system", "calorie tracker")
    assert mode != "hit"  # degraded output must never enter the seed pool


def test_promote_refuses_degraded_capture_with_409(client, monkeypatch):
    """R-403 on the MANUAL promote path: a layout persisted from a degraded capture
    carries capture_meta.degraded=True and must be refused (409) by
    POST /api/studio/layouts/{id}/promote — the user asking doesn't cleanse it."""
    from src import db, semantic_cache

    monkeypatch.setenv("TRUS_LLM_PROVIDER", "stub")
    monkeypatch.delenv("TRUS_LLM_BASE_URL", raising=False)

    monkeypatch.setattr(llm, "vision_capture", lambda *a, **k: json.dumps(_CAPTURE_IR))
    monkeypatch.setattr(llm, "generate", fake_generate(json.dumps(_CAPTURE_CONFIG), degraded=True))

    ly = client.post(
        "/api/studio/use-cases/calorie/capture",
        files={"file": ("ui.png", _CAPTURE_PNG, "image/png")},
    ).json()
    assert ly["capture_meta"]["degraded"] is True  # the marker was persisted

    r = client.post(f"/api/studio/layouts/{ly['id']}/promote")
    assert r.status_code == 409
    assert "degraded" in r.json()["detail"]

    assert db.cache_stats()["entries"] == 0  # seed pool untouched
    mode, _ = semantic_cache.lookup("system", "calorie tracker")
    assert mode != "hit"


_PROMOTABLE_CONFIG = json.dumps(
    {"title": "T", "components": [{"id": "a", "type": "text_input", "label": "A"}]}
)


def test_promote_fails_closed_on_unparseable_capture_meta(client):
    """F4/R-403: capture_meta that can't be parsed (or isn't a dict) is UNKNOWN
    provenance — treat it as degraded and refuse (409), never promote."""
    from src import db

    bad = db.layout_add(
        "calorie", "Corrupt", None, _PROMOTABLE_CONFIG, capture_meta_json="not-json{{{"
    )
    r = client.post(f"/api/studio/layouts/{bad}/promote")
    assert r.status_code == 409
    assert "degraded" in r.json()["detail"]

    # A non-dict (but valid JSON) capture_meta is equally unsafe.
    non_dict = db.layout_add(
        "calorie", "NonDict", None, _PROMOTABLE_CONFIG, capture_meta_json="[1, 2, 3]"
    )
    r2 = client.post(f"/api/studio/layouts/{non_dict}/promote")
    assert r2.status_code == 409

    assert db.cache_stats()["entries"] == 0  # nothing seeded
