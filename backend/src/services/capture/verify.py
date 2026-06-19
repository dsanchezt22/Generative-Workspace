"""Confidence + (Phase 2) render-and-verify.

MVP: an objective confidence from capability coverage — the load-bearing
"lose-no-feature" signal — plus a hard fail when a capability is dropped or no
components were produced. The render/SSIM/VLM-match signals are added in Phase 2
behind TRUS_CAPTURE_VERIFY (see the plan); the weighting is kept here so the
Phase-2 upgrade is a localized change.
"""
from __future__ import annotations

import os

from src.schema import ModuleConfig

from .ir import CaptureIR
from .transform import coverage


def conf_threshold() -> float:
    try:
        return float(os.environ.get("TRUS_CAPTURE_CONF_THRESHOLD", "0.62"))
    except ValueError:
        return 0.62


def verify_enabled() -> bool:
    return os.environ.get("TRUS_CAPTURE_VERIFY", "off").strip().lower() in ("on", "1", "true", "yes")


def assess(ir: CaptureIR, config: ModuleConfig) -> dict:
    """Score a transformed config against the captured IR (no render in MVP).

    Returns {value, element_coverage, uncovered, hard_fail, quality}.
    `hard_fail` is True when a capability was dropped or zero components produced —
    that forces a repair/escalation regardless of the numeric score.
    """
    element_coverage, uncovered = coverage(ir.capabilities, config)
    no_components = len(config.components) == 0
    hard_fail = no_components or element_coverage < 1.0

    # MVP value: coverage dominates; a small base credits a valid, non-empty config.
    value = 0.0 if no_components else round(0.15 + 0.85 * element_coverage, 4)
    quality = "high" if (element_coverage >= 1.0 and not no_components) else (
        "low" if value < conf_threshold() else "medium"
    )
    return {
        "value": value,
        "element_coverage": element_coverage,
        "uncovered": uncovered,
        "hard_fail": hard_fail,
        "quality": quality,
    }
