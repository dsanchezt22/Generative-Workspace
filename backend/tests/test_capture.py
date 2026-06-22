"""Tests for the screenshot capture→transform engine (capture/*).

All model calls are monkeypatched, so these run in stub mode with no network:
- `llm.vision_capture` returns a canned IR (the CAPTURE stage output),
- `llm.generate` returns a canned ModuleConfig (the TRANSFORM stage output).
"""

import json

import pytest
from fastapi.testclient import TestClient
from src import llm
from src.main import app
from src.services.capture.ir import parse_ir
from src.services.capture.transform import map_ui_type, transform_ir

_PNG = b"\x89PNG\r\n\x1a\n"  # bytes are irrelevant — vision is mocked

_IR = {
    "schema": "trus-capture-ir/1",
    "app_kind": "nutrition tracker",
    "summary": "A nutrition dashboard with a food diary, calorie ring and weight trend.",
    "tokens": {
        "color": {"accent": "emerald"},
        "space": {"density": "comfortable"},
        "radius": {"scale": "rounded"},
        "type": {"scale": "regular"},
    },
    "nodes": [
        {
            "id": "n1",
            "ui_type": "food_table",
            "role": "table",
            "label": "Food diary",
            "columns": ["Food", "Calories"],
        },
        {"id": "n2", "ui_type": "macro_rings", "role": "region", "label": "Calories"},
        {"id": "n3", "ui_type": "weight_chart", "role": "chart", "label": "Weight trend"},
        {"id": "bad", "label": 123},  # malformed node — must be dropped, not fatal
    ],
    "capabilities": ["log a food entry", "see calories", "view weight trend"],
}

_FULL_CONFIG = {
    "title": "Nutrition Tracker",
    "columns": 2,
    "density": "comfortable",
    "components": [
        {"id": "food", "type": "table", "label": "Food diary", "columns": ["Food", "Calories"]},
        {"id": "cals", "type": "ring", "label": "Calories", "max": 2000},
        {"id": "weight", "type": "chart", "label": "Weight trend", "chart_type": "line"},
    ],
}

# Same, but drops the weight-trend feature → a capability is lost.
_DROPPED_CONFIG = {
    "title": "Nutrition Tracker",
    "components": [
        {"id": "food", "type": "table", "label": "Food diary", "columns": ["Food", "Calories"]},
        {"id": "cals", "type": "ring", "label": "Calories", "max": 2000},
    ],
}


# ---------------------------------------------------------------- unit ----


def test_ir_parses_lenient_and_digests():
    ir = parse_ir(json.dumps(_IR))
    assert ir.app_kind == "nutrition tracker"
    assert ir.capabilities == ["log a food entry", "see calories", "view weight trend"]
    assert len(ir.nodes) == 3  # the malformed node was dropped, the rest kept
    assert ir.accent_hint() == "emerald"
    assert ir.density_hint() == "comfortable"
    digest = ir.to_digest()
    assert digest["node_count"] == 3 and "food_table" in digest["node_types"]
    assert "nutrition tracker" in ir.to_structured_text().lower()


def test_ir_codefence_and_bare_array():
    ir = parse_ir("```json\n" + json.dumps({"nodes": _IR["nodes"], "capabilities": []}) + "\n```")
    assert len(ir.nodes) == 3


def test_map_ui_type():
    assert map_ui_type("macro_rings", "region") == "ring"
    assert map_ui_type("food_table", "table") == "table"
    assert map_ui_type("weight_chart", "chart") == "chart"
    assert map_ui_type("kanban_board", "") == "kanban"
    assert map_ui_type("streak_grid", "") == "heatmap"
    assert map_ui_type("qwerty_zzz", "") == "text_input"  # safe fallback for unmatched


def test_transform_preserves_all_capabilities(monkeypatch):
    monkeypatch.setattr(llm, "generate", lambda *a, **k: json.dumps(_FULL_CONFIG))
    ir = parse_ir(json.dumps(_IR))
    config, report = transform_ir(ir, match_colors=True)
    assert report["coverage"] == 1.0 and report["uncovered"] == []
    assert set(report["component_types"]) == {"table", "ring", "chart"}
    # match_colors honored: design layer carried from the IR tokens
    assert config.theme_opt_in is True
    assert config.accent == "emerald"
    assert config.radius == "rounded" and config.type_scale == "regular"


def test_transform_flags_dropped_feature(monkeypatch):
    monkeypatch.setattr(llm, "generate", lambda *a, **k: json.dumps(_DROPPED_CONFIG))
    ir = parse_ir(json.dumps(_IR))
    _, report = transform_ir(ir, match_colors=False)
    assert report["coverage"] < 1.0
    assert "view weight trend" in report["uncovered"]


def test_transform_no_match_colors_keeps_brand(monkeypatch):
    monkeypatch.setattr(llm, "generate", lambda *a, **k: json.dumps(_FULL_CONFIG))
    ir = parse_ir(json.dumps(_IR))
    config, _ = transform_ir(ir, match_colors=False)
    assert config.theme_opt_in is False


# ---------------------------------------------------------------- route ---


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("TRUS_LLM_PROVIDER", "stub")
    monkeypatch.delenv("TRUS_LLM_BASE_URL", raising=False)
    with TestClient(app) as c:
        yield c


def test_capture_route_end_to_end_and_autoseed(client, monkeypatch):
    from src import semantic_cache

    monkeypatch.setattr(llm, "vision_capture", lambda *a, **k: json.dumps(_IR))
    monkeypatch.setattr(llm, "generate", lambda *a, **k: json.dumps(_FULL_CONFIG))

    r = client.post(
        "/api/studio/use-cases/calorie/capture",
        data={"match_colors": "true"},
        files={"file": ("ui.png", _PNG, "image/png")},
    )
    assert r.status_code == 200
    ly = r.json()
    assert ly["use_case"] == "calorie" and ly["id"]
    assert ly["confidence"] >= 0.99
    cm = ly["capture_meta"]
    assert cm["capture_quality"] == "high" and cm["uncovered"] == []
    assert set(cm["component_types"]) == {"table", "ring", "chart"}
    assert ly["config"]["theme_opt_in"] is True and ly["config"]["accent"] == "emerald"

    # it landed in the library …
    listed = client.get("/api/studio/layouts?use_case=calorie").json()
    assert any(x["id"] == ly["id"] for x in listed)
    # … and a high-confidence capture auto-seeded the generation pool
    mode, cached = semantic_cache.lookup("system", "calorie tracker")
    assert mode == "hit" and cached and cached[0]["title"]


def test_capture_low_confidence_not_seeded(client, monkeypatch):
    from src import semantic_cache

    monkeypatch.setattr(llm, "vision_capture", lambda *a, **k: json.dumps(_IR))
    monkeypatch.setattr(llm, "generate", lambda *a, **k: json.dumps(_DROPPED_CONFIG))

    r = client.post(
        "/api/studio/use-cases/calorie/capture", files={"file": ("ui.png", _PNG, "image/png")}
    )
    assert r.status_code == 200
    ly = r.json()
    assert ly["capture_meta"]["capture_quality"] != "high"
    assert "view weight trend" in ly["capture_meta"]["uncovered"]
    # dropped-feature capture must NOT auto-seed generation
    mode, _ = semantic_cache.lookup("system", "calorie tracker")
    assert mode != "hit"


def test_capture_unknown_use_case_404(client):
    r = client.post(
        "/api/studio/use-cases/not-real/capture", files={"file": ("ui.png", _PNG, "image/png")}
    )
    assert r.status_code == 404
