# Generation Variation + Website Sheen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make module generation deliberately pick the UI *format* that best models the user's intent (with more visual variety), and make the generation animation carry the marketing site's "matte sheen" across three mechanics.

**Architecture:** Backend gains an archetype registry + a deterministic `select_archetypes` selector and a live-only `decode_intent` LLM step (hybrid: LLM decode when a key is present, deterministic fallback always). Frontend aligns the per-tile build band to the site's canonical sheen, adds a one-shot title sheen, and a canvas "reading" beam during generation.

**Tech Stack:** Python 3.11 / FastAPI / pytest (backend); Next.js + TypeScript / Tailwind / GSAP (frontend).

## Global Constraints

- Backend modules import as `src.*`; tests mirror src as `tests/test_<module>.py`.
- Gemini calls go only through `src/llm.py` (`llm.generate(...)`). Never call `google.genai` from services.
- The orchestrator returns `ModuleConfig` (Pydantic) — never raw HTML/CSS/JS.
- Frontend: interactive pieces marked `"use client"`. Honor reduced motion (`data-motion` / `prefers-reduced-motion`).
- Brand sheen color is `--white-matte` = `#f0efed` = `rgb(240,239,237)`.
- Keep these tests green (update only where consolidation *intentionally* changes output, never weaken an assertion): `test_stub_templates.py`, `test_decomposition.py`, `test_orchestrator.py`.
- Guard after every backend task: `cd backend && python -m pytest -q` passes.

---

### Task 1: Archetype registry — `src/archetypes.py`

**Files:**
- Create: `backend/src/archetypes.py`
- Test: `backend/tests/test_archetypes.py`

