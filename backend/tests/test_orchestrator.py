import json
from unittest.mock import patch

import pytest

from src.schema import RefusalError
from src.services import orchestrator


VALID = json.dumps({
    "title": "Workout Log",
    "components": [
        {"id": "exercise", "type": "text_input", "label": "Exercise"},
        {"id": "reps", "type": "number_input", "label": "Reps", "min": 0, "step": 1},
    ],
    "state": {},
})


def _fake_llm(text: str):
    return patch("src.services.orchestrator.llm.generate", return_value=text)


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
    with _fake_llm('{"refusal": "Out of scope for the component library."}'):
        with pytest.raises(RefusalError, match="Out of scope"):
            orchestrator.generate_module("build a 3D movie")


def test_generate_module_raises_refusal_on_non_json():
    with _fake_llm("sorry I can't do that"):
        with pytest.raises(RefusalError):
            orchestrator.generate_module("anything")


def test_generate_module_raises_refusal_on_unknown_component():
    bogus = json.dumps({
        "title": "Bad",
        "components": [{"id": "x", "type": "magic_box", "label": "Magic"}],
    })
    with _fake_llm(bogus):
        with pytest.raises(RefusalError):
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
    from src.schema import ModuleConfig, TextInput, NumberInput
    return ModuleConfig(
        title="Workout Log",
        components=[
            TextInput(id="exercise", label="Exercise"),
            NumberInput(id="reps", label="Reps"),
        ],
        state={"reps": 10},
    )


REFINED = json.dumps({
    "title": "Workout Log",
    "components": [
        {"id": "exercise", "type": "text_input", "label": "Exercise"},
        {"id": "reps", "type": "number_input", "label": "Reps", "min": 0, "step": 1},
        {"id": "rest_day", "type": "checkbox", "label": "Rest day"},
    ],
    "state": {"reps": 10},
})


def test_refine_module_returns_updated_config():
    with _fake_llm(REFINED):
        config = orchestrator.refine_module(_make_config(), "add a rest day checkbox")
    assert any(c.type == "checkbox" for c in config.components)
    assert config.state.get("reps") == 10


def test_refine_module_raises_refusal_on_explicit_refusal():
    with _fake_llm('{"refusal": "Cannot embed a video."}'):
        with pytest.raises(RefusalError, match="Cannot embed"):
            orchestrator.refine_module(_make_config(), "embed a YouTube video")


def test_refine_module_raises_refusal_on_non_json():
    with _fake_llm("I cannot do that"):
        with pytest.raises(RefusalError):
            orchestrator.refine_module(_make_config(), "anything")


def test_refine_module_stub_returns_config_unchanged(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "stub-test")
    original = _make_config()
    result = orchestrator.refine_module(original, "add a rest day checkbox")
    assert result.title == original.title
    assert len(result.components) == len(original.components)
