"""The capture engine entry point: screenshot bytes → a stored-ready layout dict.

Orchestrates CAPTURE (image → IR) → TRANSFORM (IR → ModuleConfig) → assess. The
render-and-verify loop + Gemini escalation are added in Phase 2 (see verify.py /
the plan); this MVP runs the two stages and the capability-coverage gate.
"""

from __future__ import annotations

from src import llm

from . import capture as capture_stage
from . import verify as verify_stage
from .transform import transform_ir


def capture_to_layout(
    data: bytes, mime: str, use_case_hint: str | None = None, *, match_colors: bool = False
) -> dict:
    """Full Phase-1 pipeline. Returns:
        { label, inspired_by, config (dict), capture_meta, confidence,
          ir_digest, structured_text }
    Raises LLMError (model unavailable) / RefusalError (unreadable image), which the
    route maps to 503 / 422 — same contract as the existing importer.
    """
    ir = capture_stage.capture_ir(data, mime, use_case_hint)
    config, report = transform_ir(ir, match_colors=match_colors)
    conf = verify_stage.assess(ir, config)

    vision = llm.vision_info() if llm.vision_available() else {"available": False, "via": "gemini"}
    capture_meta = {
        "app_kind": ir.app_kind,
        "summary": ir.summary,
        "capabilities": ir.capabilities,
        "uncovered": conf["uncovered"],
        "component_types": report["component_types"],
        "component_count": report["component_count"],
        "density": config.density,
        "columns": config.columns,
        "accent": config.accent,
        "theme_opt_in": config.theme_opt_in,
        "radius": config.radius,
        "type_scale": config.type_scale,
        "capture_quality": conf["quality"],
        "vision": vision,
        "source": "screenshot",
    }
    return {
        "label": config.title or ir.app_kind.title() or "Imported layout",
        "inspired_by": "reference screenshot",
        "config": config.model_dump(mode="json"),
        "capture_meta": capture_meta,
        "confidence": conf["value"],
        "ir_digest": ir.to_digest(),
        "structured_text": ir.to_structured_text(),
    }
