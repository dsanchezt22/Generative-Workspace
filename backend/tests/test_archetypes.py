import json
from unittest.mock import patch

import pytest
from src.archetypes import (
    REGISTRY,
    archetype_menu,
    decode_intent,
    select_archetypes,
    theme_for,
)
from src.schema import LLMError, ModuleConfig
from src.stub_templates import _finalize


# --- registry ---------------------------------------------------------------
def test_every_archetype_builder_validates():
    assert len(REGISTRY) >= 18
    keys = [a.key for a in REGISTRY]
    assert len(keys) == len(set(keys))  # unique keys
    for a in REGISTRY:
        ModuleConfig.model_validate(_finalize(a.builder()))


def test_archetype_menu_lists_keys_and_when():
    menu = archetype_menu()
    for key in ("workout_calendar", "kanban_pipeline", "habit_heatmap"):
        assert key in menu


def test_theme_for_is_domain_aware():
    assert theme_for("my gym workout plan")["accent"] == "emerald"
    assert theme_for("monthly budget and expenses")["accent"] in ("amber", "gold")
    assert theme_for("plan a trip to japan")["accent"] == "sky"


# --- selector ---------------------------------------------------------------
@pytest.mark.parametrize(
    "prompt,expected_key,expected_type",
    [
        ("a workout log", "workout_calendar", "calendar"),
        ("organize a sprint backlog", "kanban_pipeline", "kanban"),
        ("daily habit streak", "habit_heatmap", "heatmap"),
        ("wedding guest list", "table_ledger", "table"),
    ],
)
def test_select_routes_intent_to_format(prompt, expected_key, expected_type):
    chosen = select_archetypes(prompt)
    assert chosen, f"no archetype matched {prompt!r}"
    assert chosen[0].key == expected_key
    types = {c["type"] for c in chosen[0].builder()["components"]}
    assert expected_type in types


def test_select_returns_empty_for_no_match():
    assert select_archetypes("xyzzy quux frobnicate") == []


# --- decode_intent ----------------------------------------------------------
def _decode_with(text):
    return patch("src.archetypes.llm.generate", return_value=text)


def test_decode_intent_parses_known_keys():
    raw = json.dumps(
        {
            "summary": "log workouts",
            "archetypes": ["workout_calendar"],
            "theme": {"accent": "emerald", "icon": "activity"},
        }
    )
    with _decode_with(raw):
        out = decode_intent("track my gym sessions")
    assert out["archetypes"] == ["workout_calendar"]
    assert out["theme"]["accent"] == "emerald"


def test_decode_intent_drops_unknown_keys():
    raw = json.dumps({"summary": "x", "archetypes": ["not_a_real_key"], "theme": {}})
    with _decode_with(raw):
        assert decode_intent("anything") is None


def test_decode_intent_none_on_non_json():
    with _decode_with("sorry, here is some prose"):
        assert decode_intent("anything") is None


def test_decode_intent_none_on_llm_error():
    with patch("src.archetypes.llm.generate", side_effect=LLMError("boom")):
        assert decode_intent("anything") is None


def test_decode_intent_drops_off_palette_theme():
    raw = json.dumps(
        {"archetypes": ["workout_calendar"], "theme": {"accent": "chartreuse", "icon": "nope"}}
    )
    with _decode_with(raw):
        out = decode_intent("track workouts")
    assert out["theme"] == {}  # invalid accent + icon both dropped


def test_decode_intent_keeps_only_valid_theme_fields():
    raw = json.dumps(
        {"archetypes": ["workout_calendar"], "theme": {"accent": "emerald", "icon": "nope"}}
    )
    with _decode_with(raw):
        out = decode_intent("track workouts")
    assert out["theme"] == {"accent": "emerald"}  # valid accent kept, bad icon dropped
