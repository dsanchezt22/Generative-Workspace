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
  "state": {},
  "layout": { "x": 0, "y": 0, "width": 360, "height": 320 },
  "summary_component_id": "id of the component that best represents this module at a glance (optional)"
}

Rules:
1. Use only the component types above. No others.
2. ids are stable, snake_case, unique within a module.
3. Pick a useful skeleton — enough to be immediately useful, but not over-engineered.
   Prefer 3-6 components. If the user wants more, they will say so.
4. Do not ask questions. Do not narrate. Output the JSON object and nothing else.
5. If the request is illicit, asks for raw code, or is structurally beyond what these
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


def generate_module(prompt: str) -> ModuleConfig:
    raw = llm.generate(prompt, system=SYSTEM_PROMPT)
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
