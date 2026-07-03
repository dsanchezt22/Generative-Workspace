import json
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from src.schema import LLMError, RefusalError
from src.services import orchestrator

from tests.conftest import gen_result

VALID = json.dumps(
    {
        "title": "Workout Log",
        "components": [
            {"id": "exercise", "type": "text_input", "label": "Exercise"},
            {"id": "reps", "type": "number_input", "label": "Reps", "min": 0, "step": 1},
        ],
        "state": {},
    }
)


@contextmanager
def _fake_llm(text: str):
    """Exercise the orchestrator's real (non-stub) path with llm.generate mocked.
    Without forcing non-stub, generate_modules/refine_module short-circuit to
    stub templates and never call the mock."""
    result = gen_result(text)
    with (
        patch("src.services.orchestrator.llm.is_stub_mode", return_value=False),
        patch("src.services.orchestrator.llm.generate", return_value=result) as gen,
    ):
        yield gen


def test_generate_module_returns_valid_config():
    with _fake_llm(VALID):
        config = orchestrator.generate_module("track my workouts")
    assert config.title == "Workout Log"
    assert config.components[1].type == "number_input"


def test_generate_module_strips_code_fence():
    fenced = f"```json\n{VALID}\n```"
    with _fake_llm(fenced):
        config = orchestrator.generate_module("track my workouts")
    assert config.title == "Workout Log"


def test_generate_module_raises_refusal_on_explicit_refusal():
    with (
        _fake_llm('{"refusal": "Out of scope for the component library."}'),
        pytest.raises(RefusalError, match="Out of scope"),
    ):
        orchestrator.generate_module("build a 3D movie")


def test_generate_module_raises_refusal_on_non_json():
    with _fake_llm("sorry I can't do that"), pytest.raises(RefusalError):
        orchestrator.generate_module("anything")


def test_generate_module_raises_refusal_on_unknown_component():
    bogus = json.dumps(
        {
            "title": "Bad",
            "components": [{"id": "x", "type": "magic_box", "label": "Magic"}],
        }
    )
    with _fake_llm(bogus), pytest.raises(RefusalError):
        orchestrator.generate_module("anything")


def test_generate_module_through_real_stub(monkeypatch):
    # No mock: exercises the seeded-prompt path against the offline stub, so the
    # stub still routes on the original intent even though the prompt is seeded.
    monkeypatch.setenv("GEMINI_API_KEY", "stub-test")
    config = orchestrator.generate_module("trip budget for japan")
    assert "budget" in config.title.lower()
    assert config.components  # valid, non-empty module


# --- refine_module tests ---


def _make_config() -> "orchestrator.ModuleConfig":
    from src.schema import ModuleConfig, NumberInput, TextInput

    return ModuleConfig(
        title="Workout Log",
        components=[
            TextInput(id="exercise", label="Exercise"),
            NumberInput(id="reps", label="Reps"),
        ],
        state={"reps": 10},
    )


REFINED = json.dumps(
    {
        "title": "Workout Log",
        "components": [
            {"id": "exercise", "type": "text_input", "label": "Exercise"},
            {"id": "reps", "type": "number_input", "label": "Reps", "min": 0, "step": 1},
            {"id": "rest_day", "type": "checkbox", "label": "Rest day"},
        ],
        "state": {"reps": 10},
    }
)


def test_refine_module_returns_updated_config():
    with _fake_llm(REFINED):
        config = orchestrator.refine_module(_make_config(), "add a rest day checkbox")
    assert any(c.type == "checkbox" for c in config.components)
    assert config.state.get("reps") == 10


def test_refine_module_raises_refusal_on_explicit_refusal():
    with (
        _fake_llm('{"refusal": "Cannot embed a video."}'),
        pytest.raises(RefusalError, match="Cannot embed"),
    ):
        orchestrator.refine_module(_make_config(), "embed a YouTube video")


def test_refine_module_raises_refusal_on_non_json():
    with _fake_llm("I cannot do that"), pytest.raises(RefusalError):
        orchestrator.refine_module(_make_config(), "anything")


def test_refine_module_stub_raises_llm_error(monkeypatch):
    """R-1104: stub mode must not silently pretend a refine succeeded."""
    monkeypatch.setenv("GEMINI_API_KEY", "stub-test")
    with pytest.raises(LLMError):
        orchestrator.refine_module(_make_config(), "add a rest day checkbox")


# --- context injection tests ---


def test_generate_module_includes_existing_context():
    from src.schema import ModuleConfig, TextInput

    existing = [ModuleConfig(title="Meal Log", components=[TextInput(id="meal", label="Meal")])]
    with _fake_llm(VALID) as mock_gen:
        orchestrator.generate_module("add a dashboard", existing_modules=existing)
    prompt_used = mock_gen.call_args[0][0]
    assert "Meal Log" in prompt_used
    assert "meal" in prompt_used


def test_refine_module_includes_existing_context():
    from src.schema import ModuleConfig, TextInput

    existing = [ModuleConfig(title="Meal Log", components=[TextInput(id="meal", label="Meal")])]
    with _fake_llm(VALID) as mock_gen:
        orchestrator.refine_module(
            _make_config(), "add cross-module binding", existing_modules=existing
        )
    prompt_used = mock_gen.call_args[0][0]
    assert "Meal Log" in prompt_used


# --- synthesize_workspace tests ---

DASHBOARD_RAW = json.dumps(
    {
        "title": "Dashboard",
        "components": [
            {
                "id": "total_reps",
                "type": "metric",
                "label": "Total Reps",
                "formula": "sum",
                "source_component_id": "reps",
            },
        ],
    }
)


def test_synthesize_workspace_returns_dashboard():
    with _fake_llm(DASHBOARD_RAW):
        config = orchestrator.synthesize_workspace([_make_config()])
    assert config.title == "Dashboard"
    assert config.components[0].type == "metric"


def test_synthesize_workspace_stub_returns_stub_module(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "stub-test")
    config = orchestrator.synthesize_workspace([_make_config()])
    assert config.title == "Dashboard"
    assert any(c.type == "metric" for c in config.components)


# --- metric schema validation ---


def test_metric_component_roundtrips():
    from src.schema import Metric, ModuleConfig

    config = ModuleConfig(
        title="Stats",
        components=[Metric(id="total", label="Total", formula="sum", source_component_id="reps")],
    )
    reloaded = ModuleConfig.model_validate_json(config.model_dump_json())
    assert reloaded.components[0].type == "metric"
    assert reloaded.components[0].formula == "sum"  # type: ignore[union-attr]


# --- clarifying question tests ---


def test_generate_module_raises_clarifying_question():
    from src.schema import ClarifyingQuestion

    with (
        _fake_llm('{"question": "How many meals per day do you track?"}'),
        pytest.raises(ClarifyingQuestion) as exc,
    ):
        orchestrator.generate_module("track my food")
    assert "meals" in exc.value.question.lower()


def test_generate_module_question_only_when_single_key():
    # A dict with "question" plus other keys is NOT a clarifying question —
    # it falls through to ModuleConfig validation and is accepted as a valid module.
    with _fake_llm('{"question": "How many?", "title": "Tracker", "components": []}'):
        config = orchestrator.generate_module("track something")
    assert config.title == "Tracker"