**Interfaces:**
- Produces: `Archetype` (dataclass: `key: str`, `label: str`, `signals: tuple[str,...]`, `builder: Callable[[], dict]`, `accent: str`, `icon: str`); `REGISTRY: list[Archetype]`; `archetype_menu() -> str`; `theme_for(prompt: str) -> dict` returning `{"accent": str, "icon": str}`.
- Consumes: builders from `src.stub_templates` (`_workout`, `_calorie`, `_task_board`, `_habit_grid`, `_daily_journal`, `_calendar_tool`, `_contacts`, `_budget`, `_life_dashboard`, `_moodboard`, `_reading`, `_weekly_retro`, etc.).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_archetypes.py
from src.archetypes import REGISTRY, archetype_menu, theme_for
from src.schema import ModuleConfig
from src.stub_templates import _finalize


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_archetypes.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.archetypes'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/src/archetypes.py
"""Named UI archetypes: the formats generation can choose from.

An archetype pairs an intent signature with a seed builder and a default theme.
`select_archetypes` (Task 2) scores these against a prompt; the orchestrator uses
the registry for the live archetype MENU, theming, and the deterministic fallback.
Builders are reused from stub_templates so there is one set of seed builders.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from src import stub_templates as st


@dataclass(frozen=True)
class Archetype:
    key: str
    label: str
    signals: tuple[str, ...]
    builder: Callable[[], dict]
    accent: str
    icon: str
    when: str  # one-line "use when…" for the LLM menu


REGISTRY: list[Archetype] = [
    Archetype("workout_calendar", "Workout (calendar)", ("workout", "gym", "exercise", "lift", "training", "fitness"), st._workout, "emerald", "activity", "logging an activity per day → a calendar of marked days + supporting fields"),
    Archetype("calorie_log", "Calorie log", ("calorie", "nutrition", "diet", "macro", "meal log", "food log"), st._calorie, "coral", "leaf", "daily totals against a goal"),
    Archetype("kanban_pipeline", "Pipeline (kanban)", ("pipeline", "kanban", "task board", "backlog", "workflow", "sprint", "leads", "deals"), st._task_board, "violet", "grid", "stages/columns of cards → a kanban board"),
    Archetype("habit_heatmap", "Habit (heatmap)", ("habit", "streak", "routine", "daily check"), st._habit_grid, "emerald", "repeat", "marking a thing done over many days → a heatmap"),
    Archetype("calendar_schedule", "Schedule (calendar)", ("calendar", "schedule", "timetable", "itinerary"), st._calendar_tool, "sky", "calendar", "dates/days → a month calendar"),
    Archetype("table_ledger", "Ledger (table)", ("guest list", "attendee", "roster", "inventory", "stock", "contacts", "address book", "transactions"), st._contacts, "teal", "list", "row/column data → a table"),
    Archetype("budget_chart", "Budget (chart)", ("budget", "expense", "spend", "money", "cost", "finance"), st._budget, "amber", "dollar", "amounts over time/categories → a chart + totals"),
    Archetype("dashboard", "Dashboard", ("dashboard", "overview", "daily overview", "life overview"), st._life_dashboard, "sky", "chart", "several metrics at a glance → columns:2 with kpis/chart/gauge"),
    Archetype("journal_note", "Journal", ("journal", "diary", "gratitude", "reflection"), st._daily_journal, "rose", "book", "free writing over time → a note + heatmap"),
    Archetype("reading_list", "Reading list", ("read", "book", "reading", "watchlist", "movie", "show"), st._reading, "violet", "book", "a collection of items to get through"),
    Archetype("moodboard_gallery", "Moodboard", ("moodboard", "mood board", "inspiration", "wishlist"), st._moodboard, "violet", "camera", "visual collection → a gallery"),
    Archetype("retro_review", "Retro / review", ("retro", "retrospective", "weekly review"), st._weekly_retro, "teal", "repeat", "structured periodic review → sections + lists"),
]

# Builders that may not exist under these exact names are referenced above only if
# present in stub_templates; the test imports each builder via the dataclass so a
# missing name fails loudly at import (caught by Task 1's validate test).


def archetype_menu() -> str:
    lines = [f"- {a.key} ({a.label}): {a.when}" for a in REGISTRY]
    return "ARCHETYPE MENU (pick the key(s) whose format best models the intent):\n" + "\n".join(lines)


_DOMAIN_THEME: list[tuple[tuple[str, ...], str, str]] = [
    (("workout", "gym", "fitness", "exercise", "run", "training"), "emerald", "activity"),
    (("budget", "expense", "money", "finance", "spend", "invoice", "savings", "debt"), "amber", "dollar"),
    (("trip", "travel", "vacation", "flight", "japan", "itinerary"), "sky", "plane"),
    (("wellness", "mood", "journal", "gratitude", "meditation", "sleep"), "rose", "heart"),
    (("creative", "moodboard", "design", "art", "inspiration", "wishlist"), "violet", "sparkles"),
    (("food", "recipe", "meal", "calorie", "diet", "nutrition"), "coral", "leaf"),
]


def theme_for(prompt: str) -> dict:
    low = prompt.lower()
    for keys, accent, icon in _DOMAIN_THEME:
        if any(re.search(rf"\b{re.escape(k)}", low) for k in keys):
            return {"accent": accent, "icon": icon}
    return {"accent": "teal", "icon": "sparkles"}
```

> If any referenced `st._*` builder name does not exist, replace it with the closest existing builder from `stub_templates.py` (verified via `grep -n "^def _" backend/src/stub_templates.py`). The validate test in Step 1 will catch a wrong name immediately.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_archetypes.py -q`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/src/archetypes.py backend/tests/test_archetypes.py
git commit -m "feat(backend): archetype registry + domain theming"
```

---

### Task 2: Deterministic selector — `select_archetypes`

**Files:**
- Modify: `backend/src/archetypes.py`
- Test: `backend/tests/test_archetypes.py`

**Interfaces:**
- Produces: `select_archetypes(prompt: str, limit: int = 3) -> list[Archetype]` — best matches first, by count of matched signals; empty list when nothing matches.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_archetypes.py
import pytest
from src.archetypes import select_archetypes


@pytest.mark.parametrize(
    "prompt,expected_key,expected_type",
    [
        ("a workout log",        "workout_calendar", "calendar"),
        ("organize a sprint backlog", "kanban_pipeline", "kanban"),
        ("daily habit streak",   "habit_heatmap",    "heatmap"),
        ("wedding guest list",   "table_ledger",     "table"),
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
```

> NOTE: This test requires the builders for `workout_calendar` (calendar component) and `table_ledger` (table component) to actually contain those component types. `_workout` is enriched to a calendar in Task 5; `st._contacts` already uses a table. If you run Task 2 before Task 5, the `workout_calendar` assertion on `"calendar" in types` will fail — that is expected; it passes once Task 5 lands. To keep tasks independently green, implement Task 5's `_workout` calendar enrichment **before** running this test, or temporarily assert only `chosen[0].key`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_archetypes.py::test_select_routes_intent_to_format -q`
Expected: FAIL with `ImportError: cannot import name 'select_archetypes'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to backend/src/archetypes.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_archetypes.py -q`
Expected: PASS (the `workout_calendar` calendar assertion passes after Task 5; otherwise see the NOTE)

- [ ] **Step 5: Commit**

```bash
git add backend/src/archetypes.py backend/tests/test_archetypes.py
git commit -m "feat(backend): select_archetypes deterministic selector"
```

---

### Task 3: Live intent decode — `decode_intent`

**Files:**
- Modify: `backend/src/archetypes.py`
- Test: `backend/tests/test_archetypes.py`

**Interfaces:**
- Produces: `decode_intent(prompt: str) -> dict | None` returning `{"summary": str, "archetypes": [keys present in REGISTRY], "theme": {"accent","icon"}}` or `None` on any failure. Calls `llm.generate(...)`. `DECODE_SYSTEM_PROMPT: str`.
- Consumes: `src.llm.generate`.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_archetypes.py
import json
from unittest.mock import patch
from src.archetypes import decode_intent
from src.schema import LLMError


def _decode_with(text):
    return patch("src.archetypes.llm.generate", return_value=text)


def test_decode_intent_parses_known_keys():
    raw = json.dumps({"summary": "log workouts", "archetypes": ["workout_calendar"], "theme": {"accent": "emerald", "icon": "activity"}})
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_archetypes.py -k decode -q`
Expected: FAIL with `ImportError: cannot import name 'decode_intent'`

- [ ] **Step 3: Write minimal implementation**

```python
# add near the top of backend/src/archetypes.py (after the `import` block)
import json

from src import llm
from src.schema import LLMError

# ... (Archetype, REGISTRY, etc.) ...

DECODE_SYSTEM_PROMPT = (
    "You are the Trus intent decoder. Read the user's request and choose which UI "
    "archetype(s) best model it, picking ONLY from the menu keys provided.\n\n"
    "Output JSON ONLY: {\"summary\": \"<one line>\", \"archetypes\": [\"key\", ...], "
    "\"theme\": {\"accent\": \"<amber|emerald|sky|rose|violet|coral|teal|gold>\", "
    "\"icon\": \"<one icon name>\"}}\n"
    "Pick 1 archetype for a focused request, 2-4 for a broad life-area. No prose."
)


def decode_intent(prompt: str) -> dict | None:
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


def _strip_fence(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.endswith("```"):
            s = s.rsplit("```", 1)[0]
        if s.startswith("json\n"):
            s = s[5:]
    return s.strip()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_archetypes.py -k decode -q`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/src/archetypes.py backend/tests/test_archetypes.py
git commit -m "feat(backend): decode_intent LLM step with graceful fallback"
```

---

### Task 4: Wire `generate_modules` to the hybrid pipeline

**Files:**
- Modify: `backend/src/services/orchestrator.py` (`DECOMPOSE_SYSTEM_PROMPT`, `_seeded_system`, `generate_modules`)
- Test: `backend/tests/test_decomposition.py`

**Interfaces:**
- Consumes: `archetypes.decode_intent`, `archetypes.select_archetypes`, `archetypes.archetype_menu`, `archetypes.theme_for`.
- Behavior: live path runs `decode_intent` (after a cache miss), falls back to `select_archetypes`, injects chosen archetype keys + theme into the seed message; the menu is appended to `DECOMPOSE_SYSTEM_PROMPT`. The generation `llm.generate` call remains the LAST call so context-injection assertions hold. Stub path unchanged.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_decomposition.py
def test_decode_runs_then_generation_is_last_call():
    """decode_intent makes the first generate() call; the seeded GENERATION call is
    last and still carries existing-module context."""
    from src.schema import ModuleConfig, TextInput

    existing = [ModuleConfig(title="Meal Log", components=[TextInput(id="meal", label="Meal")])]
    arr = json.dumps([{"title": "T", "components": [{"id": "d", "type": "calendar", "label": "Days"}]}])
    with _fake_llm(arr) as gen:
        mods = orchestrator.generate_modules("plan my fitness", existing_modules=existing)
    assert mods[0].components[0].type == "calendar"
    # last call is the generation call and includes the existing module context
    assert "Meal Log" in gen.call_args[0][0]
    assert gen.call_count >= 2  # decode + generate
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_decomposition.py::test_decode_runs_then_generation_is_last_call -q`
Expected: FAIL (`gen.call_count` == 1, decode step not wired yet)

- [ ] **Step 3: Write minimal implementation**

In `orchestrator.py`, append the menu to the decompose system prompt:

```python
# at the end of the DECOMPOSE_SYSTEM_PROMPT f-string body, before the closing """,
# add a line that pulls in the menu lazily is not possible in a module-level f-string,
# so instead build it at import time:
from src.archetypes import archetype_menu as _archetype_menu

