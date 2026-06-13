"""Turn a natural-language prompt into a ModuleConfig.

The orchestrator never returns UI code. It returns a structured ModuleConfig
that the frontend renders with its trusted component library.
"""
from __future__ import annotations

import json

from pydantic import ValidationError

from src import llm
from src.schema import ModuleConfig, RefusalError

SYSTEM_PROMPT = """You are the Trus orchestrator. Your job is to turn a user's intent
into a ModuleConfig — a JSON document that the frontend will render using a fixed
component library. You do not write HTML, CSS, JavaScript, or any UI code.

Available component types (use exactly these "type" values):
- text_input        — short free-text field. Fields: id, label, type, placeholder?
- number_input      — numeric field. Fields: id, label, type, min?, max?, step?, unit?
- checkbox          — boolean toggle. Fields: id, label, type
- slider            — bounded numeric input. Fields: id, label, type, min, max, step, unit?
- progress_bar      — visual progress, optionally bound to another component's value.
                      Fields: id, label, type, max, bound_to? (id of source component)
- list              — a list of free-text items. Fields: id, label, type, item_label, placeholder?

Output JSON ONLY, with this shape:
{
  "title": "Module title (short, human-readable)",
  "components": [ { "id": "stable_snake_case_id", "type": "...", "label": "...", ... }, ... ],
  "state": { "component_id": <prefilled value> },
  "layout": { "x": 0, "y": 0, "width": 360, "height": 320 },
  "summary_component_id": "id of the component that best represents this module at a glance (optional)"
}

Rules:
1. Use only the component types above. No others.
2. ids are stable, snake_case, unique within a module.
3. ADAPT TO THE SPECIFIC REQUEST. This is the whole point — do not emit a generic
   template. Tailor fields, labels, units, and ranges to what the user actually said:
   - Mentioned concrete values? Prefill them in "state" (e.g. a $3000 budget ->
     state has the total set to 3000; a destination "Japan" -> prefilled text).
   - Set slider/number min/max/step to a sensible range for THIS domain.
   - Name fields in the user's terms, not generic ones.
   A starting skeleton may be provided; treat it as a hint to reshape, not a fixed
   answer. Add, drop, rename, and re-bind components to fit the request.
4. Pick a useful skeleton — immediately useful, not over-engineered. Prefer 3-6
   components unless the request clearly needs more.
5. Do not ask questions. Do not narrate. Output the JSON object and nothing else.
6. If the request is illicit, asks for raw code, or is structurally beyond what these
   components can express (e.g. "a 3D game", "embed a movie"), output exactly:
   { "refusal": "<one-sentence reason>" }
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


REFINE_SYSTEM_PROMPT = """You are the Trus orchestrator. Your task is to update an existing
ModuleConfig based on the user's instruction.

The current config is provided as JSON. Apply the requested change and return the updated
ModuleConfig as JSON — same format, same output rules as generation.

Available component types (use exactly these "type" values):
- text_input        — short free-text field. Fields: id, label, type, placeholder?
- number_input      — numeric field. Fields: id, label, type, min?, max?, step?, unit?
- checkbox          — boolean toggle. Fields: id, label, type
- slider            — bounded numeric input. Fields: id, label, type, min, max, step, unit?
- progress_bar      — visual progress. Fields: id, label, type, max, bound_to?
- list              — list of free-text items. Fields: id, label, type, item_label, placeholder?

Rules:
1. Use only the component types above.
2. Preserve state values for any component that survives the edit unchanged (same id, same type).
3. Add, remove, rename, or reorder components to match the instruction.
4. New ids must be snake_case and not collide with surviving ids.
5. Do not narrate. Output the JSON object and nothing else.
6. If the request is illicit or structurally impossible, return:
   { "refusal": "<one-sentence reason>" }
"""


def _seeded_prompt(prompt: str) -> str:
    """Ground generation with the nearest preloaded skeleton, which the model is
    told to adapt to the request. This is "preloaded templates that adjust to the
    user's content" — a seed, not a fixed answer."""
    from src.stub_templates import pick_template

    seed = json.dumps(pick_template(prompt))
    return (
        f"User request: {prompt}\n\n"
        f"Nearest starting skeleton (adapt freely — reshape fields, labels, ranges, "
        f"and prefill state to match the request; do not just return it as-is):\n{seed}\n\n"
        f"Return the adapted ModuleConfig JSON."
    )


def _parse_module_config(raw: str) -> ModuleConfig:
    cleaned = _strip_codefence(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise RefusalError(f"The model returned non-JSON output: {e.msg}") from e
    if isinstance(data, dict) and "refusal" in data:
        raise RefusalError(str(data["refusal"]))
    try:
        return ModuleConfig.model_validate(data)
    except ValidationError as e:
        raise RefusalError(f"The model produced an invalid ModuleConfig: {e.errors()[0]['msg']}") from e


def generate_module(prompt: str) -> ModuleConfig:
    raw = llm.generate(_seeded_prompt(prompt), system=SYSTEM_PROMPT)
    return _parse_module_config(raw)


def refine_module(config: ModuleConfig, prompt: str) -> ModuleConfig:
    # Stub mode: Gemini isn't available, so return the config unchanged.
    # Real refinement requires a valid GEMINI_API_KEY.
    if llm.is_stub_mode():
        return config
    user_message = (
        f"Current ModuleConfig:\n{config.model_dump_json()}\n\n"
        f"User instruction: {prompt}\n\n"
        f"Return the updated ModuleConfig JSON."
    )
    raw = llm.generate(user_message, system=REFINE_SYSTEM_PROMPT)
    return _parse_module_config(raw)
