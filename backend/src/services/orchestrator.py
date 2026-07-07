"""Turn a natural-language prompt into a ModuleConfig.

The orchestrator never returns UI code. It returns a structured ModuleConfig
that the frontend renders with its trusted component library.
"""

from __future__ import annotations

import contextvars
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from pydantic import ValidationError

from src import db, llm
from src.schema import (
    ClarifyingQuestion,
    DataSource,
    LLMError,
    ModuleConfig,
    RefusalError,
    StructureAutomation,
    StructurePage,
    StructureProposal,
)
from src.services import extract
from src.services.live_data import ALLOWED_PROVIDERS

_T = TypeVar("_T")

# R-103/R-301: the plan paragraph parsed alongside the last generate_modules()
# decomposition. A side channel (mirrors llm.last_call) so generate_modules()
# keeps returning list[ModuleConfig] — every existing call site is untouched —
# while the route can still surface the plan on GenerateResponse. Only
# generate_modules() (the generate/preview entry point) sets this; the file
# upload path does not read it.
last_plan: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "orchestrator_last_plan", default=None
)

# SURF/ONB-1: the multi-surface structure proposal parsed alongside the last
# generate_modules() call, surfaced the same side-channel way as last_plan so the
# return type stays list[ModuleConfig] and every existing caller is untouched. A
# structure result returns [] and sets this instead; the route reads it.
last_structure: contextvars.ContextVar[StructureProposal | None] = contextvars.ContextVar(
    "orchestrator_last_structure", default=None
)


class _InvalidOutput(Exception):
    """The model returned unparseable/invalid JSON (not an explicit refusal).
    These are retried; explicit refusals/questions are not."""


_RETRY_NOTE = (
    "\n\nIMPORTANT: your previous reply could not be parsed. Output ONLY valid JSON "
    "in the exact required shape — no prose, no markdown, no code fences."
)

_MODULE_SCHEMA = ModuleConfig.model_json_schema()

_UNREADABLE_FILE_REFUSAL = (
    "This file can't be read with the current model configuration — "
    "configure a live model, or paste the document's text into the prompt."
)


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
- feed         — newest-first entries an automation writes into. Fields: id, label, type, max_items?.
                 Use as the landing surface for a digest/watcher/reminder automation product.

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


# R-302: cap on the rendered "Recent conversation:" block (bounded overall
# length, not per-message) so a long history never dominates the prompt.
_CONVERSATION_CONTEXT_BUDGET = 1200

# Stage-2b backlog: a cap on the FINAL composed message once seed-JSON +
# module-context + exchange fold + conversation block are all stacked (see
# _seeded_system below). `_CONVERSATION_CONTEXT_BUDGET` already bounds the
# conversation block on its own, but a large module-context list (many
# existing modules) can still push the total over a sane size. This is a
# last-resort guard, not the primary budget.
_MAX_PROMPT_CHARS = 12000


def _conversation_block(messages: list[dict] | None) -> str:
    """Render the owner's recent persisted conversation (db.recent_messages,
    oldest-first) as a bounded context block, so e.g. "make it like the one I
    made yesterday" has something to bind to (R-302). Bounded to ~1200 chars
    total; when it doesn't fit, OLDER turns are dropped first (messages are
    already oldest-first, so this pops from the front)."""
    if not messages:
        return ""
    lines = [f"{m['role']}: {m['text']}" for m in messages]
    while lines and sum(len(x) for x in lines) + len(lines) - 1 > _CONVERSATION_CONTEXT_BUDGET:
        lines.pop(0)
    if not lines:
        # Even the single most recent turn alone exceeds the budget — keep its
        # tail (the most recent characters) rather than drop it entirely.
        tail = f"{messages[-1]['role']}: {messages[-1]['text']}"
        lines = [tail[-_CONVERSATION_CONTEXT_BUDGET:]]
    return "\n\nRecent conversation:\n" + "\n".join(lines)