DECOMPOSE_SYSTEM_PROMPT = DECOMPOSE_SYSTEM_PROMPT + "\n\n" + _archetype_menu() + (
    "\nBuild each tool in the format of its best-matching archetype unless a clearly "
    "better one fits. Keep one coherent theme (accents/icons) across the set."
)
```

Extend `_seeded_system` to accept optional archetype hints:

```python
def _seeded_system(
    prompt: str,
    existing_modules: list[ModuleConfig] | None = None,
    seed_override: list | None = None,
    archetype_hint: str | None = None,
) -> str:
    from src.stub_templates import pick_system

    seed = json.dumps(seed_override if seed_override is not None else pick_system(prompt))
    context = _module_context(existing_modules or [])
    hint = f"\n\n{archetype_hint}" if archetype_hint else ""
    return (
        f"User request: {prompt}\n\n"
        f"Example starting system (adapt freely — change the number of tools, fields, components, "
        f"labels, icons, accents, and prefill state to match the request; do not return it as-is):\n{seed}"
        f"{hint}{context}\n\n"
        f"Return the adapted ModuleConfig JSON array."
    )
```

Rewire `generate_modules` (replace the body after the stub short-circuit):

```python
def generate_modules(
    prompt: str,
    existing_modules: list[ModuleConfig] | None = None,
) -> list[ModuleConfig]:
    """Decompose a request into the set of tools it needs (1-6 modules)."""
    if llm.is_stub_mode():
        from src.stub_templates import pick_system

        return [ModuleConfig.model_validate(c) for c in pick_system(prompt)]
    from src import archetypes, semantic_cache

    mode, cached = semantic_cache.lookup("system", prompt)
    if mode == "hit" and cached:
        try:
            return [ModuleConfig.model_validate(c) for c in cached]
        except ValidationError:
            pass

    # Hybrid decode: LLM intent decode when available, deterministic fallback always.
    archetype_hint: str | None = None
    if not (mode == "seed" and cached):
        decoded = archetypes.decode_intent(prompt)
        if decoded:
            keys = decoded["archetypes"]
            theme = decoded.get("theme") or archetypes.theme_for(prompt)
        else:
            chosen = archetypes.select_archetypes(prompt)
            keys = [a.key for a in chosen]
            theme = archetypes.theme_for(prompt)
        if keys:
            archetype_hint = (
                f"Best-matching archetype(s): {', '.join(keys)}. "
                f"Theme: accent={theme.get('accent')}, icon={theme.get('icon')}."
            )

    seed_override = cached if (mode == "seed" and cached) else None
    result = _generate_validated(
        _seeded_system(prompt, existing_modules, seed_override=seed_override, archetype_hint=archetype_hint),
        DECOMPOSE_SYSTEM_PROMPT,
        _parse_modules,
        expect_array=True,
    )
    semantic_cache.store("system", prompt, [m.model_dump(mode="json") for m in result])
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_decomposition.py tests/test_orchestrator.py -q`
Expected: PASS (all — decode degrades to None on the fixed mock payloads, generation stays last)

- [ ] **Step 5: Commit**

```bash
git add backend/src/services/orchestrator.py backend/tests/test_decomposition.py
git commit -m "feat(backend): hybrid intent->archetype generation pipeline"
```

---

### Task 5: Format remap + domain theming in stub templates

**Files:**
- Modify: `backend/src/stub_templates.py` (`_workout`, `_visual_for`)
- Test: `backend/tests/test_stub_templates.py`

**Interfaces:**
- Behavior: `_workout()` becomes calendar-led (keeps title "Workout Log"); `_visual_for` becomes domain-aware via `archetypes.theme_for` (lazy import to avoid a cycle).

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_stub_templates.py
def test_workout_template_is_calendar_led():
    cfg = pick_template("track my workouts at the gym")
    assert "workout" in cfg["title"].lower()
    types = [c["type"] for c in cfg["components"]]
    assert "calendar" in types  # the format now models "log per day"


def test_generic_visuals_are_domain_aware():
    from src.stub_templates import _visual_for
    _, accent = _visual_for("monthly budget and savings")
    assert accent in ("amber", "gold")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_stub_templates.py -k "calendar_led or domain_aware" -q`
