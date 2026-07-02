"""Turn a natural-language prompt into a ModuleConfig.

The orchestrator never returns UI code. It returns a structured ModuleConfig
that the frontend renders with its trusted component library.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import TypeVar

from pydantic import ValidationError

from src import llm
from src.schema import ClarifyingQuestion, LLMError, ModuleConfig, RefusalError

_T = TypeVar("_T")


class _InvalidOutput(Exception):
    """The model returned unparseable/invalid JSON (not an explicit refusal).
    These are retried; explicit refusals/questions are not."""


_RETRY_NOTE = (
    "\n\nIMPORTANT: your previous reply could not be parsed. Output ONLY valid JSON "
    "in the exact required shape — no prose, no markdown, no code fences."
)

_MODULE_SCHEMA = ModuleConfig.model_json_schema()


def _retry_count() -> int:
    """Smaller/local models occasionally slip on strict JSON; one cheap retry
    recovers most of those. Disabled in stub mode (no model call)."""
    if llm.is_stub_mode():
        return 0
    try:
        return max(0, int(os.environ.get("TRUS_LLM_MAX_RETRIES", "1")))
    except ValueError:
        return 1


_COMPONENT_DOCS = """Available component types (use exactly these "type" values):
- text_input   — free-text field.   Fields: id, label, type, placeholder?
- number_input — numeric entry.     Fields: id, label, type, min?, max?, step?, unit?
- checkbox     — boolean toggle.    Fields: id, label, type
- slider       — bounded number.    Fields: id, label, type, min, max, step, unit?
- progress_bar — visual progress.   Fields: id, label, type, max, bound_to? (intra-module component id),
                                    source_module_id? (cross-module: reads that module's bound_to field)
- list         — free-text items.   Fields: id, label, type, item_label, placeholder?
- metric       — READ-ONLY derived number aggregated across ALL session modules.
                 Fields: id, label, type, formula ("sum"|"count"|"avg"|"max"|"min"),
                 source_component_id (the component id to aggregate), unit?
                 Use metric when the user wants a running total, average, or count
                 across multiple modules (e.g. total calories across meal logs).
- rating       — star rating.        Fields: id, label, type, max? (default 5)
- tags         — chip labels.        Fields: id, label, type, placeholder?
- kpi          — ONE big headline number with a label. Fields: id, label, type, unit?
- date         — a date picker.      Fields: id, label, type, include_time?
- table        — structured grid.    Fields: id, label, type, columns (list of column names)
                 Use for guests, transactions, inventory, anything row/column shaped.
- calendar     — a month calendar of marked days. Fields: id, label, type
                 Use for schedules, habit day-marking, trip days, streaks.
- chart        — a chart drawn from data the user enters. Fields: id, label, type,
                 chart_type ("bar"|"line"|"area"|"pie"), unit?
                 Use for trends, spending over time, distributions.
- dropdown     — pick one of set options.  Fields: id, label, type, options (list of strings)
- choice_chips — pick one option as chips.  Fields: id, label, type, options (list of strings)
- color        — a colour swatch.           Fields: id, label, type
- sparkline    — tiny inline trend line.    Fields: id, label, type, unit?
- ring         — circular progress ring.    Fields: id, label, type, max, bound_to? (a number/slider id)
- timeline     — chronological event strip. Fields: id, label, type
- button       — an action button.          Fields: id, label, type, action ("calculator"|"timer"|"increment"|"add_item"), target? (component id for increment/add_item)
- section      — a labelled group header.    Fields: id, label, type. Use to structure a tool into sections.
- divider      — a thin horizontal rule.     Fields: id, label(""), type.
- kanban       — a BOARD of columns of cards. Fields: id, label, type, columns (list of column names, e.g. ["To do","Doing","Done"]). Use for pipelines, backlogs, workflows, stages.
- heatmap      — a streak/contribution grid. Fields: id, label, type, unit?. Use for habit/mood/activity day-marking over time.
- gauge        — a radial meter.             Fields: id, label, type, min, max, unit?. Use for a single level (hydration, sleep score, budget used).
- checklist    — checkable items w/ progress. Fields: id, label, type. Use for packing, onboarding, routines.
- gallery      — a grid of image thumbnails. Fields: id, label, type. Use for moodboards, wishlists, inspiration.
- note         — a multi-line text area.      Fields: id, label, type, placeholder?. Use for journals, descriptions, reflections.
- tracker      — MULTI-SUBJECT tracker; EACH row has its OWN streak + completion%, and the
                 tick resets each period. Fields: id, label, type, period ("day"|"week"), goal?.
                 PREFER THIS over a lone checkbox+streak whenever the user tracks SEVERAL
                 things over time (habits, routines, daily disciplines, per-person check-ins) —
                 it individualises the metrics per subject instead of one shared number.

Also: set "columns": 2 on a module to lay its components out in a TWO-COLUMN grid (great for dashboards and forms). Wide components (section, divider, table, chart, calendar, kanban, heatmap, timeline, gallery, note) automatically span both columns.
AVOID WASTED SPACE: if a tool has 4+ short fields (number/text/kpi/rating/slider/date/dropdown/color), set "columns": 2 so it reads as a compact grid instead of a tall sparse column. Don't pad a tool with empty or redundant fields. Keep one clear primary block per tool.

CHOOSE COMPONENTS AND A LAYOUT THAT MATCH THE SUBJECT — vary the FORMAT, don't always make a single vertical form. A task pipeline → a kanban board; a habit → a heatmap; a dashboard → columns:2 with kpis + chart + gauge; a journal → a note + heatmap; a packing list → a checklist.

CHOOSE COMPONENTS THAT MATCH THE SUBJECT so each tool LOOKS like what it is:
a calendar request → a calendar; a guest list → a table; spending over time → a chart;
a headline figure → a kpi; a review → a rating. Do not reduce everything to text/number fields."""

SYSTEM_PROMPT = f"""You are the Trus orchestrator. Your job is to turn a user's intent
into a ModuleConfig — a JSON document that the frontend renders using a fixed component
library. You do not write HTML, CSS, JavaScript, or any UI code.

{_COMPONENT_DOCS}

Output JSON ONLY, with this shape:
{{
  "title": "Module title (short, human-readable)",
  "components": [ {{ "id": "stable_snake_case_id", "type": "...", "label": "...", ... }}, ... ],
  "state": {{ "component_id": <prefilled value> }},
  "layout": {{ "x": 0, "y": 0, "width": 360, "height": 320 }},
  "summary_component_id": "id of the component that best represents this module at a glance (optional)",
  "icon": "one icon NAME from: activity, leaf, dollar, check, book, repeat, smile, calendar, plane, music, cap, briefcase, droplet, moon, film, cart, star, target, list, grid, chart, camera, heart, home, folder, bell, paw, sparkles",
  "accent": "one token from: amber, emerald, sky, rose, violet, coral, teal, gold",
  "columns": 1
}}

Rules:
1. Use only the component types above. No others.
2. ids are stable, snake_case, unique within a module.
3. ADAPT TO THE SPECIFIC REQUEST — tailor fields, labels, units, ranges to what was asked.
   Prefill "state" with any concrete values mentioned. Use the user's own terms for labels.
   A seed skeleton may be provided; reshape it freely.
4. If existing modules are listed, prefer metric/progress_bar cross-module bindings where
   they add real value (e.g. a dashboard that aggregates workout totals).
5. Prefer 3-6 components unless the request clearly needs more.
6. GIVE IT A DISTINCT LOOK. Choose an "icon" (one name from the list above) and an "accent" token that fit the
   subject, so two different tools never look the same at a glance. Match the accent to the
   domain's feel (e.g. fitness→emerald, finance→amber/gold, travel→sky, wellness→rose,
   creative→violet, food→coral) and vary it across requests — do not default everything to amber.
