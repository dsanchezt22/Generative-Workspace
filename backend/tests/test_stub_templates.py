import pytest

from src.schema import ModuleConfig
from src.stub_templates import pick_template


@pytest.mark.parametrize(
    "prompt,expected_keyword",
    [
        ("track my workouts at the gym", "Workout"),  # plural must still route
        ("workout", "Workout"),
        ("a calorie tracker for my diet", "Calorie"),
        ("budget for a trip to Japan", "Budget"),
        ("a to-do list for chores", "To-Do"),
        ("my reading list of books", "Reading"),
        ("daily habit streak", "Habit"),
        ("a mood journal", "Mood"),
    ],
)
def test_pick_template_routes_by_intent(prompt, expected_keyword):
    config = pick_template(prompt)
    assert expected_keyword.lower() in config["title"].lower()
    # Every template must validate as a real ModuleConfig.
    ModuleConfig.model_validate(config)


def test_pick_template_falls_back_to_generic():
    config = pick_template("xyzzy quux frobnicate")
    parsed = ModuleConfig.model_validate(config)
    assert parsed.components  # generic still produces a usable module


def test_generic_title_strips_filler_and_does_not_double_tracker():
    # Use an unrouted noun so we exercise the generic title path.
    config = pick_template("I want to create a tracker for my gadgets")
    title = config["title"]
    assert "tracker" not in title.lower()  # filler stripped, no "Tracker Tracker"
    assert "Gadgets" in title


def test_every_template_validates():
    prompts = [
        "workout", "calorie", "budget", "todo", "reading", "habit", "mood",
        "random thing",
    ]
    for p in prompts:
        ModuleConfig.model_validate(pick_template(p))


def test_all_v2_templates_validate():
    from src.stub_templates import _ROUTES_V2, _finalize
    builders = {b for _, b in _ROUTES_V2}
    assert len(builders) >= 50  # at least 50 new templates
    for b in builders:
        ModuleConfig.model_validate(_finalize(b()))


def test_v2_templates_use_varied_formats():
    """The new templates must use more than plain stacked fields."""
    from src.stub_templates import _ROUTES_V2, _finalize
    used = set()
    for _, b in _ROUTES_V2:
        for c in _finalize(b())["components"]:
            used.add(c["type"])
    # Distinct, non-rectangular formats are represented.
    for fmt in ["kanban", "heatmap", "gauge", "checklist", "gallery", "note", "section", "timeline"]:
        assert fmt in used, f"expected {fmt} in the new templates"


def test_v2_routing_spot_check():
    assert pick_template("a kanban task board")["title"] == "Task Board"
    assert "Dashboard" in pick_template("a finance dashboard")["title"]
    assert pick_template("weekly retro")["title"] == "Weekly Retro"
    # 'category' must not mis-route to the 'cat' (pet) template.
    assert "Pet" not in pick_template("expense categories")["title"]