Expected: FAIL (`calendar` not in workout types; accent not domain-aware)

- [ ] **Step 3: Write minimal implementation**

Replace `_workout()`:

```python
def _workout():
    return _mod(
        "Workout Log",
        "🏋️",
        "emerald",
        [
            _cal("days", "Workout days"),
            _t("exercise", "Today's focus", "e.g. Push day — bench, dips"),
            _n("sets", "Sets"),
            _sl("weight", "Top set weight", 0, 315, 5, "lb"),
            _pr("weekly", "Weekly sessions", 5, "sets"),
        ],
        "days",
        columns=2,
    )
```

Make `_visual_for` domain-aware (keep the hash as the final fallback so unrouted prompts still vary):

```python
def _visual_for(prompt: str) -> tuple[str, str]:
    from src.archetypes import theme_for

    ICONS = {
        "activity": "🏋️", "dollar": "💰", "plane": "✈️", "heart": "💗",
        "sparkles": "✨", "leaf": "🥗",
    }
    t = theme_for(prompt)
    if t["accent"] != "teal":  # a real domain match (teal is the neutral default)
        return ICONS.get(t["icon"], "✨"), t["accent"]
    h = sum(ord(ch) for ch in prompt.strip().lower()) if prompt.strip() else 0
    return _GENERIC_ICONS[h % len(_GENERIC_ICONS)], _GENERIC_ACCENTS[h % len(_GENERIC_ACCENTS)]
```