7. If the request is too vague to produce a useful module — AND one short question would
   unlock it — output exactly: {{ "question": "<one short, specific question>" }}
   Only do this when the answer genuinely changes the module structure (e.g. you cannot
   pick sensible fields, units, or ranges without knowing). If you can make a reasonable
   default, do so instead.
8. Do not narrate. Output the JSON object and nothing else.
9. If the request is illicit or structurally impossible, output exactly:
   {{ "refusal": "<one-sentence reason>" }}
"""


def _strip_codefence(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.endswith("```"):
            s = s.rsplit("```", 1)[0]
        if s.startswith("json\n"):
            s = s[5:]
    return s.strip()


REFINE_SYSTEM_PROMPT = f"""You are the Trus orchestrator. Your task is to update an existing
ModuleConfig based on the user's instruction.

The current config is provided as JSON. Apply the requested change and return the updated
ModuleConfig as JSON — same format, same output rules as generation.

{_COMPONENT_DOCS}

Rules:
1. Use only the component types above.
2. Preserve state values for any component that survives the edit unchanged (same id, same type).
3. Add, remove, rename, or reorder components to match the instruction.
4. New ids must be snake_case and not collide with surviving ids.
5. If other session modules are listed, use metric/cross-module bindings where helpful.
6. Keep the existing "icon" and "accent" unless the user asks to change the look; if they do,
   pick a new icon name and/or accent token (amber, emerald, sky, rose, violet, coral, teal, gold).
