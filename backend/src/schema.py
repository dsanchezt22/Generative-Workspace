"""Pydantic schemas for the Trus orchestration contract.

The orchestrator emits a ModuleConfig — never raw UI code. The frontend renders
this config using a trusted component library (Part II.4 of the design doc).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator


class ComponentBase(BaseModel):
    id: str
    label: str
    span: str | None = None  # "full" | "half" — width placement in a 2-column module
    # Visual weight, mapped to existing --accent intensity (no new colour). Lets a
    # screenshot capture mark the "primary action / hero figure". Optional → default
    # render is unchanged for every existing config.
    emphasis: Literal["normal", "primary", "muted"] | None = None


class DataSource(BaseModel):
    """A live external-data binding for a single-value display component
    (R-701/R-704): Metric/Kpi/Ring/Gauge/ProgressBar MAY carry one. The
    frontend's refresh hook calls GET /api/live/{provider} with `query` and
    renders the fetched value with freshness + provenance; a fetch
    failure/staleness never blocks manual editing — the component's own
    state[id] stays the fallback."""

    provider: Literal["weather", "nutrition"]
    query: dict[str, str | float] = Field(default_factory=dict)
    refresh_secs: int = 600
    label: str | None = None

    @field_validator("refresh_secs")
    @classmethod
    def _bounded_refresh_secs(cls, v: int) -> int:
        if not (60 <= v <= 86400):
            raise ValueError("refresh_secs must be between 60 and 86400")
        return v

    @field_validator("query")
    @classmethod
    def _bounded_query(cls, v: dict[str, str | float]) -> dict[str, str | float]:
        # Value types (str/number only) are already enforced by the field's own
        # `dict[str, str | float]` annotation — anything else (list/dict/None)
        # fails pydantic's own coercion before this validator runs. Only the key
        # count needs manual enforcement (pydantic has no built-in dict-length bound).
        if len(v) > 10:
            raise ValueError("query may have at most 10 keys")
        return v


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
    bound_to: str | None = None  # intra-module: reads state[bound_to]
    source_module_id: str | None = None  # cross-module: reads that module's state[bound_to]
    data_source: DataSource | None = None  # R-701/R-704: optional live-value binding


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
    data_source: DataSource | None = None  # R-701/R-704: optional live-value binding


class Rating(ComponentBase):
    """Star/number rating. state[id] = number."""

    type: Literal["rating"] = "rating"
    max: int = 5


class Tags(ComponentBase):
    """Free-form chip labels. state[id] = list[str]."""

    type: Literal["tags"] = "tags"
    placeholder: str | None = None


class Kpi(ComponentBase):
    """A single headline figure with a label. state[id] = number."""

    type: Literal["kpi"] = "kpi"
    unit: str | None = None
    data_source: DataSource | None = None  # R-701/R-704: optional live-value binding


class DatePicker(ComponentBase):
    """A date (or date-time). state[id] = ISO string."""

    type: Literal["date"] = "date"
    include_time: bool = False


class Table(ComponentBase):
    """Structured grid. state[id] = list[list[str]] (rows of cells)."""

    type: Literal["table"] = "table"
    columns: list[str] = Field(default_factory=lambda: ["Item", "Value"])


class Calendar(ComponentBase):
    """Month calendar. state[id] = list[str] of ISO dates (marked days)."""

    type: Literal["calendar"] = "calendar"


class Chart(ComponentBase):
    """Chart drawn from a data series. state[id] = list[{label,value}]."""

    type: Literal["chart"] = "chart"
    chart_type: Literal["bar", "line", "area", "pie"] = "bar"
    unit: str | None = None


class Dropdown(ComponentBase):
    """Pick one from set options. state[id] = selected string."""

    type: Literal["dropdown"] = "dropdown"
    options: list[str] = Field(default_factory=list)


class ChoiceChips(ComponentBase):
    """Pick one option shown as chips. state[id] = selected string."""

    type: Literal["choice_chips"] = "choice_chips"
    options: list[str] = Field(default_factory=list)


class ColorField(ComponentBase):
    """A colour swatch. state[id] = hex string."""

    type: Literal["color"] = "color"


class Sparkline(ComponentBase):
    """Tiny inline trend line. state[id] = list[number]."""

    type: Literal["sparkline"] = "sparkline"
    unit: str | None = None


class Ring(ComponentBase):
    """Circular progress ring. state[id] (or bound_to) = number against max."""

    type: Literal["ring"] = "ring"
    max: float = 100
    bound_to: str | None = None
    data_source: DataSource | None = None  # R-701/R-704: optional live-value binding


class Timeline(ComponentBase):
    """Chronological event strip. state[id] = list[{date,label}]."""

    type: Literal["timeline"] = "timeline"


class Button(ComponentBase):
    """An action button. action: calculator|timer open a utility; increment +1s a
    number field (target); add_item appends to a list field (target)."""

    type: Literal["button"] = "button"
    action: Literal["calculator", "timer", "increment", "add_item"] = "calculator"
    target: str | None = None


class Section(ComponentBase):
    """A labelled section header to group fields — gives a tool structure."""

    type: Literal["section"] = "section"


class Divider(ComponentBase):
    """A thin horizontal rule. label optional."""

    type: Literal["divider"] = "divider"
    label: str = ""


class Kanban(ComponentBase):
    """A board with named columns of cards. state[id] = {column: list[str]}."""

    type: Literal["kanban"] = "kanban"
    columns: list[str] = Field(default_factory=lambda: ["To do", "Doing", "Done"])


class Heatmap(ComponentBase):
    """A calendar contribution/streak grid. state[id] = {dateISO: level 0-4}."""

    type: Literal["heatmap"] = "heatmap"
    unit: str | None = None


class Gauge(ComponentBase):
    """A radial meter. state[id] (or bound_to) = number against max."""

    type: Literal["gauge"] = "gauge"
    min: float = 0
    max: float = 100
    unit: str | None = None
    data_source: DataSource | None = None  # R-701/R-704: optional live-value binding


class Checklist(ComponentBase):
    """Checkable items with a progress bar. state[id] = list[{text,done}]."""

    type: Literal["checklist"] = "checklist"


class Gallery(ComponentBase):
    """A grid of image thumbnails. state[id] = list[url]."""

    type: Literal["gallery"] = "gallery"


class Note(ComponentBase):
    """A multi-line free-text note. state[id] = string."""

    type: Literal["note"] = "note"
    placeholder: str | None = None


class Tracker(ComponentBase):
    """Multi-subject tracker: each row/subject has its OWN streak + completion,
    and the 'today' tick resets each period. state[id] = {rows:[{name, done:[ISO]}]}.
    Use for habit trackers, daily routines, per-person/per-item check-ins."""

    type: Literal["tracker"] = "tracker"
    period: Literal["day", "week"] = "day"
    goal: int | None = None  # optional per-subject target (e.g. 30-day goal)


Component = Annotated[
    TextInput
    | NumberInput
    | Checkbox
    | Slider
    | ProgressBar
    | ListField
    | Metric
    | Rating
    | Tags
    | Kpi
    | DatePicker
    | Table
    | Calendar
    | Chart
    | Dropdown
    | ChoiceChips
    | ColorField
    | Sparkline
    | Ring
    | Timeline
    | Button
    | Section
    | Divider
    | Kanban
    | Heatmap
    | Gauge
    | Checklist
    | Gallery
    | Note
    | Tracker,
    Field(discriminator="type"),
]


class ModuleLayout(BaseModel):
    x: float = 0
    y: float = 0
    width: float = 360
    height: float = 280


class Automation(BaseModel):
    """A plain-language rule: when <when_id> <when> <when_value?>, then <then> <then_id>."""

    id: str
    when_id: str
    when: Literal["checked", "over", "under", "changes"] = "checked"
    when_value: float | None = None
    then: Literal["increment", "flag"] = "increment"
    then_id: str
    then_value: float | None = None


class ModuleConfig(BaseModel):
    title: str
    components: list[Component]
    state: dict[str, Any] = Field(default_factory=dict)
    layout: ModuleLayout = Field(default_factory=ModuleLayout)
    summary_component_id: str | None = None
    automations: list[Automation] = Field(default_factory=list)
    columns: int = 1  # 1 = single stack; 2 = two-column grid layout
    # Visual identity so each generated tool looks distinct, not a clone of the
    # last. `icon` is a single emoji; `accent` is one of the trusted palette
    # tokens (see frontend lib/theme.ts). Both optional: the frontend derives a
    # deterministic fallback from the title when missing, so no two pods read the
    # same even if the model omits them.
    icon: str | None = None
    accent: str | None = None
    density: str | None = None
    # Constrained design layer (closed-enum, no raw CSS) — raises re-skin fidelity for
    # screenshot captures while preserving config-not-code. All Optional so existing
    # configs and normal generation render identically.
    radius: Literal["sharp", "rounded", "pill"] | None = None  # corner scale token
    type_scale: Literal["compact", "regular", "large"] | None = None  # font scale token
    # When True, the captured `accent` hue is honored by the renderer (a themed import);
    # otherwise the brand-blue ethos default applies. Default False → no visual change.
    theme_opt_in: bool = False


class StoredModule(BaseModel):
    id: str
    config: ModuleConfig
    created_at: str
    updated_at: str
    page_id: str | None = None
    archived: bool = False
    rev: int = 0


# ── Per-surface read-only sharing (SHARE-1..3) ──
# Whitelist by construction — NEVER reuse Page (serializes session_id/parent_id/
# position/portal_*/view_*) or StoredModule (serializes page_id/rev/archived).


class ShareStatus(BaseModel):
    active: bool
    token: str | None = None
    created_at: str | None = None


class SharedPage(BaseModel):
    name: str
    icon: str | None = None


class SharedModule(BaseModel):
    id: str  # needed: React keys + same-page cross-module bindings
    config: ModuleConfig  # data_source stripped by the route before construction
    updated_at: str  # the "as of" honesty stamp


class SharedPageResponse(BaseModel):
    page: SharedPage
    modules: list[SharedModule]


class Page(BaseModel):
    id: str
    session_id: str
    name: str
    icon: str | None = None
    parent_id: str | None = None
    position: int
    # R-502/R-504: a child page's portal placement (world coords) on its parent's
    # canvas. Null until the tile is dragged — the frontend then auto-places it.
    portal_x: float | None = None
    portal_y: float | None = None
    # R-504 completion: this page's own saved viewport (pan offset + zoom), so a
    # user's view resumes across devices. Null until the view is first saved.
    view_x: float | None = None
    view_y: float | None = None
    view_zoom: float | None = None
    created_at: str


class CreatePageRequest(BaseModel):
    name: str
    icon: str | None = None
    parent_id: str | None = None


class RenamePageRequest(BaseModel):
    name: str | None = None
    icon: str | None = None
    parent_id: str | None = None
    # R-504: dragging a child's portal tile persists its placement here.
    portal_x: float | None = None
    portal_y: float | None = None
    # R-504 completion: the page's own viewport (pan/zoom), saved debounced.
    view_x: float | None = None
    view_y: float | None = None
    view_zoom: float | None = None


class ReorderPagesRequest(BaseModel):
    ordered_ids: list[str]


class ModuleVersion(BaseModel):
    config: ModuleConfig
    created_at: str


class Message(BaseModel):
    """One turn in a page's conversation log (the prompts that shaped it)."""

    id: str
    role: Literal["user", "assistant"]
    text: str
    module_id: str | None = None
    page_id: str | None = None
    created_at: str


