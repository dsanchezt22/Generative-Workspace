"""Layout Studio — a use-case-indexed library of candidate ModuleConfig layouts.

Each layout is MODELLED AFTER how a leading app in that category structures the
experience (e.g. Cronometer's nutrient dashboard, MyFitnessPal's food diary).
These are LEGITIMATELY GENERATED, not scraped: the model emits original Trus
configs informed by well-known app patterns it already knows. The output is the
same artifact a scraper would aim for — a per-use-case database of layouts — in
the format the app actually renders, and it feeds the generation seed pool.
"""
from __future__ import annotations

import json

from pydantic import TypeAdapter, ValidationError

from src import llm
from src.schema import Component, LLMError, ModuleConfig, RefusalError

_COMPONENT_ADAPTER = TypeAdapter(Component)
from src.services.orchestrator import (
    _COMPONENT_DOCS,
    _RETRY_NOTE,
    _retry_count,
    _strip_codefence,
)

# Curated categories. `apps` are leaders the layouts are modelled after; `brief`
# describes the characteristic on-screen elements; `seed_prompts` drive the
# offline fallback AND the key used when a layout is promoted into the seed pool.
USE_CASES: list[dict] = [
    {"key": "calorie", "title": "Calorie & nutrition", "icon": "leaf", "accent": "coral",
     "apps": ["Cronometer", "MyFitnessPal", "Cal AI", "MacroFactor", "Lose It!"],
     "brief": "a food/meal diary (table or list), a calorie & macro budget shown as rings/gauges/progress bars, a micronutrient breakdown, a weight-trend chart, water intake",
     "seed_prompts": ["calorie tracker", "nutrition log", "food diary"]},
    {"key": "fitness", "title": "Fitness & workouts", "icon": "activity", "accent": "emerald",
     "apps": ["Strava", "Strong", "Hevy", "Apple Fitness", "Nike Training Club"],
     "brief": "a workout log (exercise/sets/reps/weight table), a weekly training-volume chart, personal-record KPIs, a streak heatmap, a rest timer",
     "seed_prompts": ["workout tracker", "gym log", "training plan"]},
    {"key": "travel", "title": "Travel planning", "icon": "plane", "accent": "sky",
     "apps": ["TripIt", "Wanderlog", "Google Trips", "Roadtrippers"],
     "brief": "a day-by-day itinerary calendar/timeline, a trip budget (chart + total KPI), a packing checklist, a bookings/reservations table",
     "seed_prompts": ["travel planner", "trip itinerary", "vacation plan"]},
    {"key": "finance", "title": "Personal finance", "icon": "dollar", "accent": "gold",
     "apps": ["YNAB", "Mint", "Copilot", "Monarch", "Rocket Money"],
     "brief": "a budget-by-category breakdown (chart / progress bars), a spending-over-time chart, a net-worth/balance KPI, a transactions table, savings-goal rings",
     "seed_prompts": ["budget tracker", "expense tracker", "personal finance dashboard"]},
    {"key": "productivity", "title": "Tasks & productivity", "icon": "check", "accent": "violet",
     "apps": ["Todoist", "Things", "TickTick", "Notion", "Sunsama"],
     "brief": "a task list with priorities, a kanban board (To do / Doing / Done), a today/agenda view, a project tracker, progress toward a goal",
     "seed_prompts": ["to-do list", "task manager", "project board"]},
    {"key": "habits", "title": "Habits & routines", "icon": "repeat", "accent": "teal",
     "apps": ["Streaks", "Habitica", "Way of Life", "Done"],
     "brief": "a multi-subject habit tracker (each habit its own streak + completion), a contribution heatmap, a daily checklist, streak KPIs",
     "seed_prompts": ["habit tracker", "daily routine", "streak tracker"]},
    {"key": "reading", "title": "Reading & learning", "icon": "book", "accent": "amber",
     "apps": ["Goodreads", "StoryGraph", "Audible", "Anki"],
     "brief": "a reading-list table (title/author/status/rating), a pages-read progress bar, a yearly reading-goal ring, a ratings breakdown chart",
     "seed_prompts": ["reading list", "book tracker", "study tracker"]},
    {"key": "wellness", "title": "Sleep & wellness", "icon": "moon", "accent": "sky",
     "apps": ["Oura", "Whoop", "Sleep Cycle", "Calm"],
     "brief": "a sleep-duration chart, a readiness/score gauge, a mood/energy rating, a hydration or meditation streak",
     "seed_prompts": ["sleep tracker", "wellness dashboard"]},
    {"key": "mood", "title": "Mood & journaling", "icon": "smile", "accent": "rose",
     "apps": ["Daylio", "Reflectly", "Stoic", "Journey"],
     "brief": "a daily mood rating or choice chips, a journal note, a mood-over-time chart, a gratitude list, a calendar/heatmap of entries",
     "seed_prompts": ["mood journal", "gratitude journal", "daily journal"]},
    {"key": "home", "title": "Home & chores", "icon": "home", "accent": "emerald",
     "apps": ["Tody", "Sweepy", "OurHome", "Cozi"],
     "brief": "a recurring-chores checklist/tracker, a household-tasks kanban, a shopping list, a chore-rotation table",
     "seed_prompts": ["chore tracker", "cleaning schedule", "household tasks"]},
    {"key": "events", "title": "Events & planning", "icon": "calendar", "accent": "violet",
     "apps": ["The Knot", "Zola", "Eventbrite"],
     "brief": "a guest-list table (name / RSVP), a budget chart, a planning-timeline calendar, a vendor or to-do checklist",
     "seed_prompts": ["event planner", "wedding planner", "party checklist"]},
    {"key": "content", "title": "Content & creators", "icon": "film", "accent": "coral",
     "apps": ["Later", "Buffer", "Notion content calendars", "Trello"],
     "brief": "a content calendar, an idea-backlog kanban, a publishing checklist, per-platform metric KPIs",
     "seed_prompts": ["content calendar", "social media planner", "creator dashboard"]},
]