7. Do not narrate. Output the JSON object and nothing else.
8. If the request is illicit or structurally impossible, return:
   {{ "refusal": "<one-sentence reason>" }}
"""

SYNTHESIZE_SYSTEM_PROMPT = f"""You are the Trus orchestrator. The user has multiple modules
on their canvas. Generate a single dashboard ModuleConfig that surfaces the most important
cross-module insights using metric and progress_bar (cross-module) components.

{_COMPONENT_DOCS}

Rules:
1. Use metric components to aggregate numeric values across modules (totals, averages, counts).
2. Use progress_bar with source_module_id to show a specific module's progress.
3. Prefer 4-8 components. Title it something like "Dashboard" or domain-specific ("Fitness Overview").
   Give it an "icon" name (e.g. "chart" or "layers") and an "accent" token (amber, emerald, sky, rose, violet, coral, teal, gold).
4. Do not narrate. Output the JSON object and nothing else.
5. If there is nothing meaningful to synthesize, output:
   {{ "refusal": "Not enough data across modules to synthesize a dashboard." }}
"""


def _module_context(modules: list[ModuleConfig]) -> str:
    if not modules:
        return ""
    lines = [f"- {m.title}: {', '.join(c.id for c in m.components)}" for m in modules]
    return (
        "\n\nExisting modules on canvas (reference their component ids for cross-module bindings):\n"
        + "\n".join(lines)
    )


def _seeded_prompt(prompt: str, existing_modules: list[ModuleConfig] | None = None) -> str:
    """Ground generation with the nearest preloaded skeleton, which the model is
    told to adapt to the request. This is "preloaded templates that adjust to the
    user's content" — a seed, not a fixed answer."""
    from src.stub_templates import pick_template

    seed = json.dumps(pick_template(prompt))
    context = _module_context(existing_modules or [])
    return (
        f"User request: {prompt}\n\n"
        f"Nearest starting skeleton (adapt freely — reshape fields, labels, ranges, "
        f"and prefill state to match the request; do not just return it as-is):\n{seed}"
        f"{context}\n\n"
        f"Return the adapted ModuleConfig JSON."
    )