# R-803: cap on the rendered "What I know about you:" block — mirrors
# _CONVERSATION_CONTEXT_BUDGET's bounded-overall-length (not per-fact)
# approach so an established profile never dominates the prompt.
_PROFILE_CONTEXT_BUDGET = 800
_PROFILE_CONTEXT_MAX_FACTS = 10


def _profile_block(facts: list[dict] | None) -> str:
    """Render the owner's profile (db.profile_list, most-recently-updated
    first) as a bounded "What I know about you:" context block, so a
    returning user's proposals are shaped by what Trus has already learned
    about them (R-803). Mirrors _conversation_block's budgeting: only the
    ~10 most recent facts are even considered, then bounded to ~800 chars
    total; when it doesn't fit, the OLDEST of those ~10 (the tail of this
    most-recent-first list) are dropped first."""
    if not facts:
        return ""
    lines = [f"- ({f['kind']}) {f['text']}" for f in facts[:_PROFILE_CONTEXT_MAX_FACTS]]
    while lines and sum(len(x) for x in lines) + len(lines) - 1 > _PROFILE_CONTEXT_BUDGET:
        lines.pop()
    if not lines:
        # Even the single most recent fact alone exceeds the budget — keep its
        # head rather than drop it entirely.
        head = f"- ({facts[0]['kind']}) {facts[0]['text']}"
        lines = [head[:_PROFILE_CONTEXT_BUDGET]]
    return "\n\nWhat I know about you:\n" + "\n".join(lines)


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
    # R-705: same strip-defense as _parse_modules — a corrupted/out-of-domain
    # data_source (REFINE_SYSTEM_PROMPT hands the model a config that may already
    # carry a valid one) is stripped before validation so it never kills the
    # whole module; the component survives as manual entry.
    if isinstance(data, dict):
        _sanitize_module_data_sources(data)
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

Output JSON ONLY: an OBJECT with this shape:
{{
  "plan": "<one short paragraph: what you will build and why it fits the request>",
  "modules": [ <1-6 ModuleConfig objects>, each shaped:
    {{
      "title": "...", "components": [ {{ "id","type","label",... }} ], "state": {{ }},
      "layout": {{ "x":0,"y":0,"width":360,"height":320 }},
      "icon": "<one icon name: activity|leaf|dollar|check|book|repeat|smile|calendar|plane|music|cap|briefcase|droplet|moon|film|cart|star|target|list|grid|chart|camera|heart|home|folder|bell|paw|sparkles>", "accent": "<amber|emerald|sky|rose|violet|coral|teal|gold>",
      "columns": 1, "summary_component_id": "<id?>"
    }}
  ]
}}

HOW MANY TOOLS:
- A focused request ("a workout log", "a calorie tracker", "a reading list") → ONE strong module.
- A broad project or life-area → SEVERAL complementary modules forming a system. Examples:
  • "plan my Japan trip" → [Itinerary (calendar), Trip Budget (chart + kpi/progress), Packing List (table or list), To-Do (list)]
  • "organize my wedding" → [Guest List (table), Budget (chart), Timeline (calendar), Vendors (table)]
  • "my semester" → [Class Schedule (calendar), Assignment Tracker (table), GPA (kpi), Study Habits (calendar)]
  • "moving house" → [Moving Checklist (list), Budget (chart), Address Change (table), Timeline (calendar)]