- [ ] **Step 4: Run the full stub + archetype suite**

Run: `cd backend && python -m pytest tests/test_stub_templates.py tests/test_archetypes.py -q`
Expected: PASS (incl. the Task 2 `workout_calendar` calendar assertion, now satisfied)

- [ ] **Step 5: Commit**

```bash
git add backend/src/stub_templates.py backend/tests/test_stub_templates.py
git commit -m "feat(backend): workout->calendar remap + domain-aware stub theming"
```

---

### Task 6: Sheen A1 — canonical build scan band (frontend)

**Files:**
- Modify: `frontend/src/components/Module.tsx` (the `data-assembly="scan"` element, ~line 314-317)
- Modify: `frontend/src/lib/assembly.ts` (beat 4 easing)

**Interfaces:** none (visual only). No frontend test runner — verify by build + screenshot.

- [ ] **Step 1: Update the scan band geometry + gradient**

In `Module.tsx`, replace the scan `<div data-assembly="scan" ...>` style/width:

```tsx
            <div data-assembly="scan" className="absolute inset-y-0 left-0 opacity-0"
              style={{
                width: "36%",
                background:
                  "linear-gradient(100deg, transparent 0%, " +
                  "color-mix(in srgb, var(--white-matte) 10%, transparent) 45%, " +
                  "color-mix(in srgb, var(--white-matte) 16%, transparent) 50%, " +
                  "color-mix(in srgb, var(--white-matte) 10%, transparent) 55%, " +
                  "transparent 100%)",
              }} />
```