def _parse_module_config(raw: str) -> ModuleConfig:
    cleaned = _strip_codefence(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise _InvalidOutput(f"non-JSON output: {e.msg}") from e
    if isinstance(data, dict) and "refusal" in data:
        raise RefusalError(str(data["refusal"]))
    if isinstance(data, dict) and "question" in data and len(data) == 1:
        raise ClarifyingQuestion(str(data["question"]))
    try:
        return ModuleConfig.model_validate(data)
    except ValidationError as e:
        raise _InvalidOutput(f"invalid ModuleConfig: {e.errors()[0]['msg']}") from e


def _generate_validated(
    user: str,
    system: str,
    parse: Callable[[str], _T],
    *,
    schema: dict | None = None,
    expect_array: bool = False,
) -> _T:
    """Generate, parse, and retry once on unparseable output. Explicit refusals
    and clarifying questions propagate immediately (they are not model slips)."""
    last: Exception | None = None
    for attempt in range(1 + _retry_count()):
        msg = user if attempt == 0 else user + _RETRY_NOTE
        raw = llm.generate(msg, system=system, schema=schema, expect_array=expect_array).text
        try:
            return parse(raw)
        except _InvalidOutput as e:
            last = e
    raise RefusalError(f"The model could not produce a valid result ({last}).")


def generate_module(
    prompt: str,
    existing_modules: list[ModuleConfig] | None = None,
) -> ModuleConfig:
    return _generate_validated(
        _seeded_prompt(prompt, existing_modules),
        SYSTEM_PROMPT,
        _parse_module_config,
        schema=_MODULE_SCHEMA,
    )


DECOMPOSE_SYSTEM_PROMPT = f"""You are the Trus orchestrator. Turn the user's intent into the
SET of tools (modules) they actually need — a coordinated system when appropriate, not always
a single card. You never write UI code; you return ModuleConfig JSON.

{_COMPONENT_DOCS}

Output JSON ONLY: an ARRAY of 1-6 ModuleConfig objects. Each object has this shape:
{{
  "title": "...", "components": [ {{ "id","type","label",... }} ], "state": {{ }},
  "layout": {{ "x":0,"y":0,"width":360,"height":320 }},
  "icon": "<one icon name: activity|leaf|dollar|check|book|repeat|smile|calendar|plane|music|cap|briefcase|droplet|moon|film|cart|star|target|list|grid|chart|camera|heart|home|folder|bell|paw|sparkles>", "accent": "<amber|emerald|sky|rose|violet|coral|teal|gold>",
  "columns": 1, "summary_component_id": "<id?>"
}}

HOW MANY TOOLS:
- A focused request ("a workout log", "a calorie tracker", "a reading list") → ONE strong module.
- A broad project or life-area → SEVERAL complementary modules forming a system. Examples:
  • "plan my Japan trip" → [Itinerary (calendar), Trip Budget (chart + kpi/progress), Packing List (table or list), To-Do (list)]
  • "organize my wedding" → [Guest List (table), Budget (chart), Timeline (calendar), Vendors (table)]
  • "my semester" → [Class Schedule (calendar), Assignment Tracker (table), GPA (kpi), Study Habits (calendar)]
  • "moving house" → [Moving Checklist (list), Budget (chart), Address Change (table), Timeline (calendar)]

Rules:
1. Only the component types listed above. Pick the ones that make each tool LOOK right.
2. Give EACH module a DISTINCT icon and accent so the system reads as a colour-coded set.
3. snake_case unique ids within each module. Prefill "state" with any concrete values mentioned.
4. ADAPT to the specifics of the request — never return generic rebranded clones.
5. If existing modules are listed, you may add cross-module metric/progress_bar bindings.
6. If the request is too vague AND one short question would unlock it, output exactly:
   {{ "question": "<one short question>" }}
7. If illicit or impossible, output exactly: {{ "refusal": "<one-sentence reason>" }}
8. Output ONLY the JSON array (or the single refusal/question object). No prose.
"""


def _seeded_system(
    prompt: str,
    existing_modules: list[ModuleConfig] | None = None,
    seed_override: list | None = None,
) -> str:
    from src.stub_templates import pick_system

    # seed_override (the nearest past generation from the semantic cache) makes the
    # template library self-growing; fall back to the keyword builders when the
    # cache has nothing close.
    seed = json.dumps(seed_override if seed_override is not None else pick_system(prompt))
    context = _module_context(existing_modules or [])
    return (
        f"User request: {prompt}\n\n"
        f"Example starting system (adapt freely — change the number of tools, fields, components, "
        f"labels, icons, accents, and prefill state to match the request; do not return it as-is):\n{seed}"
        f"{context}\n\n"
        f"Return the adapted ModuleConfig JSON array."
    )


def _parse_modules(raw: str) -> list[ModuleConfig]:
    cleaned = _strip_codefence(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise _InvalidOutput(f"non-JSON output: {e.msg}") from e
    if isinstance(data, dict):
        if "refusal" in data:
            raise RefusalError(str(data["refusal"]))
        if "question" in data and len(data) == 1:
            raise ClarifyingQuestion(str(data["question"]))
        # tolerate {"modules": [...]}; otherwise treat a lone object as a one-item list
        data = data["modules"] if isinstance(data.get("modules"), list) else [data]
    if not isinstance(data, list):
        raise _InvalidOutput("did not return a list of modules.")
    out: list[ModuleConfig] = []
    for item in data:
        if not isinstance(item, dict) or "refusal" in item:
            continue
        try:
            out.append(ModuleConfig.model_validate(item))
        except ValidationError:
            continue
    if not out:
        raise _InvalidOutput("produced no valid modules.")
    return out


def generate_modules(
    prompt: str,
    existing_modules: list[ModuleConfig] | None = None,
) -> list[ModuleConfig]:
    """Decompose a request into the set of tools it needs (1-6 modules)."""
    if llm.is_stub_mode():
        from src.stub_templates import pick_system

        return [ModuleConfig.model_validate(c) for c in pick_system(prompt)]
    from src import semantic_cache

    # Cache: an (almost) identical past prompt is reused for free; a near match
    # becomes the generation seed (so the library grows with real usage).
    mode, cached = semantic_cache.lookup("system", prompt)
    if mode == "hit" and cached:
        try:
            return [ModuleConfig.model_validate(c) for c in cached]
        except ValidationError:
            pass  # stale/incompatible cache entry → fall through and regenerate
    result = _generate_validated(
        _seeded_system(prompt, existing_modules, seed_override=cached if mode == "seed" else None),
        DECOMPOSE_SYSTEM_PROMPT,
        _parse_modules,
        expect_array=True,
    )
    last = llm.last_call.get()
    # R-403: only a definitely-non-degraded call may seed the cache — an unknown
    # provenance (last is None) is not safe to treat as "not degraded".
    if last is not None and not last.degraded:
        semantic_cache.store("system", prompt, [m.model_dump(mode="json") for m in result])
    return result


def generate_modules_from_file(
    prompt: str,
    data: bytes,
    mime: str,
    existing_modules: list[ModuleConfig] | None = None,
) -> list[ModuleConfig]:
    """Build tools shaped around an uploaded document/image (Gemini multimodal)."""
    if llm.is_stub_mode():
        from src.stub_templates import pick_system

        return [ModuleConfig.model_validate(c) for c in pick_system(prompt)]
    user_message = (
        _seeded_system(prompt, existing_modules)
        + "\n\nA file is attached above. Read it and build tools shaped around its ACTUAL content — "
        "prefill state with the real values, dates, and rows you extract from it."
    )
    last: Exception | None = None
    for attempt in range(1 + _retry_count()):
        msg = user_message if attempt == 0 else user_message + _RETRY_NOTE
        raw = llm.generate_from_file(msg, DECOMPOSE_SYSTEM_PROMPT, data, mime)
        if not raw or raw.strip() in ("{}", ""):
            raise RefusalError(
                "This file type can't be read with the current model configuration — "
                "try an image, or paste the document's text into the prompt."
            )
        try:
            return _parse_modules(raw)
        except _InvalidOutput as e:
            last = e
    raise RefusalError(f"The model could not produce a valid result ({last}).")


def refine_module(
    config: ModuleConfig,
    prompt: str,
    existing_modules: list[ModuleConfig] | None = None,
) -> ModuleConfig:
    if llm.is_stub_mode():
        raise LLMError("Refine needs a live model; the app is in offline template mode.")
    context = _module_context(existing_modules or [])
    user_message = (
        f"Current ModuleConfig:\n{config.model_dump_json()}\n\n"
        f"User instruction: {prompt}"
        f"{context}\n\n"
        f"Return the updated ModuleConfig JSON."
    )
    return _generate_validated(
        user_message, REFINE_SYSTEM_PROMPT, _parse_module_config, schema=_MODULE_SCHEMA
    )


def synthesize_workspace(modules: list[ModuleConfig]) -> ModuleConfig:
    """Generate a dashboard module that aggregates values across all session modules."""
    if llm.is_stub_mode():
        from src.schema import Metric

        return ModuleConfig(
            title="Dashboard",
            components=[
                Metric(
                    id="total_metric",
                    label="Total (stub)",
                    formula="sum",
                    source_component_id="value",
                ),
            ],
        )
    summaries = json.dumps([m.model_dump() for m in modules])
    user_message = (
        f"Session modules (JSON):\n{summaries}\n\n"
        f"Generate a dashboard ModuleConfig that surfaces the most important "
        f"cross-module insights using metric and progress_bar components."
    )
    return _generate_validated(
        user_message, SYNTHESIZE_SYSTEM_PROMPT, _parse_module_config, schema=_MODULE_SCHEMA
    )