_BY_KEY = {u["key"]: u for u in USE_CASES}


def use_cases() -> list[dict]:
    return USE_CASES


def get_use_case(key: str) -> dict | None:
    return _BY_KEY.get(key)


STUDIO_SYSTEM = f"""You are Trus's Layout Studio. For a given USE CASE you design a set of
DISTINCT candidate tool layouts, each MODELLED AFTER how a well-known app in that category
structures the experience. You never write UI code — you return Trus ModuleConfig JSON built
ONLY from the trusted component library.

{_COMPONENT_DOCS}

Output JSON ONLY: an ARRAY of layout objects, each EXACTLY this shape:
{{
  "label": "<short name for this layout, e.g. 'Nutrient dashboard'>",
  "inspired_by": "<the app/style it models, e.g. 'Cronometer'>",
  "config": {{ "title": "...", "components": [ {{ "id","type","label",... }} ], "icon": "...", "accent": "...", "columns": 1, "state": {{}} }}
}}

Rules:
1. Each config is a valid ModuleConfig using only the component types above.
2. Layouts must be GENUINELY DIFFERENT in structure (different component mix / columns) —
   model DIFFERENT apps' approaches, not recolours of one layout.
3. Pick components that make each tool LOOK like that app's screen (a diary → table/list;
   macros → rings/gauges; trends → chart; streaks → heatmap/tracker; a board → kanban).
4. snake_case unique ids within each config. Vary icon/accent across layouts.
5. Output ONLY the JSON array — no prose, no code fences.
"""


class _Invalid(Exception):
    """Unparseable studio output (retried)."""