(Remove the old `w-1/2` class — width is now set inline to 36%.)

- [ ] **Step 2: Align beat-4 easing**

In `assembly.ts`, beat 4:

```ts
  // 4 · Scan sweep — the canonical matte sheen band sweeps L→R (DESIGN-ETHOS §5.2).
  if (scan) tl.fromTo(scan,
    { xPercent: -130, opacity: 1 },
    { xPercent: 330, duration: 0.5, ease: "power2.inOut" }, 0.18);
```

- [ ] **Step 3: Verify build compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Module.tsx frontend/src/lib/assembly.ts
git commit -m "feat(frontend): match build scan band to site matte sheen"
```

---

### Task 7: Sheen A2 — one-shot title sheen (frontend)

**Files:**
- Modify: `frontend/src/app/globals.css` (add `@keyframes trus-title-sheen` + `.title-sheen`)
- Modify: `frontend/src/lib/assembly.ts` (toggle the class after the label wipe; clear on finalize)

- [ ] **Step 1: Add the CSS**

Append to `globals.css`:

```css
/* One-shot matte sheen swept across a module title as it builds (DESIGN-ETHOS §5.4). */
@keyframes trus-title-sheen {
  from { background-position: 200% 0; }
  to { background-position: -50% 0; }
}
.title-sheen {
  background-image: linear-gradient(
    100deg,
    var(--foreground) 0%, var(--foreground) 40%,
    #ffffff 50%,
    var(--foreground) 60%, var(--foreground) 100%
  );
  background-size: 200% 100%;
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  color: transparent;
  animation: trus-title-sheen 0.6s ease-out 1;
}
```

- [ ] **Step 2: Toggle from the assembly timeline**

In `assembly.ts`, after the beat-5 label-wipe block, add:

```ts
  // 5b · Title sheen — a one-shot matte sheen passes over the revealed label.
  if (label) {
    tl.add(() => label.classList.add("title-sheen"), 0.52);
  }
```

And in `finalize()`, remove the class:

```ts
    if (label) { label.style.clipPath = ""; label.classList.remove("title-sheen"); }
```

- [ ] **Step 3: Verify build compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/globals.css frontend/src/lib/assembly.ts
git commit -m "feat(frontend): one-shot title matte sheen on build"
```

---

### Task 8: Sheen A3 — canvas reading beam during generation (frontend)

**Files:**
- Create: `frontend/src/components/GenerationBeam.tsx`
- Modify: `frontend/src/app/globals.css` (`@keyframes trus-readbeam` + `.read-beam`)
- Modify: `frontend/src/components/PromptBar.tsx` (add `onGeneratingChange` prop; fire in `submit`)
- Modify: `frontend/src/app/page.tsx` (hold `generating` state; pass to Canvas + PromptBar)
- Modify: `frontend/src/components/Canvas.tsx` (add `generating?: boolean` prop; render the beam)

- [ ] **Step 1: Add the CSS**

Append to `globals.css`:

```css
/* A light beam sweeping the canvas while Trus reads the user's intent. */
@keyframes trus-readbeam {
  0% { transform: translateX(-20vw); opacity: 0; }
  12% { opacity: 1; }
  88% { opacity: 1; }
  100% { transform: translateX(120vw); opacity: 0; }
}
.read-beam {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 64px;
  pointer-events: none;
  background: linear-gradient(
    90deg,
    transparent 0%,
    color-mix(in srgb, var(--white-matte) 6%, transparent) 40%,
    color-mix(in srgb, var(--white-matte) 18%, transparent) 50%,
    color-mix(in srgb, var(--white-matte) 6%, transparent) 60%,
    transparent 100%
  );
  animation: trus-readbeam 1.4s linear infinite;
}
```

- [ ] **Step 2: Create the component**

