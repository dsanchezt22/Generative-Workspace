"""Pydantic schemas for the Trus orchestration contract.

The orchestrator emits a ModuleConfig — never raw UI code. The frontend renders
this config using a trusted component library (Part II.4 of the design doc).
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field


class ComponentBase(BaseModel):
    id: str
    label: str


class TextInput(ComponentBase):
    type: Literal["text_input"] = "text_input"
    placeholder: str | None = None


class NumberInput(ComponentBase):
    type: Literal["number_input"] = "number_input"
    min: float | None = None
    max: float | None = None
    step: float | None = None
    unit: str | None = None


class Checkbox(ComponentBase):
    type: Literal["checkbox"] = "checkbox"


class Slider(ComponentBase):
    type: Literal["slider"] = "slider"
    min: float = 0
    max: float = 100
    step: float = 1
    unit: str | None = None


class ProgressBar(ComponentBase):
    type: Literal["progress_bar"] = "progress_bar"
    max: float = 100
    bound_to: str | None = None          # intra-module: reads state[bound_to]
    source_module_id: str | None = None  # cross-module: reads that module's state[bound_to]


class ListField(ComponentBase):
    type: Literal["list"] = "list"
    item_label: str = "Item"
    placeholder: str | None = None


class Metric(ComponentBase):
    """Read-only derived number aggregated across all session modules."""
    type: Literal["metric"] = "metric"
    formula: Literal["sum", "count", "avg", "max", "min"] = "sum"
    source_component_id: str  # aggregate state[this] across modules
    unit: str | None = None


Component = Annotated[
    Union[TextInput, NumberInput, Checkbox, Slider, ProgressBar, ListField, Metric],
    Field(discriminator="type"),
]


class ModuleLayout(BaseModel):
    x: float = 0
    y: float = 0
    width: float = 360
    height: float = 280


class ModuleConfig(BaseModel):
    title: str
    components: list[Component]
    state: dict[str, Any] = Field(default_factory=dict)
    layout: ModuleLayout = Field(default_factory=ModuleLayout)
    summary_component_id: str | None = None


class StoredModule(BaseModel):
    id: str
    config: ModuleConfig
    created_at: str
    updated_at: str
    page_id: str | None = None


class Page(BaseModel):
    id: str
    session_id: str
    name: str
    position: int
    created_at: str


class CreatePageRequest(BaseModel):
    name: str


class RenamePageRequest(BaseModel):
    name: str


class ModuleVersion(BaseModel):
    config: ModuleConfig
    created_at: str


class GenerateRequest(BaseModel):
    prompt: str


class RefineRequest(BaseModel):
    prompt: str


class GenerateResponse(BaseModel):
    module: StoredModule


class PatchRequest(BaseModel):
    config: ModuleConfig


class RefusalError(Exception):
    """Honest refusal: request is out of scope or over-complex (Part II.12)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class LLMError(Exception):
    """The upstream model call failed (quota, network, auth). Distinct from a
    refusal — this is the system being unavailable, not the request being invalid."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason
