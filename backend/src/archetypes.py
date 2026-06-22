"""Named UI archetypes: the formats generation can choose from.

An archetype pairs an intent signature with a seed builder and a default theme.
`select_archetypes` scores these against a prompt (the deterministic "search for the
best model that fits the intent"); `decode_intent` is the live LLM equivalent. The
orchestrator uses the registry for the live archetype MENU, theming, and the
deterministic fallback. Builders are reused from `stub_templates` so there is one
set of seed builders.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from src import llm
from src import stub_templates as st
from src.schema import LLMError


@dataclass(frozen=True)
class Archetype:
    key: str
    label: str
    signals: tuple[str, ...]
    builder: Callable[[], dict[str, Any]]
    accent: str
    icon: str
    when: str  # one-line "use when…" for the LLM menu


REGISTRY: list[Archetype] = [
    Archetype(
        "workout_calendar",
        "Workout (calendar)",
        ("workout", "gym", "exercise", "lift", "training", "fitness"),
        st._workout,
        "emerald",
        "activity",
        "logging an activity per day → a calendar of marked days + supporting fields",
    ),
    Archetype(
        "calorie_log",
        "Calorie log",
        ("calorie", "nutrition", "diet", "macro", "meal log", "food log"),
        st._calorie,
        "coral",
        "leaf",
        "daily totals against a goal",
    ),
    Archetype(
        "kanban_pipeline",
        "Pipeline (kanban)",
        ("pipeline", "kanban", "task board", "backlog", "workflow", "sprint", "leads", "deals"),
        st._task_board,
        "violet",
        "grid",
        "stages/columns of cards → a kanban board",
    ),
    Archetype(
        "habit_heatmap",
        "Habit (heatmap)",
        ("habit", "streak", "routine", "daily check"),
        st._habit_grid,
        "emerald",
        "repeat",
        "marking a thing done over many days → a heatmap",
    ),
    Archetype(
        "calendar_schedule",
        "Schedule (calendar)",
        ("calendar", "schedule", "timetable", "itinerary"),
        st._calendar_tool,
        "sky",
        "calendar",
        "dates/days → a month calendar",
    ),
    Archetype(
        "table_ledger",
        "Ledger (table)",
        (
            "guest list",
            "attendee",
            "roster",
            "inventory",
            "stock",
            "contacts",
            "address book",
            "transactions",
        ),
        st._contacts,
        "teal",
        "list",
        "row/column data → a table",
    ),
    Archetype(
        "budget_chart",
        "Budget (chart)",
        ("budget", "expense", "spend", "money", "cost", "finance"),
        st._budget,
        "amber",
        "dollar",
        "amounts over time/categories → a chart + totals",
    ),
    Archetype(
        "dashboard",
        "Dashboard",
        ("dashboard", "overview", "daily overview", "life overview"),
        st._life_dashboard,
        "sky",
        "chart",
        "several metrics at a glance → columns:2 with kpis/chart/gauge",
    ),
    Archetype(
        "journal_note",
        "Journal",
        ("journal", "diary", "gratitude", "reflection"),
        st._daily_journal,
        "rose",
        "book",
        "free writing over time → a note + heatmap",
    ),
    Archetype(
        "reading_list",
        "Reading list",
        ("read", "book", "reading", "watchlist", "movie", "show"),
        st._reading,
        "violet",
        "book",
        "a collection of items to get through",
    ),
    Archetype(
        "moodboard_gallery",
        "Moodboard",
        ("moodboard", "mood board", "inspiration", "wishlist"),
        st._moodboard,
        "violet",
        "camera",
        "visual collection → a gallery",
    ),
    Archetype(
        "retro_review",
        "Retro / review",
        ("retro", "retrospective", "weekly review"),
        st._weekly_retro,
        "teal",
        "repeat",
        "structured periodic review → sections + lists",
    ),
    Archetype(
        "schedule_class",
        "Class schedule",
        ("class", "course", "lecture", "semester", "timetable"),
        st._class_schedule,
        "sky",
        "cap",
        "recurring sessions across the week → a calendar/table",
    ),
    Archetype(
        "sleep_log",
        "Sleep log",
        ("sleep", "bedtime", "rest"),
        st._sleep,
        "violet",
        "moon",
        "a nightly metric trend → a chart/sparkline",
    ),
    Archetype(
        "water_gauge",
        "Hydration (gauge)",
        ("water", "hydration", "drink"),
        st._water,
        "sky",
        "droplet",
        "a single level filling toward a goal → a gauge/ring",
    ),
    Archetype(
        "todo_checklist",
        "To-do / checklist",
        ("todo", "to-do", "task", "checklist", "chore", "packing"),
        st._todo,
        "amber",
        "check",
        "a list of things to complete → a checklist",
    ),
    Archetype(
        "goals_tracker",
        "Goals",
        ("goal", "objective", "okr", "milestone"),
        st._goals,
        "gold",
        "target",
        "targets with progress → progress bars/kpis",
    ),
    Archetype(
        "savings_progress",
        "Savings goal",
        ("saving", "save up", "savings goal", "fund"),
        st._savings,
        "gold",
        "dollar",
        "progress toward a money target → a progress bar/ring",
    ),
    Archetype(
        "recipe_card",
        "Recipe",
        ("recipe", "cook", "meal plan", "ingredient"),
        st._recipe,
        "coral",
        "leaf",
        "ingredients + steps → list + note",
    ),
    Archetype(
        "weight_trend",
        "Weight trend",
        ("weight", "weigh", "bodyweight"),
        st._weight,
        "emerald",
        "activity",
        "a single number tracked over time → a chart",
    ),
]


def archetype_menu() -> str:
    lines = [f"- {a.key} ({a.label}): {a.when}" for a in REGISTRY]
    return "ARCHETYPE MENU (pick the key(s) whose format best models the intent):\n" + "\n".join(
        lines
    )


# --- domain theming ---------------------------------------------------------
_DOMAIN_THEME: list[tuple[tuple[str, ...], str, str]] = [
    (("workout", "gym", "fitness", "exercise", "run", "training"), "emerald", "activity"),
    (
        ("budget", "expense", "money", "finance", "spend", "invoice", "savings", "debt"),
        "amber",
        "dollar",
    ),
    (("trip", "travel", "vacation", "flight", "japan", "itinerary"), "sky", "plane"),
    (("wellness", "mood", "journal", "gratitude", "meditation", "sleep"), "rose", "heart"),
    (("creative", "moodboard", "design", "art", "inspiration", "wishlist"), "violet", "sparkles"),
    (("food", "recipe", "meal", "calorie", "diet", "nutrition"), "coral", "leaf"),
]


def theme_for(prompt: str) -> dict[str, str]:
    low = prompt.lower()
    for keys, accent, icon in _DOMAIN_THEME:
        if any(re.search(rf"\b{re.escape(k)}", low) for k in keys):
            return {"accent": accent, "icon": icon}
    return {"accent": "teal", "icon": "sparkles"}


# --- deterministic selection ------------------------------------------------
def _signal_score(archetype: Archetype, text: str) -> int:
    score = 0
    for kw in archetype.signals:
        pattern = rf"\b{re.escape(kw)}s?\b" if len(kw) <= 3 else rf"\b{re.escape(kw)}"
        if re.search(pattern, text):
            # Longer / multi-word signals are stronger evidence of intent.
            score += 2 if " " in kw or len(kw) >= 6 else 1
    return score


def select_archetypes(prompt: str, limit: int = 3) -> list[Archetype]:
    low = prompt.lower()
    scored = [(a, _signal_score(a, low)) for a in REGISTRY]
    hits = sorted([(a, s) for a, s in scored if s > 0], key=lambda t: -t[1])
    return [a for a, _ in hits[:limit]]


# --- live LLM intent decode -------------------------------------------------
DECODE_SYSTEM_PROMPT = (
    "You are the Trus intent decoder. Read the user's request and choose which UI "
    "archetype(s) best model it, picking ONLY from the menu keys provided.\n\n"
    'Output JSON ONLY: {"summary": "<one line>", "archetypes": ["key", ...], '
    '"theme": {"accent": "<amber|emerald|sky|rose|violet|coral|teal|gold>", '
    '"icon": "<one icon name>"}}\n'
    "Pick 1 archetype for a focused request, 2-4 for a broad life-area. No prose."
)


def _strip_fence(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.endswith("```"):
            s = s.rsplit("```", 1)[0]
        if s.startswith("json\n"):
            s = s[5:]
    return s.strip()


def decode_intent(prompt: str) -> dict[str, Any] | None:
    """LLM step (live only). Returns a decoded intent or None on ANY failure so the
    caller falls back to select_archetypes. Never raises."""
    valid = {a.key for a in REGISTRY}
    user = f"{archetype_menu()}\n\nUser request: {prompt}\n\nReturn the decode JSON."
    try:
        raw = llm.generate(user, system=DECODE_SYSTEM_PROMPT)
        data = json.loads(_strip_fence(raw))
    except (LLMError, json.JSONDecodeError, ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    keys = [k for k in data.get("archetypes", []) if k in valid]
    if not keys:
        return None
    theme = data.get("theme") if isinstance(data.get("theme"), dict) else {}
    return {"summary": str(data.get("summary", "")), "archetypes": keys, "theme": theme}
