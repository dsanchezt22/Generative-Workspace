"""The full-fidelity intermediate representation (IR) for a captured screenshot.

A flat, ordered node list (parent-by-id, not deep nesting — far more reliable for
a 7B/VLM to emit as valid JSON in one shot). It captures all five fidelity axes
(layout hierarchy, component semantics, data/content, interactions, style tokens)
so nothing is lost before the lossy down-map to ModuleConfig. The raw image is
never persisted; only a compact digest of this IR is stored.
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class IRNode(BaseModel):
    # Lenient: a vision model may add/omit fields — ignore extras, default the rest.
    model_config = ConfigDict(extra="ignore")

    id: str
    parent: str | None = None
    role: str = ""                       # AX/ARIA open vocab (region, button, list, table, heading…)
    ui_type: str = ""                    # OPEN semantic type — down-mapped later
    label: str = ""
    bbox: list[float] = Field(default_factory=list)   # normalized [x,y,w,h] 0..1
    content: dict[str, Any] = Field(default_factory=dict)  # {text,value,unit,series}
    options: list[str] | None = None     # selects/chips/tabs
    columns: list[str] | None = None     # tables/boards
    state: dict[str, Any] = Field(default_factory=dict)
    interactions: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float = 0.5


class CaptureIR(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_: str = Field(default="trus-capture-ir/1", alias="schema")
    viewport: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    app_kind: str = ""                   # free text → use-case routing + metadata
    tokens: dict[str, Any] = Field(default_factory=dict)   # design-token sidecar
    nodes: list[IRNode] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)  # the "lose-no-feature" contract

    # ---- derived views (never store the raw image) ----

    def node_type_histogram(self) -> dict[str, int]:
        hist: dict[str, int] = {}
        for n in self.nodes:
            key = (n.ui_type or n.role or "unknown").strip().lower()
            hist[key] = hist.get(key, 0) + 1
        return hist

    def accent_hint(self) -> str | None:
        """A single accent-token name hint from the token sidecar, if present."""
        color = self.tokens.get("color") if isinstance(self.tokens, dict) else None
        if isinstance(color, dict):
            for key in ("accent", "accentGuess", "primary"):
                v = color.get(key)
                if isinstance(v, str) and v.strip():
                    return v.strip()
        token_accent = self.tokens.get("accent") if isinstance(self.tokens, dict) else None
        return token_accent.strip() if isinstance(token_accent, str) and token_accent.strip() else None

    def density_hint(self) -> str | None:
        space = self.tokens.get("space") if isinstance(self.tokens, dict) else None
        if isinstance(space, dict):
            d = space.get("density")
            if isinstance(d, str) and d.strip():
                return d.strip().lower()
        return None

    def radius_hint(self) -> str | None:
        r = self.tokens.get("radius") if isinstance(self.tokens, dict) else None
        if isinstance(r, dict):
            s = r.get("scale")
            if isinstance(s, str) and s.strip():
                return s.strip().lower()
        return None

    def type_scale_hint(self) -> str | None:
        t = self.tokens.get("type") if isinstance(self.tokens, dict) else None
        if isinstance(t, dict):
            s = t.get("scale")
            if isinstance(s, str) and s.strip():
                return s.strip().lower()
        return None

    def to_structured_text(self) -> str:
        """A discriminative text document for embedding/seeding (NOT raw pixels)."""
        hist = self.node_type_histogram()
        inventory = ", ".join(f"{k}×{v}" for k, v in sorted(hist.items(), key=lambda x: -x[1]))
        labels = "; ".join(n.label for n in self.nodes if n.label)[:400]
        caps = "; ".join(self.capabilities)
        return (
            f"{self.app_kind or 'app'}. {self.summary}. "
            f"Capabilities: {caps}. Components: {inventory}. "
            f"Labels: {labels}."
        ).strip()

    def to_digest(self) -> dict[str, Any]:
        """Compact, storable summary of the IR — never the image."""
        return {
            "schema": self.schema_,
            "app_kind": self.app_kind,
            "summary": self.summary,
            "capabilities": self.capabilities,
            "node_types": self.node_type_histogram(),
            "node_count": len(self.nodes),
            "tokens": self.tokens,
        }


def _strip_codefence(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[-1] if "\n" in s else s
        if s.endswith("```"):
            s = s[: -3]
        # drop a leading "json" language tag if present
        if s.lstrip().lower().startswith("json"):
            s = s.lstrip()[4:]
    return s.strip()


class IRParseError(ValueError):
    """The vision output couldn't be coerced into a usable CaptureIR."""


def parse_ir(raw: str) -> CaptureIR:
    """Parse a vision model's text into a CaptureIR, lenient about junk/extra keys
    and individual malformed nodes (drop them rather than fail wholesale)."""
    cleaned = _strip_codefence(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise IRParseError(f"non-JSON IR: {e.msg}") from e
    if isinstance(data, list):  # tolerate a bare nodes array
        data = {"nodes": data}
    if not isinstance(data, dict):
        raise IRParseError("IR is not an object")
    # Drop any node that can't validate, keep the rest.
    raw_nodes = data.get("nodes")
    if isinstance(raw_nodes, list):
        good: list[dict] = []
        for n in raw_nodes:
            if not isinstance(n, dict):
                continue
            try:
                IRNode.model_validate(n)
                good.append(n)
            except Exception:
                continue
        data = {**data, "nodes": good}
    try:
        ir = CaptureIR.model_validate(data)
    except Exception as e:
        raise IRParseError(f"invalid IR: {e}") from e
    if not ir.nodes:
        raise IRParseError("IR has no usable nodes")
    return ir
