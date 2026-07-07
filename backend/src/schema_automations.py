"""Wire models for the V2 trust spine.

Server-side runtime automation — NOT schema.Automation (a client-side module
rule). Kept in a separate file so the existing `schema.Automation`
(ModuleConfig.automations, an intra-module increment/flag rule) stays visually
distant and is never imported by any of this code (the naming collision guard).

An automation IS one typed action on a schedule (DESIGN-RECONCILED ruling 1):
the discriminated `AutoAction` union below is the whole shape, keyed by `type`
into services.actions.ACTION_SPECS.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# ── The typed action union (12 types, one executor each) ─────────────────────

_HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


class AutoActionWatch(BaseModel):
    type: Literal["watch"] = "watch"
    provider: Literal["weather", "nutrition"]
    query: dict[str, str | float] = Field(default_factory=dict)
    module_id: str
    component_id: str
    op: Literal["over", "under"] | None = None
    threshold: float | None = None
    # Optional alert landing: a feed/note component that gets an entry on a cross.
    feed_module_id: str | None = None
    feed_component_id: str | None = None

    @field_validator("query")
    @classmethod
    def _bounded_query(cls, v: dict[str, str | float]) -> dict[str, str | float]:
        if len(v) > 10:
            raise ValueError("query may have at most 10 keys")
        return v


class AutoActionSort(BaseModel):
    type: Literal["sort"] = "sort"
    module_id: str
    component_id: str
    by: Literal["date", "value", "label"] = "date"


class AutoActionTrack(BaseModel):
    type: Literal["track"] = "track"
    module_id: str  # target series (chart/sparkline)
    component_id: str
    source_module_id: str
    source_component_id: str
    label: str | None = Field(default=None, max_length=100)


class AutoActionRemind(BaseModel):
    type: Literal["remind"] = "remind"
    module_id: str
    component_id: str
    feed_module_id: str | None = None
    feed_component_id: str | None = None


class AutoActionSummarize(BaseModel):
    type: Literal["summarize"] = "summarize"
    module_id: str
    component_id: str
    source_module_ids: list[str] = Field(default_factory=list, max_length=10)


class AutoActionDraft(BaseModel):
    type: Literal["draft"] = "draft"
    module_id: str
    component_id: str
    recipient: str = Field(max_length=200)
    instruction: str = Field(max_length=500)


class AutoActionLearn(BaseModel):
    type: Literal["learn"] = "learn"
    lookback_days: int = Field(default=7, ge=1, le=30)
    max_facts: int = Field(default=3, ge=1, le=5)


class AutoActionArchiveModule(BaseModel):
    type: Literal["archive_module"] = "archive_module"
    module_id: str


class AutoActionSendEmail(BaseModel):
    type: Literal["send_email"] = "send_email"
    to: str = Field(max_length=200)
    subject: str = Field(max_length=200)
    module_id: str | None = None  # draft-body source component
    component_id: str | None = None


class AutoActionMessageHuman(BaseModel):
    type: Literal["message_human"] = "message_human"
    to: str = Field(max_length=200)
    text: str = Field(max_length=1000)


class AutoActionPay(BaseModel):
    type: Literal["pay"] = "pay"
    payee: str = Field(max_length=200)
    amount_usd: float = Field(gt=0, le=10_000)
    memo: str = Field(default="", max_length=200)


class AutoActionDeleteData(BaseModel):
    type: Literal["delete_data"] = "delete_data"
    target: Literal["module", "page"]
    target_id: str


AutoAction = Annotated[
    AutoActionWatch
    | AutoActionSort
    | AutoActionTrack
    | AutoActionRemind
    | AutoActionSummarize
    | AutoActionDraft
    | AutoActionLearn
    | AutoActionArchiveModule
    | AutoActionSendEmail
    | AutoActionMessageHuman
    | AutoActionPay
    | AutoActionDeleteData,
    Field(discriminator="type"),
]


# ── Approval preview (trusted-render only — flat text, never markup) ─────────


class PreviewField(BaseModel):
    label: str
    value: str  # truncated server-side (<= 200 chars)


class PreviewPayload(BaseModel):
    title: str
    fields: list[PreviewField] = Field(default_factory=list)
    body: str | None = None  # e.g. full draft text, mono-rendered
    simulated: bool = False  # SEAM-1 badge


# ── CRUD wire models ─────────────────────────────────────────────────────────


class AutomationOut(BaseModel):
    id: str
    name: str
    description: str
    page_id: str | None
    action: AutoAction
    action_type: str
    tier_floor: Literal["autonomous", "consequential"]  # from ACTION_SPECS — display only
    irreversible: bool  # drives the dial's lock stop
    trust_dial: int
    enabled: bool
    schedule_kind: Literal["interval", "daily"]
    interval_secs: int | None
    daily_at: str | None
    next_run_at: str | None
    last_run_at: str | None
    last_status: str | None
    created_at: str


class AutomationCreate(BaseModel):
    name: str = Field(max_length=100)
    description: str = ""
    page_id: str | None = None  # validated owner-owned when set
    action: AutoAction
    schedule_kind: Literal["interval", "daily"] = "interval"
    interval_secs: int | None = Field(default=3600, ge=300, le=604800)
    daily_at: str | None = Field(default=None, pattern=_HHMM)  # 'HH:MM' UTC
    trust_dial: int = Field(default=1, ge=0, le=1)  # creation can NEVER exceed 1 (AUT-3)

    @model_validator(mode="after")
    def _schedule_fields(self) -> AutomationCreate:
        if self.schedule_kind == "interval" and self.interval_secs is None:
            raise ValueError("interval schedule requires interval_secs")
        if self.schedule_kind == "daily" and not self.daily_at:
            raise ValueError("daily schedule requires daily_at (HH:MM UTC)")
        return self


class AutomationPatch(BaseModel):  # additive-optional; the ONLY dial writer
    name: str | None = Field(default=None, max_length=100)
    enabled: bool | None = None
    trust_dial: int | None = Field(default=None, ge=0, le=2)


class ApprovalOut(BaseModel):
    id: str
    automation_id: str
    automation_name: str
    action_type: str
    summary: str  # future-tense "what it will do"
    preview: PreviewPayload | None
    status: Literal["pending", "approved", "rejected", "expired", "failed"]
    expires_at: str
    created_at: str
    decided_at: str | None
    executed_at: str | None


ActivityKind = Literal["ran", "held", "approved", "rejected", "expired", "failed", "skipped"]


class ActivityEntry(BaseModel):
    id: str
    kind: ActivityKind
    summary: str
    automation_id: str | None
    automation_name: str | None
    approval_id: str | None
    module_id: str | None = None  # deep-link targets (zoom-to-portal)
    page_id: str | None = None
    simulated: bool = False
    created_at: str
