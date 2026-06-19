"""Stage 2 — TRANSFORM: IR → Trus ModuleConfig (re-skinned, no feature dropped).

A deterministic type pre-map (open IR `ui_type` → the 31 closed trusted types)
plus an LLM assembly step, then a capability-coverage check that is the
"lose-no-feature" guard.
"""
from __future__ import annotations

import json
import re

from pydantic import TypeAdapter, ValidationError

from src import llm
from src.schema import Component, ModuleConfig
from src.services.orchestrator import _COMPONENT_DOCS, _strip_codefence

from .ir import CaptureIR
from .prompts import transform_system

_COMPONENT_ADAPTER = TypeAdapter(Component)

VALID_ACCENTS = {"amber", "emerald", "sky", "rose", "violet", "coral", "teal", "gold", "blue"}

# Open IR ui_type / role keyword → trusted component type. First substring match wins.
UI_TYPE_MAP: list[tuple[tuple[str, ...], str]] = [
    (("ring", "macro", "dial"), "ring"),
    (("gauge", "meter", "score"), "gauge"),
    (("kanban", "board", "column"), "kanban"),
    (("heatmap", "streak_grid", "contribution"), "heatmap"),
    (("calendar", "month"), "calendar"),
    (("timeline", "itinerary", "agenda"), "timeline"),
    (("sparkline",), "sparkline"),
    (("chart", "graph", "trend", "plot"), "chart"),
    (("checklist", "todo", "task_list"), "checklist"),
    (("tracker", "habit"), "tracker"),
    (("table", "diary", "log", "grid", "ledger", "transactions"), "table"),
    (("kpi", "big_number", "stat", "headline", "balance", "total"), "kpi"),
    (("metric", "aggregate"), "metric"),
    (("rating", "stars"), "rating"),
    (("tags", "labels"), "tags"),
    (("gallery", "images", "thumbnails", "photos"), "gallery"),
    (("note", "textarea", "journal", "description"), "note"),
    (("tabs", "chips", "segmented", "toggle_group"), "choice_chips"),
    (("dropdown", "select", "picker"), "dropdown"),
    (("slider", "range"), "slider"),
    (("checkbox", "toggle", "switch"), "checkbox"),
    (("date", "datetime", "day_picker"), "date"),
    (("color", "swatch"), "color"),
    (("progress", "bar"), "progress_bar"),
    (("section", "header", "group", "card_title"), "section"),
    (("divider", "separator", "rule"), "divider"),
    (("number", "stepper", "count"), "number_input"),
    (("list", "items", "bullets"), "list"),
    (("input", "field", "text", "search"), "text_input"),
]


def map_ui_type(ui_type: str, role: str = "") -> str:
    blob = f"{ui_type} {role}".lower()
    for needles, comp in UI_TYPE_MAP:
        if any(n in blob for n in needles):
            return comp
    return "text_input"


def _coerce(data: object) -> ModuleConfig:
    """Validate a ModuleConfig, dropping individual components that don't validate
    (mirrors studio._coerce) rather than failing wholesale."""
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


def _parse_config(raw: str) -> ModuleConfig:
    cleaned = _strip_codefence(raw)
    data = json.loads(cleaned)
    if isinstance(data, list):
        for item in data:
            try:
                return _coerce(item)
            except (ValidationError, ValueError):
                continue
        raise ValueError("no valid config in array")
    return _coerce(data)


_STOP = {"a", "an", "the", "of", "to", "and", "or", "for", "your", "my", "see", "view",
         "add", "log", "track", "with", "in", "on", "per", "by", "switch", "between"}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOP and len(w) > 2}


def coverage(capabilities: list[str], config: ModuleConfig) -> tuple[float, list[str]]:
    """Fraction of IR capabilities served by ≥1 component (the leave-no-feature signal).
    A capability is covered when a significant word of it appears in some component's
    label/id/columns/options. With no capabilities listed, coverage is 1.0."""
    if not capabilities:
        return 1.0, []
    haystacks: list[set[str]] = []
    for c in config.components:
        text = " ".join(str(x) for x in [
            getattr(c, "label", ""), getattr(c, "id", ""),
            " ".join(getattr(c, "columns", []) or []),
            " ".join(getattr(c, "options", []) or []),
        ])
        haystacks.append(_words(text))
    uncovered: list[str] = []
    for cap in capabilities:
        cap_words = _words(cap)
        if not cap_words:
            continue
        if not any(cap_words & h for h in haystacks):
            uncovered.append(cap)
    covered = len(capabilities) - len(uncovered)
    return (covered / len(capabilities) if capabilities else 1.0), uncovered


def _apply_design_layer(config: ModuleConfig, ir: CaptureIR, match_colors: bool) -> None:
    """Carry the IR's closed-enum design tokens onto the config when the model omitted
    them, and honor the source accent only when match_colors is on."""
    if config.density is None and ir.density_hint() in ("compact", "comfortable", "spacious"):
        config.density = ir.density_hint()
    if config.radius is None and ir.radius_hint() in ("sharp", "rounded", "pill"):
        config.radius = ir.radius_hint()
    if config.type_scale is None and ir.type_scale_hint() in ("compact", "regular", "large"):
        config.type_scale = ir.type_scale_hint()
    if match_colors:
        hint = (ir.accent_hint() or "").lower()
        if hint in VALID_ACCENTS:
            config.accent = hint
        config.theme_opt_in = True
    else:
        config.theme_opt_in = False


def _type_hints(ir: CaptureIR) -> str:
    lines = []
    for n in ir.nodes:
        lines.append(f"- {n.id} ({n.ui_type or n.role or 'element'}) → {map_ui_type(n.ui_type, n.role)}: \"{n.label}\"")
    return "\n".join(lines)


def transform_ir(ir: CaptureIR, *, match_colors: bool = False) -> tuple[ModuleConfig, dict]:
    """Down-map the IR to a Trus ModuleConfig. Returns (config, report)."""
    system = transform_system(_COMPONENT_DOCS)
    theme_note = (
        "The user opted to MATCH SOURCE COLORS: set `theme_opt_in: true` and put the source accent "
        f"('{ir.accent_hint() or 'pick the closest'}') into `accent`."
        if match_colors else
        "Do NOT match source colors: leave `theme_opt_in: false` (Trus brand default)."
    )
    user = (
        f"Captured IR:\n{json.dumps(ir.model_dump(by_alias=True), ensure_ascii=False)[:9000]}\n\n"
        f"Type hints (IR node → trusted component):\n{_type_hints(ir)}\n\n"
        f"Capabilities that MUST each be served by ≥1 component:\n- " + "\n- ".join(ir.capabilities) + "\n\n"
        f"{theme_note}\n\nReturn the ModuleConfig JSON."
    )

    last: Exception | None = None
    config: ModuleConfig | None = None
    for attempt in range(2):
        try:
            raw = llm.generate(
                user if attempt == 0 else user + "\n\nReturn ONLY valid ModuleConfig JSON.",
                system=system, schema=ModuleConfig.model_json_schema(), expect_array=False,
            )
            config = _parse_config(raw)
            break
        except (ValueError, ValidationError, json.JSONDecodeError) as e:
            last = e
    if config is None:
        raise ValueError(f"transform produced no valid ModuleConfig ({last})")

    if not config.title:
        config.title = ir.app_kind.title() or ir.summary[:40] or "Imported layout"
    _apply_design_layer(config, ir, match_colors)

    cov, uncovered = coverage(ir.capabilities, config)
    report = {
        "coverage": cov,
        "uncovered": uncovered,
        "component_types": [c.type for c in config.components],
        "component_count": len(config.components),
    }
    return config, report