class Snapshot(BaseModel):
    """A point-in-time capture of a page's modules (read-only until restored)."""

    id: str
    page_id: str | None = None
    label: str
    module_count: int = 0
    created_at: str


class CreateSnapshotRequest(BaseModel):
    label: str | None = None


class ExchangeTurn(BaseModel):
    """One question/answer pair from a multi-turn clarifying interview (R-102).
    The route folds the accumulated exchange into the text the MODEL sees, so a
    second (or third, or fourth) question never loses earlier answers."""

    question: str = Field(max_length=500)
    answer: str = Field(max_length=500)


class GenerateRequest(BaseModel):
    prompt: str
    # R-102: prior Q/A pairs in this clarifying interview, oldest first. Capped
    # at 6 turns (the route enforces the actual build-now cap at 4 answered).
    exchange: list[ExchangeTurn] | None = Field(default=None, max_length=6)
    # R-102 "Just build it": a HARD skip. When true the route forces
    # allow_question=False so the model never re-questions — it builds its best
    # interpretation now (or refuses honestly), never relaying another question.
    build_now: bool = False


class RefineRequest(BaseModel):
    prompt: str


class GenerateResponse(BaseModel):
    module: StoredModule | None = None  # first module (back-compat)
    modules: list[StoredModule] | None = None  # full system when decomposed
    previews: list[ModuleConfig] | None = None  # proposed (not yet persisted) tools
    question: str | None = None  # set when the orchestrator needs clarification
    degraded: bool = False  # true when the result came from a cascade fallback
    # R-103/R-301: a one-paragraph rationale for what was built and why — set
    # only on a fresh (non-stub, non-cached) model response; None otherwise so
    # the app never fabricates a rationale it didn't actually generate.
    plan: str | None = None


