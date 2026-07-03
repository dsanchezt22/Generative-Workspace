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


# --- R-103/R-301: proposal plan alongside the decomposed modules ---


def test_parse_modules_tolerates_modules_object_shape_no_plan():
    """{"modules": [...]} with no "plan" key — already-tolerated shape, verified."""
    obj = json.dumps(
        {
            "modules": [
                {"title": "A", "components": [{"id": "x", "type": "text_input", "label": "X"}]}
            ]
        }
    )
    with _fake_llm(obj):
        mods = orchestrator.generate_modules("plan a trip")
    assert [m.title for m in mods] == ["A"]
    assert orchestrator.last_plan.get() is None


def test_generate_modules_extracts_plan_alongside_modules():
    """{"plan": str, "modules": [...]} — the new shape — surfaces the plan via
    orchestrator.last_plan without changing generate_modules' return type."""
    obj = json.dumps(
        {
            "plan": "I'll build a focused itinerary tracker for your trip.",
            "modules": [
                {"title": "A", "components": [{"id": "x", "type": "text_input", "label": "X"}]}
            ],
        }
    )
    with _fake_llm(obj):
        mods = orchestrator.generate_modules("plan a trip")
    assert [m.title for m in mods] == ["A"]
    assert orchestrator.last_plan.get() == "I'll build a focused itinerary tracker for your trip."


def test_generate_modules_stub_mode_has_no_plan(monkeypatch):
    """Stub mode never fabricates a rationale it didn't actually generate."""
    monkeypatch.setenv("GEMINI_API_KEY", "stub-test")
    orchestrator.generate_modules("organize my wedding")
    assert orchestrator.last_plan.get() is None


def test_generate_modules_bare_array_shape_has_no_plan():
    """The old bare-array shape still works and never claims a plan."""
    with _fake_llm(
        json.dumps(
            [{"title": "A", "components": [{"id": "x", "type": "text_input", "label": "X"}]}]
        )
    ):
        orchestrator.generate_modules("plan a trip")
    assert orchestrator.last_plan.get() is None


# --- R-102: exchange_context reaches the model, never the cache key ---


def test_exchange_context_reaches_the_model_message():
    arr = json.dumps(
        [{"title": "A", "components": [{"id": "x", "type": "text_input", "label": "X"}]}]
    )
    with _fake_llm(arr) as mock_gen:
        orchestrator.generate_modules(
            "plan my unique trip prompt", exchange_context="Q: Which city?\nA: Tokyo"
        )
    prompt_used = mock_gen.call_args[0][0]
    assert "Tokyo" in prompt_used


# --- R-302: recent conversation feeds generation context ---


def test_recent_messages_reach_the_model_message():
    arr = json.dumps(
        [{"title": "A", "components": [{"id": "x", "type": "text_input", "label": "X"}]}]
    )
    history = [
        {"role": "user", "text": "a distinctive prior message about narwhals"},
        {"role": "assistant", "text": "Created Narwhal Tracker"},
    ]
    with _fake_llm(arr) as mock_gen:
        orchestrator.generate_modules("plan my context-aware prompt", recent_messages=history)
    prompt_used = mock_gen.call_args[0][0]
    assert "narwhals" in prompt_used
    assert "Recent conversation:" in prompt_used


def test_no_recent_messages_omits_the_conversation_block():
    arr = json.dumps(
        [{"title": "A", "components": [{"id": "x", "type": "text_input", "label": "X"}]}]
    )
    with _fake_llm(arr) as mock_gen:
        orchestrator.generate_modules("plan a trip with no history")
    prompt_used = mock_gen.call_args[0][0]
    assert "Recent conversation:" not in prompt_used


def test_recent_conversation_bounded_to_about_1200_chars():
    arr = json.dumps(
        [{"title": "A", "components": [{"id": "x", "type": "text_input", "label": "X"}]}]
    )
    history = [{"role": "user", "text": f"message number {i} " * 5} for i in range(30)]
    with _fake_llm(arr) as mock_gen:
        orchestrator.generate_modules("plan my bounded context prompt", recent_messages=history)
    prompt_used = mock_gen.call_args[0][0]
    start = prompt_used.index("Recent conversation:")
    end = prompt_used.index("\n\nReturn the adapted", start)
    block = prompt_used[start:end]
    assert len(block) <= 1200 + 100  # header + slack around the ~1200-char budget


def test_recent_conversation_single_oversized_message_keeps_recent_tail():
    """When even the single most recent turn alone exceeds the ~1200-char
    budget, its TAIL (most recent characters, containing the sentinel) is kept
    rather than dropping the turn entirely."""
    arr = json.dumps(
        [{"title": "A", "components": [{"id": "x", "type": "text_input", "label": "X"}]}]
    )
    history = [{"role": "user", "text": ("x" * 2000) + "TAIL-SENTINEL"}]
    with _fake_llm(arr) as mock_gen:
        orchestrator.generate_modules("plan my oversized turn prompt", recent_messages=history)
    prompt_used = mock_gen.call_args[0][0]
    assert "Recent conversation:" in prompt_used
    assert "TAIL-SENTINEL" in prompt_used


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