def _parse_layouts(raw: str) -> list[dict]:
    cleaned = _strip_codefence(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise _Invalid(f"non-JSON: {e.msg}") from e
    if isinstance(data, dict) and isinstance(data.get("layouts"), list):
        data = data["layouts"]
    if not isinstance(data, list):
        raise _Invalid("not a list")
    out: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        cfg = item.get("config") if isinstance(item.get("config"), dict) else item
        try:
            mc = ModuleConfig.model_validate(cfg)
        except ValidationError:
            continue
        out.append({
            "label": str(item.get("label") or mc.title or "Layout"),
            "inspired_by": str(item.get("inspired_by") or ""),
            "config": mc.model_dump(mode="json"),
        })
    if not out:
        raise _Invalid("no valid layouts")
    return out


def _stub_layouts(uc: dict, n: int) -> list[dict]:
    """Offline / fallback: build layouts from the keyword template library."""
    from src.stub_templates import pick_template

    apps = uc.get("apps") or [""]
    seeds = uc.get("seed_prompts") or [uc["title"]]
    out: list[dict] = []
    for i, sp in enumerate(seeds[: max(1, n)]):
        cfg = pick_template(sp)
        out.append({
            "label": cfg.get("title") or sp.title(),
            "inspired_by": apps[i % len(apps)],
            "config": cfg,
        })
    return out


def generate_layouts(use_case_key: str, n: int = 4) -> list[dict]:
    """Produce N distinct candidate layouts for a use case. Uses the configured
    model; falls back to keyword templates offline or on repeated model failure."""
    uc = _BY_KEY.get(use_case_key)
    if uc is None:
        raise RefusalError(f"Unknown use case: {use_case_key}")
    n = max(1, min(n, 8))
    if llm.is_stub_mode():
        return _stub_layouts(uc, n)
    user = (
        f"USE CASE: {uc['title']}.\n"
        f"Leading apps to model (use DIFFERENT ones across the layouts): {', '.join(uc['apps'])}.\n"
        f"Characteristic on-screen elements: {uc['brief']}.\n"
        f"Produce {n} distinct candidate layouts as the JSON array."
    )
    last: Exception | None = None
    for attempt in range(1 + _retry_count()):
        try:
            raw = llm.generate(
                user if attempt == 0 else user + _RETRY_NOTE,
                system=STUDIO_SYSTEM, expect_array=True,
            )
            return _parse_layouts(raw)[:n]
        except _Invalid as e:
            last = e
        except LLMError as e:
            last = e
            break  # endpoint unavailable — stop retrying, fall back
    # The model couldn't produce valid layouts — still give the user something.
    return _stub_layouts(uc, n)


# ── Vision import: a reference screenshot → a Trus layout ─────────────────────

STUDIO_IMPORT_SYSTEM = f"""You are Trus's Layout Studio vision importer. You are shown a
SCREENSHOT of a real app's interface. Reproduce ITS LAYOUT as a SINGLE Trus ModuleConfig
using ONLY the trusted component library — match the on-screen STRUCTURE (a food diary →
table/list; macro rings → ring/gauge; a trend → chart; a streak grid → heatmap; a board →
kanban; a big figure → kpi). Capture the APPROACH/STRUCTURE, not the app's exact text or
branding — use your own generic field labels.

{_COMPONENT_DOCS}

Output ONLY one ModuleConfig JSON object:
{{ "title": "...", "components": [ {{ "id","type","label",... }} ], "icon": "...", "accent": "...", "columns": 1, "state": {{}} }}
Do NOT use the 'button' component. No prose, no code fences."""


def _coerce(data: object) -> ModuleConfig:
    """Validate a config, dropping any individual components that don't validate
    (a vision model may invent an out-of-enum field) rather than failing wholesale."""
    if isinstance(data, dict) and isinstance(data.get("components"), list):
        good = []
        for c in data["components"]:
            try:
                _COMPONENT_ADAPTER.validate_python(c)
                good.append(c)
            except ValidationError:
                continue
        data = {**data, "components": good}
    return ModuleConfig.model_validate(data)


def _parse_one(raw: str) -> ModuleConfig:
    cleaned = _strip_codefence(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise _Invalid(f"non-JSON: {e.msg}") from e
    if isinstance(data, list):  # tolerate an array — take the first valid config
        for item in data:
            try:
                return _coerce(item)
            except ValidationError:
                continue
        raise _Invalid("no valid config in array")
    try:
        return _coerce(data)
    except ValidationError as e:
        raise _Invalid(f"invalid ModuleConfig: {e.errors()[0]['msg']}") from e


def import_from_image(use_case_key: str, data: bytes, mime: str) -> dict:
    """Read a reference screenshot with a vision model and return a layout dict
    {label, inspired_by, config}. Only the derived layout is kept — never the image.

    This is the original single-shot importer (kept for back-compat / the fast path).
    The staged capture→transform engine is `capture_layout`."""
    uc = _BY_KEY.get(use_case_key)
    if uc is None:
        raise RefusalError(f"Unknown use case: {use_case_key}")
    user = (
        f"This is a screenshot of a {uc['title'].lower()} app interface. "
        f"Reproduce its layout as one Trus ModuleConfig using the matching components."
    )
    last: Exception | None = None
    for attempt in range(2):  # one retry — vision models occasionally slip on JSON
        raw = llm.vision_describe(STUDIO_IMPORT_SYSTEM, user if attempt == 0 else user + _RETRY_NOTE, data, mime)
        try:
            mc = _parse_one(raw)
            return {
                "label": mc.title or "Imported layout",
                "inspired_by": "reference screenshot",
                "config": mc.model_dump(mode="json"),
            }
        except _Invalid as e:
            last = e
    raise RefusalError(f"Couldn't read a usable layout from that image ({last}).")


def capture_layout(use_case_key: str, data: bytes, mime: str, *, match_colors: bool = False) -> dict:
    """Staged screenshot → layout: CAPTURE the image into a full-fidelity IR, then
    TRANSFORM it onto the trusted component library (re-skinned, no feature dropped),
    score capability coverage, and return an enriched layout dict
    {label, inspired_by, config, capture_meta, confidence, ir_digest, structured_text}.
    Image is never persisted. Raises RefusalError / LLMError like import_from_image."""
    uc = _BY_KEY.get(use_case_key)
    if uc is None:
        raise RefusalError(f"Unknown use case: {use_case_key}")
    from src.services.capture.engine import capture_to_layout

    return capture_to_layout(data, mime, uc["title"].lower(), match_colors=match_colors)