STRUCTURES (multi-surface systems): when the request is a whole life-area or an ongoing
operation that needs DISTINCT surfaces ("organize my whole life", "run my freelance
business", "manage the family"), output this OBJECT instead of "modules":
{{
  "plan": "<one short paragraph: the system you will build and why>",
  "pages": [ 2-4 objects, each an APP SURFACE:
    {{ "name": "<short app name>", "icon": "<one icon name from the list above>",
      "accent": "<one accent token from the list above>",
      "purpose": "<one sentence: what this surface is for>",
      "modules": [ 1-6 ModuleConfig objects, exactly the shape above ] }} ],
  "automations": [ 0-6 objects, each a proposed always-on agent for ONE page:
    {{ "name": "...", "description": "<plain language: exactly what it does each run>",
      "schedule": "hourly|daily|weekly", "action_type": "watch|summarize|track|remind|draft",
      "page": <index into pages>,
      "target_component_id": "<a component id on that page it writes into, usually a feed>",
      <action-specific fields, see below> }} ]
}}
- A focused request still gets the flat {{"plan","modules"}} shape — never force pages.
- Give a page a "feed" component when an automation reports into it; point target_component_id at it.
- action_type — what the agent does each run:
  • summarize — an LLM digest of the page's tools into the target feed/note (the default choice).
  • watch — check a live value and flag a threshold; REQUIRES "provider" (weather|nutrition),
    "query", and "op" (over|under) + "threshold".
  • track — append a source number into a target chart/series; REQUIRES "source_component_id"
    (a number component id on the SAME page).
  • remind — list what is still pending on a tracker/checklist into the feed.
  • draft — an LLM-composed message into the feed; provide "instruction".
- When unsure whether an automation is warranted, emit NO automation.

LIVE DATA BINDINGS (R-701/R-702/R-705): Metric, Kpi, Ring, Gauge, and ProgressBar MAY carry an
optional "data_source" field — but ONLY when the user's intent clearly falls into one of these
TWO launched domains. There are no others:
- Calorie/food/nutrition intent → "data_source": {{"provider": "nutrition", "query": {{"food": "<item>"}}}}
- Weather/trip/run/hike/outdoor intent → "data_source": {{"provider": "weather", "query": {{"place": "<city>"}}}}
  (lat/lon also accepted: {{"lat": <num>, "lon": <num>}})
Example — a calorie tracker's Kpi "Calories":
  {{ "id": "calories", "type": "kpi", "label": "Calories", "unit": "kcal",
     "data_source": {{"provider": "nutrition", "query": {{"food": "banana"}}}} }}
Example — a trip planner's Metric "Saturday Forecast":
  {{ "id": "forecast", "type": "metric", "label": "Saturday Forecast", "formula": "avg",
     "source_component_id": "forecast",
     "data_source": {{"provider": "weather", "query": {{"place": "Tokyo"}}}} }}
For ANY other domain — stocks, flights, sports scores, currency rates, news, or anything else not
listed above — do NOT emit a data_source, even if the user asks for "live" or "real-time" data.
Leave the component as plain manual entry instead. Never fabricate a live binding for a source we
don't actually have (R-705) — an unlaunched domain gets no live badge, not a fake one.

Rules:
1. Only the component types listed above. Pick the ones that make each tool LOOK right.
2. Give EACH module a DISTINCT icon and accent so the system reads as a colour-coded set.
3. snake_case unique ids within each module. Prefill "state" with any concrete values mentioned.
4. ADAPT to the specifics of the request — never return generic rebranded clones.
5. If existing modules are listed, you may add cross-module metric/progress_bar bindings.
6. Ask AT MOST ONE clarifying question, and ONLY when the request is genuinely ambiguous —
   you cannot pick sensible fields, units, or ranges without the answer, and no reasonable
   default exists. When you do, output exactly (nothing else — no "plan", no "modules"):
   {{ "question": "<one short, specific question>" }}
7. If illicit or impossible, output exactly: {{ "refusal": "<one-sentence reason>" }}
8. Do not narrate. Output ONLY the JSON object above (or the single refusal/question object).
9. Only bind "data_source" for the two launched domains above (nutrition, weather) — see
   LIVE DATA BINDINGS. Every other domain stays manual entry, no data_source.
"""


def _cap_composed_prompt(
    head: str,
    context: str,
    convo_block: str,
    profile_block: str,
    exchange_block: str,
    tail: str,
) -> str:
    """Stage-2b backlog (extended for R-803's profile block): bound the final
    composed message to `_MAX_PROMPT_CHARS`. `head` (the raw user request +
    seed skeleton) and `exchange_block` (the interview answers) are NEVER
    truncated — the model needs both to do the job and to avoid re-asking an
    already-answered question. When over budget, the LOWEST-priority blocks
    are cut first: conversation and profile share that lowest tier (profile
    is no higher priority than conversation — conversation keeps the existing
    priority within the tier when both must shrink), then the module-context
    detail is trimmed only as a last resort."""
    full = head + context + convo_block + profile_block + exchange_block + tail
    if len(full) <= _MAX_PROMPT_CHARS:
        return full
    protected_len = len(head) + len(exchange_block) + len(tail)
    budget = max(0, _MAX_PROMPT_CHARS - protected_len)
    if len(context) >= budget:
        # No room left for conversation OR profile; module-context itself must
        # also be trimmed to what's left of the budget.
        convo_block = ""
        profile_block = ""
        context = context[:budget]
    else:
        remaining = budget - len(context)
        convo_block = convo_block[:remaining]
        profile_block = profile_block[: max(0, remaining - len(convo_block))]
    return head + context + convo_block + profile_block + exchange_block + tail


def _seeded_system(
    prompt: str,
    existing_modules: list[ModuleConfig] | None = None,
    seed_override: list | None = None,
    exchange_context: str | None = None,
    recent_messages: list[dict] | None = None,
    profile_facts: list[dict] | None = None,
) -> str:
    from src.stub_templates import pick_system

    # seed_override (the nearest past generation from the semantic cache) makes the
    # template library self-growing; fall back to the keyword builders when the
    # cache has nothing close.
    seed = json.dumps(seed_override if seed_override is not None else pick_system(prompt))
    context = _module_context(existing_modules or [])
    # R-302: the owner's recent persisted conversation (db.recent_messages, via
    # the generate/preview routes only — never the grounded-file path, where
    # document content already dominates). Bounded, never the cache key.
    convo_block = _conversation_block(recent_messages)
    # R-803: the owner's profile (db.profile_list(owner), fetched by
    # generate_modules — never the grounded-file path, same exclusion as the
    # conversation block above: document content already dominates there).
    # Bounded, never the cache key.
    profile_block = _profile_block(profile_facts)
    # R-102: the folded interview Q/A (built by the route from GenerateRequest.exchange)
    # reaches the model here so a multi-turn clarifying chain sees ALL prior answers —
    # never the semantic-cache key (see generate_modules — that stays the raw `prompt`).
    # A just-asked question may already be reflected in `convo_block` too (the persisted
    # history and the exchange fold overlap when a chain's earlier turns were logged) —
    # accepted rather than filtered; there's no reliable timestamp to correlate an
    # exchange turn against a messages row.
    exchange_block = (
        f"\n\nConversation so far (answers already given — do not ask about these again):\n"
        f"{exchange_context}"
        if exchange_context
        else ""
    )
    head = (
        f"User request: {prompt}\n\n"
        f"Example starting system (adapt freely — change the number of tools, fields, components, "
        f"labels, icons, accents, and prefill state to match the request; do not return it as-is):\n{seed}"
    )
    tail = "\n\nReturn the adapted ModuleConfig JSON array."
    # Stage-2b backlog: cap the total composed size AFTER everything above is
    # built — see _cap_composed_prompt's truncation priority.
    return _cap_composed_prompt(head, context, convo_block, profile_block, exchange_block, tail)


@dataclass
class _Decomposition:
    """Parsed result of a DECOMPOSE_SYSTEM_PROMPT response: the modules to build
    plus the optional plan paragraph the model gave for them (R-103/R-301). SURF:
    a broad-request answer instead carries a `structure` (pages + modules +
    proposed automations); `modules` is then [] and the route reads `structure`."""

    plan: str | None
    modules: list[ModuleConfig]
    structure: StructureProposal | None = None


def _sanitize_data_source(component: dict) -> None:
    """R-705 defense-in-depth: strip an invalid or out-of-domain `data_source`
    from a raw (pre-Pydantic) component dict, in place.

    `DataSource.provider` is a strict `Literal["weather", "nutrition"]`, so a
    well-formed-but-wrong-domain value (e.g. "stocks") — or any other malformed
    shape (an out-of-bounds `refresh_secs`, an oversized `query`, wrong value
    types) — would otherwise fail `ModuleConfig.model_validate()` for the WHOLE
    module, dropping every other component in it too. Sanitizing the raw dict
    BEFORE that validation call means the model's mistake costs only the
    live-data binding: the component keeps validating and renders as ordinary
    manual entry (never a whole-module rejection)."""
    raw = component.get("data_source")
    if raw is None:
        return
    if not isinstance(raw, dict):
        component["data_source"] = None
        return
    try:
        validated = DataSource.model_validate(raw)
    except ValidationError:
        component["data_source"] = None
        return
    if validated.provider not in ALLOWED_PROVIDERS:
        component["data_source"] = None


def _sanitize_module_data_sources(item: dict) -> None:
    components = item.get("components")
    if not isinstance(components, list):
        return
    for component in components:
        if isinstance(component, dict):
            _sanitize_data_source(component)


def _flatten(parsed: _Decomposition) -> list[ModuleConfig]:
    """The file/grounded paths never produce structures (v1): a structure parse
    degrades to its flattened modules (≤6), tools land flat with no pages."""
    if parsed.structure is not None:
        return [m for p in parsed.structure.pages for m in p.modules][:6]
    return parsed.modules


def _parse_structure(data: dict) -> _Decomposition:
    """SURF/ONB-1: parse a {"plan","pages","automations"} structure answer.
    Strip-don't-reject — one bad item costs only that item:
    - pages clipped to 4, each page's raw modules to 6 (BEFORE Pydantic);
    - invalid modules dropped individually; a 0-module page dropped;
    - each automation validated individually (garbage action_type → dropped: the
      parser can never emit an action_type the JSON didn't state), its `page`
      remapped through original→surviving index (dropped/out-of-range → dropped),
      and an unknown target_component_id set to None (confirm drops it if still
      unresolvable);
    - zero surviving pages → degrade to flat modules if any existed, else invalid.
    """
    plan_val = data.get("plan")
    plan = plan_val.strip() if isinstance(plan_val, str) and plan_val.strip() else None

    raw_pages = data.get("pages")
    raw_pages = raw_pages[:4] if isinstance(raw_pages, list) else []
    pages: list[StructurePage] = []
    all_valid_modules: list[ModuleConfig] = []
    surviving_index: dict[int, int] = {}
    for orig_idx, rp in enumerate(raw_pages):
        if not isinstance(rp, dict):
            continue
        raw_mods = rp.get("modules")
        raw_mods = raw_mods[:6] if isinstance(raw_mods, list) else []
        mods: list[ModuleConfig] = []
        for rm in raw_mods:
            if not isinstance(rm, dict):
                continue
            _sanitize_module_data_sources(rm)
            try:
                mc = ModuleConfig.model_validate(rm)
            except ValidationError:
                continue
            mods.append(mc)
            all_valid_modules.append(mc)
        if not mods:
            continue  # drop an emptied page
        try:
            page = StructurePage(
                name=rp.get("name") or "Untitled",
                icon=rp.get("icon"),
                accent=rp.get("accent"),
                purpose=rp.get("purpose"),
                modules=mods,
            )
        except ValidationError:
            continue
        surviving_index[orig_idx] = len(pages)
        pages.append(page)

    if not pages:
        # Zero surviving pages: degrade to flat modules (plan kept, automations
        # dropped) if any valid modules existed; else fall to the retry-once loop.
        if all_valid_modules:
            return _Decomposition(plan=plan, modules=all_valid_modules[:6])
        raise _InvalidOutput("structure produced no valid pages.")

    autos: list[StructureAutomation] = []
    for ra in data.get("automations") or []:
        if not isinstance(ra, dict):
            continue
        page_ref = ra.get("page")
        if not isinstance(page_ref, int) or isinstance(page_ref, bool):
            continue  # non-int page ref (str/float/list/None) → drop
        new_idx = surviving_index.get(page_ref)  # None → dropped/out-of-range page
        if new_idx is None:
            continue
        candidate = {**ra, "page": new_idx}
        comp_ids = {c.id for m in pages[new_idx].modules for c in m.components}
        if candidate.get("target_component_id") not in comp_ids:
            candidate["target_component_id"] = None
        try:
            autos.append(StructureAutomation.model_validate(candidate))
        except ValidationError:
            continue
    autos = autos[:6]

    try:
        structure = StructureProposal(plan=plan, pages=pages, automations=autos)
    except ValidationError as e:
        raise _InvalidOutput(f"invalid structure: {e.errors()[0]['msg']}") from e
    return _Decomposition(plan=plan, modules=[], structure=structure)


def _parse_modules(raw: str) -> _Decomposition:
    cleaned = _strip_codefence(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise _InvalidOutput(f"non-JSON output: {e.msg}") from e
    plan: str | None = None
    if isinstance(data, dict):
        if "refusal" in data:
            raise RefusalError(str(data["refusal"]))
        if "question" in data and len(data) == 1:
            raise ClarifyingQuestion(str(data["question"]))
        # SURF/ONB-1: a {"pages": [...]} answer is a multi-surface structure.
        if isinstance(data.get("pages"), list):
            return _parse_structure(data)
        if isinstance(data.get("modules"), list):
            # {"plan": str, "modules": [...]} (new) or {"modules": [...]} (already tolerated)
            plan_val = data.get("plan")
            if isinstance(plan_val, str) and plan_val.strip():
                plan = plan_val.strip()
            data = data["modules"]
        else:
            data = [data]  # a lone module object (back-compat)
    if not isinstance(data, list):
        raise _InvalidOutput("did not return a list of modules.")
    out: list[ModuleConfig] = []
    for item in data:
        if not isinstance(item, dict) or "refusal" in item:
            continue
        # R-705: strip any invalid/out-of-domain data_source BEFORE Pydantic
        # validation, so the model fabricating a bad live binding costs only
        # that binding (component survives as manual entry), not the module.
        _sanitize_module_data_sources(item)
        try:
            out.append(ModuleConfig.model_validate(item))
        except ValidationError:
            continue
    if not out:
        raise _InvalidOutput("produced no valid modules.")
    return _Decomposition(plan=plan, modules=out)


# R-102 hard cap ("never a fifth question"): appended to the user message when the
# model questions past an exhausted budget — one last chance to comply before refusal.
_BUILD_NOW_NOTE = (
    "\n\nDo NOT ask another question. Return the modules object NOW — "
    "build your best interpretation of everything above."
)

_QUESTION_CAP_REFUSAL = (
    "Four answers in, the model still couldn't settle on a build — "
    "try rephrasing the request with more detail."
)


def generate_modules(
    prompt: str,
    existing_modules: list[ModuleConfig] | None = None,
    owner: str = "local",
    exchange_context: str | None = None,
    allow_question: bool = True,
    recent_messages: list[dict] | None = None,
) -> list[ModuleConfig]:
    """Decompose a request into the set of tools it needs (1-6 modules).

    The cache is scoped to `owner` (R-903): a prompt is never reused across owners.
    `exchange_context` (R-102's folded interview Q/A, built by the route) reaches
    the MODEL via `_seeded_system` but never the semantic-cache key below — the
    key is always the raw `prompt`. Interview-specialized results are also never
    STORED under that key (see the store guard below). When `allow_question` is
    False (the route's 4-answered cap is exhausted), a ClarifyingQuestion from
    the model is not relayed: retry once with a strengthened build-now note, and
    refuse honestly if it still questions — the user never sees a fifth question.
    The parsed plan (R-103/R-301) is surfaced via `last_plan`, not the return
    value, so every existing caller of this function is unaffected.
    `recent_messages` (R-302: the owner's last ~10 persisted `messages` rows for
    the current page, oldest-first — see db.recent_messages) also reaches the
    model via `_seeded_system` only, never the cache key: an identical re-prompt
    still cache-HITs regardless of how the conversation has moved on since.
    `owner`'s profile (R-803: db.profile_list(owner), the ~10 most-recently-
    updated facts) is fetched HERE (not by the caller, unlike recent_messages —
    `owner` is already this function's own parameter) and reaches the model via
    `_seeded_system` only, never the cache key: an identical re-prompt still
    cache-HITs regardless of what the owner's profile looks like. Skipped
    entirely on a cache hit (nothing to compose) and never reached by the
    grounded-file path (_generate_modules_grounded doesn't thread an owner
    through at all — document content already dominates there)."""
    last_plan.set(None)
    last_structure.set(None)
    if llm.is_stub_mode():
        from src.stub_templates import pick_structure, pick_system

        # ONB-1 A-flow offline: a clearly-broad prompt yields a deterministic
        # structure (feed + a summarize automation wired via action_type).
        struct = pick_structure(prompt)
        if struct is not None:
            proposal = StructureProposal.model_validate(struct)
            last_plan.set(proposal.plan)
            last_structure.set(proposal)
            return []
        return [ModuleConfig.model_validate(c) for c in pick_system(prompt)]
    from src import semantic_cache

    # Cache: an (almost) identical past prompt is reused for free; a near match
    # becomes the generation seed (so the library grows with real usage).
    mode, cached = semantic_cache.lookup("system", prompt, owner=owner)
    # R-102 (lookup-side chain fix): when there ARE interview answers, never
    # short-circuit on a plain cache hit. A same-owner entry created mid-chain
    # (a parallel tab/device) keys on the raw `prompt`, which does NOT carry the
    # answers — returning it would silently discard the interview. Downgrade the
    # hit to a seed: keep the skeleton benefit, but the model MUST run so the
    # answers are honored.
    if mode == "hit" and exchange_context is not None:
        mode = "seed"
    if mode == "hit" and cached:
        try:
            return [ModuleConfig.model_validate(c) for c in cached]
        except ValidationError:
            pass  # stale/incompatible cache entry → fall through and regenerate
    # R-803: the owner's profile shapes the generation prompt (see docstring
    # above) — fetched here, not by the route, since `owner` is already ours.
    profile_facts = db.profile_list(owner)
    user_message = _seeded_system(
        prompt,
        existing_modules,
        seed_override=cached if mode == "seed" else None,
        exchange_context=exchange_context,
        recent_messages=recent_messages,
        profile_facts=profile_facts,
    )
    try:
        parsed = _generate_validated(
            user_message, DECOMPOSE_SYSTEM_PROMPT, _parse_modules, expect_array=True
        )
    except ClarifyingQuestion:
        if allow_question:
            raise
        # R-102 hard cap: the question budget is spent — never relay another.
        try:
            parsed = _generate_validated(
                user_message + _BUILD_NOW_NOTE,
                DECOMPOSE_SYSTEM_PROMPT,
                _parse_modules,
                expect_array=True,
            )
        except ClarifyingQuestion as e:
            raise RefusalError(_QUESTION_CAP_REFUSAL) from e
    last_plan.set(parsed.plan)
    # SURF/ONB-1: a structure result returns [] and is surfaced via last_structure.
    # It is NEVER stored in the semantic cache (the cache value shape stays a flat
    # config list); returning here before the store guard guarantees that.
    if parsed.structure is not None:
        last_structure.set(parsed.structure)
        return []
    result = parsed.modules
    last = llm.last_call.get()
    # R-403: only a definitely-non-degraded call may seed the cache — an unknown
    # provenance (last is None) is not safe to treat as "not degraded".
    # R-102 (review fix): interview-specialized results must not seed the shared
    # prompt→template library — the key would be the raw prompt but the value is
    # shaped by answers the key doesn't carry (key/value intent mismatch), so a
    # later plain generation of the same prompt would be served the wrong tools.
    if last is not None and not last.degraded and exchange_context is None:
        semantic_cache.store(
            "system", prompt, [m.model_dump(mode="json") for m in result], owner=owner
        )
    return result


def _needs_text_extraction(mime: str) -> bool:
    """Mirrors llm.generate_from_file's provider-x-mime sentinel logic (see its
    docstring) so we can decide, BEFORE the multimodal call, whether this
    provider can read `mime` natively or would just bounce with the "{}"
    sentinel: stub never reads a file natively (every mime needs extraction);
    the openai-compat provider only takes image/* natively (everything else
    needs extraction); gemini reads any mime natively (never needs it)."""
    provider = llm.provider_info()["provider"]
    if provider == "gemini":
        return False
    if provider == "openai":
        return not mime.startswith("image/")
    return True  # stub


def _generate_modules_grounded(
    prompt: str,
    extracted_text: str,
    filename: str | None,
    existing_modules: list[ModuleConfig] | None,
) -> list[ModuleConfig]:
    """R-211 text-extraction grounding path: route the extracted document text
    through the normal TEXT generation call so a provider with no (or limited)
    multimodal input still grounds proposals in the file's actual content.

    Deliberately calls _generate_validated directly instead of generate_modules()
    — generate_modules() looks up/stores the semantic cache (gen_cache), which is
    a shared seed pool that future unrelated prompts draw on (R-403's "seeds the
    library" mechanism). Document content is per-upload and often sensitive
    (R-903 owner-scoping, R-1004 no cross-user leakage) — it must never be
    written into that shared pool, so this path skips cache lookup/store
    entirely and always calls the model.
    """
    label = filename or "the uploaded file"
    user_message = (
        _seeded_system(prompt, existing_modules)
        + f"\n\nDOCUMENT CONTENT (extracted from {label}):\n{extracted_text}"
    )
    parsed = _generate_validated(
        user_message, DECOMPOSE_SYSTEM_PROMPT, _parse_modules, expect_array=True
    )
    # R-211 honesty: _generate_validated ran the TEXT model, but in stub mode (or a
    # cascade that fell all the way to stub) that returns generic keyword templates
    # with no knowledge of the document. Surfacing them as success would claim we
    # read a file we never actually read — refuse honestly instead.
    last = llm.last_call.get()
    if last is None or last.provider == "stub":
        raise RefusalError(_UNREADABLE_FILE_REFUSAL)
    return _flatten(parsed)


def generate_modules_from_file(
    prompt: str,
    data: bytes,
    mime: str,
    existing_modules: list[ModuleConfig] | None = None,
    filename: str | None = None,
    hint: str | None = None,
) -> list[ModuleConfig]:
    """Build tools shaped around an uploaded document/image.

    R-211: documents must ground on EVERY provider, not just Gemini's native
    multimodal path. Before the multimodal call, if this provider can't read
    `mime` natively (see _needs_text_extraction), try server-side text
    extraction (src.services.extract) and — on success — ground generation via
    the normal text path (_generate_modules_grounded). Extraction
    failure/unsupported mime falls through to the native multimodal call below,
    which refuses honestly (via the "{}" sentinel) if that can't read it either
    — we never fabricate a generic keyword template from a file we never
    actually read.

    R-221: `hint` (the sketch snap's interpretation instruction, bounded by the
    route) is folded into the user request the model sees, so the sketch-specific
    guidance reaches BOTH the grounded and native multimodal paths below. Default
    None → every other caller (plain file upload) is unaffected."""
    if hint:
        prompt = f"{prompt}\n\n{hint}"
    if _needs_text_extraction(mime):
        extracted = extract.text_from_file(data, mime, filename=filename)
        if extracted is not None:
            return _generate_modules_grounded(prompt, extracted, filename, existing_modules)

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
            raise RefusalError(_UNREADABLE_FILE_REFUSAL)
        try:
            return _flatten(_parse_modules(raw))
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