```tsx
// frontend/src/components/GenerationBeam.tsx
"use client";

export function GenerationBeam({ active }: { active: boolean }) {
  if (!active) return null;
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden z-[5]" aria-hidden>
      <span className="read-beam" />
    </div>
  );
}
```

- [ ] **Step 3: Thread state through PromptBar**

In `PromptBar.tsx`, add to `Props`:

```tsx
  onGeneratingChange?: (busy: boolean) => void;
```

Add it to the destructured params, then in `submit`, fire it around the work (always reset in `finally`):

```tsx
  const submit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    const v = prompt.trim();
    if ((!v && !file) || loading) return;
    setLoading(true);
    onGeneratingChange?.(true);
    setError(null);
    try {
      // ... unchanged ...
    } catch (err) {
      // ... unchanged ...
    } finally {
      setLoading(false);
      onGeneratingChange?.(false);
    }
  };
```

- [ ] **Step 4: Hold state in page.tsx and pass it down**

In `page.tsx`, add near the other `useState` hooks:

```tsx
  const [generating, setGenerating] = useState(false);
```

Pass to `<Canvas ... generating={generating} />` and `<PromptBar ... onGeneratingChange={setGenerating} />` (add the props to the existing JSX from Step start).

- [ ] **Step 5: Render the beam in Canvas**

In `Canvas.tsx`: add `generating?: boolean;` to `Props`, destructure it, import the component (`import { GenerationBeam } from "./GenerationBeam";`), and render it as the first child inside the root `<div ref={containerRef} ...>`:

```tsx
      <GenerationBeam active={!!generating} />
```

- [ ] **Step 6: Verify build compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/GenerationBeam.tsx frontend/src/app/globals.css frontend/src/components/PromptBar.tsx frontend/src/app/page.tsx frontend/src/components/Canvas.tsx
git commit -m "feat(frontend): canvas reading beam during generation"
```

---

### Task 9: Full verification

**Files:** none (verification only).

- [ ] **Step 1: Backend tests + coverage guard**

Run: `cd backend && python -m pytest -q`
Expected: all pass.
Run: `cd backend && python -m pytest -q 2>/dev/null && echo passed`
Expected: `passed`.

- [ ] **Step 2: Frontend typecheck + lint + build**

Run: `cd frontend && npx tsc --noEmit && npm run lint && npm run build`
Expected: no errors.

- [ ] **Step 3: Reduced-motion sanity (visual)**

With the app running (`make` targets / `uvicorn` + `npm run dev`), set the appearance to reduced motion and generate: the modules render in their final state with **no** beam and **no** sheen animation; with full motion, the build band, title sheen, and canvas beam all appear. Capture screenshots of both.

- [ ] **Step 4: Commit any test-fixture updates** (if Step 1 required intentional assertion updates).

```bash
git add -A && git commit -m "test: update fixtures for archetype consolidation"
```

---

## Self-Review

**Spec coverage:**
- A1 build band → Task 6. A2 title sheen → Task 7. A3 canvas beam → Task 8.
- B1 registry → Task 1. B2 selector → Task 2. B3 decode_intent → Task 3. B4 orchestration → Task 4. B5 library/remap → Task 5. B6 theming → Tasks 1 (`theme_for`) + 5 (`_visual_for`).
- Stub + live both covered (Task 4 stub short-circuit unchanged; live path adds decode). Reduced motion → Task 9 Step 3.

**Placeholder scan:** No TBD/TODO; all code blocks complete. The one conditional ("if a builder name doesn't exist, swap it") is a guarded instruction with a verification command, not a placeholder.

**Type consistency:** `Archetype` fields and `select_archetypes`/`decode_intent`/`archetype_menu`/`theme_for` signatures match between Tasks 1-4. `onGeneratingChange`/`generating` names consistent across Tasks 8 (PromptBar/page/Canvas). `_strip_fence` defined in Task 3 and used only there.

**Known cross-task dependency:** Task 2's `workout_calendar` calendar assertion depends on Task 5's `_workout` enrichment — flagged inline in Task 2's NOTE; both green once Task 5 lands (verified together in Task 5 Step 4).