class InsertModulesRequest(BaseModel):
    configs: list[ModuleConfig]
    prompt: str | None = None
    # R-802: the clarifying interview that produced these accepted tools, if any.
    # Accretion fires HERE (on a confirmed insert), not on preview/generate — so a
    # discarded draft never enters the profile. Same shape/cap as GenerateRequest.
    exchange: list[ExchangeTurn] | None = Field(default=None, max_length=6)


class PatchRequest(BaseModel):
    config: ModuleConfig
    rev: int | None = None


class UserProfileEntry(BaseModel):
    """One fact the "remembers you" profile store holds about an owner (R-801).
    Always owner-scoped in the DB layer — this is just the wire shape."""

    id: str
    owner: str
    kind: Literal["goal", "preference", "pattern", "fact"]
    text: str
    source: Literal["interview", "prompt", "activity", "manual"]
    created_at: str
    updated_at: str


class ProfileAddRequest(BaseModel):
    """Manual "add a fact" (POST /api/profile). source is always "manual" —
    the route sets it; it isn't caller-controlled."""

    kind: Literal["goal", "preference", "pattern", "fact"]
    text: str = Field(max_length=500)


class ProfileUpdateRequest(BaseModel):
    text: str = Field(max_length=500)


class RefusalError(Exception):
    """Honest refusal: request is out of scope or over-complex (Part II.12)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class ClarifyingQuestion(Exception):
    """The orchestrator needs one more piece of info before generating."""

    def __init__(self, question: str):
        super().__init__(question)
        self.question = question


class LLMError(Exception):
    """The upstream model call failed (quota, network, auth). Distinct from a
    refusal — this is the system being unavailable, not the request being invalid."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason
