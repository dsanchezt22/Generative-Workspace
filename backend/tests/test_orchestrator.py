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
