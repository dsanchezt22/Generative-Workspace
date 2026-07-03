import json
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from src.schema import ClarifyingQuestion, RefusalError
from src.services import orchestrator
from src.stub_templates import pick_system

from tests.conftest import gen_result


@contextmanager
def _fake_llm(text: str):
    """Exercise the orchestrator's real (non-stub) path with llm.generate mocked.
    Without forcing non-stub, generate_modules short-circuits to stub templates
    and never calls the mock."""
    result = gen_result(text)
    with (
        patch("src.services.orchestrator.llm.is_stub_mode", return_value=False),
        patch("src.services.orchestrator.llm.generate", return_value=result) as gen,
    ):
        yield gen


def test_pick_system_broad_returns_multiple():
    sys = pick_system("plan my japan trip")
    assert len(sys) >= 2
    titles = [m["title"] for m in sys]
    assert len(set(titles)) == len(titles)  # distinct tools


def test_pick_system_focused_returns_one():
    assert len(pick_system("a workout log")) == 1


def test_generate_modules_stub_decomposes(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "stub-test")
    mods = orchestrator.generate_modules("organize my wedding")
    assert len(mods) >= 2
    assert all(m.components for m in mods)


def test_generate_modules_parses_array():
    arr = json.dumps(
        [
            {
                "title": "Itinerary",
                "icon": "🗓️",
                "accent": "sky",
                "components": [{"id": "days", "type": "calendar", "label": "Days"}],
            },
            {
                "title": "Budget",
                "icon": "💰",
                "accent": "amber",
                "components": [{"id": "total", "type": "kpi", "label": "Total", "unit": "$"}],
            },
        ]
    )
    with _fake_llm(arr):
        mods = orchestrator.generate_modules("plan my trip")
    assert [m.title for m in mods] == ["Itinerary", "Budget"]
    assert mods[0].components[0].type == "calendar"
    assert mods[1].components[0].type == "kpi"


def test_generate_modules_wraps_single_object():
    obj = json.dumps(
        {
            "title": "Workout Log",
            "components": [{"id": "e", "type": "text_input", "label": "Exercise"}],
        }
    )
    with _fake_llm(obj):
        mods = orchestrator.generate_modules("track workouts")
    assert len(mods) == 1
    assert mods[0].title == "Workout Log"


def test_generate_modules_refusal():
    with _fake_llm('{"refusal": "Out of scope."}'), pytest.raises(RefusalError):
        orchestrator.generate_modules("do something illicit")


def test_generate_modules_question():
    with _fake_llm('{"question": "Which city?"}'), pytest.raises(ClarifyingQuestion):
        orchestrator.generate_modules("plan a trip")


def test_new_component_types_validate():
    from src.schema import ModuleConfig

    cfg = ModuleConfig.model_validate(
        {
            "title": "Everything",
            "components": [
                {"id": "r", "type": "rating", "label": "Rating", "max": 5},
                {"id": "tg", "type": "tags", "label": "Tags"},
                {"id": "k", "type": "kpi", "label": "Total", "unit": "$"},
                {"id": "d", "type": "date", "label": "When"},
                {"id": "tb", "type": "table", "label": "Grid", "columns": ["A", "B"]},
                {"id": "c", "type": "calendar", "label": "Days"},
                {"id": "ch", "type": "chart", "label": "Trend", "chart_type": "line"},
            ],
        }
    )
    assert [c.type for c in cfg.components] == [
        "rating",
        "tags",
        "kpi",
        "date",
        "table",
        "calendar",
        "chart",
    ]
