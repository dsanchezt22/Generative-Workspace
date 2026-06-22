"""Live, opt-in verification of adapt-to-content generation.

Skipped by default. Runs only when a funded Gemini key is present and
GEMINI_LIVE=1 is set, so CI and normal `pytest` never hit the network or spend
credits. This is the concrete form of "verify live generation": once the user
funds billing, `GEMINI_LIVE=1 pytest tests/test_live_generation.py` proves the
model adapts a module to specifics in the prompt (prefilling stated values),
not just returning a fixed template.
"""

import json
import os

import pytest
from src.services import orchestrator

_LIVE = os.environ.get("GEMINI_LIVE") == "1"

pytestmark = pytest.mark.skipif(
    not _LIVE,
    reason="set GEMINI_LIVE=1 with a funded GEMINI_API_KEY to run live generation checks",
)


def test_budget_prompt_adapts_to_stated_specifics():
    config = orchestrator.generate_module("budget for a 5-day Japan trip, $3000 total")
    blob = json.dumps(config.model_dump()).lower()
    # Adapt-to-content: the concrete amount and/or destination should appear,
    # proving the module was shaped by the request rather than returned generic.
    assert "3000" in blob or "japan" in blob
    assert config.components, "a real module must have components"


def test_off_catalog_prompt_still_generates_something_sensible():
    config = orchestrator.generate_module("track which DJ tracks I've practiced mixing")
    assert config.title
    assert config.components
