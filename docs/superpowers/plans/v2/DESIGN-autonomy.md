# V2 committed design — autonomy

> Produced by a 3-take + adversarial-judge council on 2026-07-06.
> This is the spec the implementation follows verbatim.


# FORK 2 COMMITTED DESIGN — The Trust Spine (tiered-by-reversibility autonomy, modeled and surfaced)

Skeleton: Take 1 (single frozen action registry, one pure routing function, one panel). Grafted: Take 3's lifecycle hardening (failed-approval status, expires_at in the CAS, activity prune, delete-cascade, disjoint column sets, quarantine) and Take 2's `archive_module` (gives dial 2 a real function), typed `PreviewPayload`, `adopt_session_data` migration, and pending-approval dedupe. Rejected: multi-action automations, the "Routine" rename, `.format(**payload)` templating, LLM-composed copy, SSE/push, per-tier config tables.

Naming rule (the collision guard): the existing `src/schema.py` class `Automation` (client-side intra-module increment/flag rule inside `ModuleConfig.automations`) is untouched and never imported by any new code. No new class is named exactly `Automation`. The new server-side concept uses the table `automations`, db functions `automation_*`, and wire models `AutomationOut`/`AutomationCreate`/`AutomationPatch`. Every new file carries the docstring line: "Server-side runtime automation — NOT schema.Automation (a client-side module rule)."

---

## 1. Backend — new file `backend/src/services/actions.py`

The action-tier taxonomy is a **build invariant living in code**, not DB rows: one frozen registry. Per action type it carries the hard floor, the irreversibility flag, LLM usage, seam-stub flag, and the executor. Copy templates live in `legibility.py` (§5) keyed by the same type names.

```python
"""Action registry + tier routing. Server-side runtime automations — NOT schema.Automation."""
from dataclasses import dataclass
from typing import Callable, Literal

Tier = Literal["autonomous", "consequential"]

@dataclass(frozen=True)
class ActionSpec:
    floor: Tier
    irreversible: bool     # True → AUT-4 hard floor: NEVER autonomous in this build, dial ignored
    uses_llm: bool         # True → _check_gen_budget(owner) MUST pass before execution
    stub: bool             # True → SEAM-1: executor simulates honestly, results badged simulated
    execute: Callable[[str, dict], dict]   # (owner, payload) -> result dict; raises on failure

ACTION_SPECS: dict[str, ActionSpec] = {
    # autonomous floor — reversible, internal to the owner's workspace
    "watch":          ActionSpec("autonomous", False, False, False, _exec_watch),
    "sort":           ActionSpec("autonomous", False, False, False, _exec_sort),
    "track":          ActionSpec("autonomous", False, False, False, _exec_track),
    "summarize":      ActionSpec("autonomous", False, True,  False, _exec_summarize),
    "draft":          ActionSpec("autonomous", False, True,  False, _exec_draft),
    # consequential floor, REVERSIBLE inside Trus — dial 2 may run these autonomously
    "archive_module": ActionSpec("consequential", False, False, False, _exec_archive_module),
    # consequential floor + hard floor (irreversible) — always park, dial can never win
    "send_email":     ActionSpec("consequential", True, False, True,  _exec_send_email_stub),
    "message_human":  ActionSpec("consequential", True, False, True,  _exec_message_stub),
    "pay":            ActionSpec("consequential", True, False, True,  _exec_pay_stub),
    "delete_data":    ActionSpec("consequential", True, False, False, _exec_delete_data),
}

def requires_approval(action_type: str, trust_dial: int) -> bool:
    """The single tier-routing choke point. Pure, time-free."""
    spec = ACTION_SPECS[action_type]        # KeyError → caller journals a refusal (closed world)
    if spec.irreversible:
        return True                          # AUT-4: checked FIRST, dial irrelevant
    if trust_dial <= 0:
        return True                          # dial 0: hold everything
    if spec.floor == "consequential":
        return trust_dial < 2                # dial 2 unlocks reversible-consequential only
    return False                             # autonomous floor at dial >= 1
```

Executors (all sync, all owner-scoped via db functions):
- `_exec_watch` — fetch via the existing `services/live_data.py` seam (provider + query in payload); returns `{"value": ..., "flagged": bool}`.
- `_exec_sort` — reorder items in a target module component's state by `by` field; writes through the existing module-update path (bumps rev, writes module_versions).
- `_exec_track` — append a value row to a target module component's state (same path).
- `_exec_summarize` / `_exec_draft` — LLM via `src/llm.py` (never direct genai), writing the digest/draft into a target Note/Draft component. Callers gate with `_check_gen_budget` first (§3.2, §3.4).
- `_exec_archive_module` — sets `archived=1` on the target module (restorable from ArchivedPanel — that is what makes it reversible).
- `_exec_send_email_stub` / `_exec_message_stub` / `_exec_pay_stub` — SEAM-1 honest stubs: write a record with `{"simulated": True, ...}` into the result, never claim real success.
- `_exec_delete_data` — really deletes the target module/page (owner-scoped), which is why it is irreversible and hard-floored.

An unknown `action_type` never executes anywhere: both the runner and the approve handler catch `KeyError` and journal `failed` ("Unknown action type — refused").

**Trust dial semantics** (`automations.trust_dial`, integer):
| dial | UI label | behavior |
|---|---|---|
| 0 | Ask always | every fire parks as a pending approval, even autonomous-floor actions |
| 1 | Standard (default) | autonomous floor runs immediately; consequential parks |
| 2 | Trusted | consequential-but-reversible (`archive_module`) also runs; irreversible ALWAYS parks |

**AUT-3 "system cannot self-raise", enforced structurally:** `trust_dial` has exactly one writer — the `PATCH /api/automations/{id}` handler (behind `_owner_id`, i.e. a real user request). `db.automation_create` accepts `trust_dial` but hard-clamps it to `min(value, 1)` (an orchestrator/ONB proposal can create at 0 or 1, never 2). The scheduler's bookkeeping UPDATE touches only `next_run_at, last_run_at, failure_count, updated_at` — a column set disjoint from PATCH's (`name, enabled, trust_dial, updated_at`... `updated_at` overlap is harmless), so neither clobbers the other.

## 2. DDL — appended verbatim to `db.py`'s `_SCHEMA` executescript (all new tables → no `_migrate` entries needed; future columns follow the additive ALTER pattern)

```sql
-- V2 trust spine: server-side runtime automations. owner = the _owner_id key
-- (claimed uid, or dev-only anon sid) — R-903. NOT schema.Automation (the
-- client-side intra-module rule): different concept, different store.
CREATE TABLE IF NOT EXISTS automations (
    id            TEXT PRIMARY KEY,
    owner         TEXT NOT NULL,
    name          TEXT NOT NULL,
    action_type   TEXT NOT NULL,             -- key into services/actions.ACTION_SPECS
    action_json   TEXT NOT NULL,             -- typed AutoAction payload (Pydantic-validated, quarantined on read)
    schedule_kind TEXT NOT NULL,             -- 'interval' | 'daily'
    interval_secs INTEGER,                   -- schedule_kind='interval' (>= 60)
    daily_at      TEXT,                      -- 'HH:MM' UTC, schedule_kind='daily'
    trust_dial    INTEGER NOT NULL DEFAULT 1,-- 0 ask-always | 1 standard | 2 trusted
    enabled       INTEGER NOT NULL DEFAULT 1,
    next_run_at   TEXT,                      -- persisted: restarts never re-derive (RUN-3)
    last_run_at   TEXT,
    failure_count INTEGER NOT NULL DEFAULT 0,-- consecutive failures -> runner backoff (RUN-4)
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_automations_owner ON automations(owner, created_at);
CREATE INDEX IF NOT EXISTS idx_automations_due   ON automations(enabled, next_run_at);

-- Parked consequential fires (AUT-2). payload_json is the FROZEN fully-resolved
-- action payload captured at park time — approve executes exactly these bytes,
-- never a re-computation (no preview/execution drift, zero LLM spend on approve).
CREATE TABLE IF NOT EXISTS approvals (
    id            TEXT PRIMARY KEY,
    owner         TEXT NOT NULL,
    automation_id TEXT NOT NULL,
    action_type   TEXT NOT NULL,
    payload_json  TEXT NOT NULL,
    summary       TEXT NOT NULL,             -- template-composed future-tense line, frozen at park
    preview_json  TEXT,                      -- typed PreviewPayload dict or NULL
    status        TEXT NOT NULL DEFAULT 'pending', -- pending|approved|rejected|expired|failed
    expires_at    TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    decided_at    TEXT,
    executed_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_approvals_owner ON approvals(owner, status, created_at);

-- Append-only activity journal (TAP-1). summary composed AT WRITE TIME and
-- stored — history never rewrites when copy templates change. Pruned per owner
-- on write past TRUS_ACTIVITY_MAX (the live_cache cap pattern).
CREATE TABLE IF NOT EXISTS activity (
    id            TEXT PRIMARY KEY,
    owner         TEXT NOT NULL,
    automation_id TEXT,                      -- nullable: rows survive automation deletion
    approval_id   TEXT,
    kind          TEXT NOT NULL,             -- ran|held|approved|rejected|expired|failed
    summary       TEXT NOT NULL,
    detail_json   TEXT,                      -- small typed dict: {module_id?, page_id?, simulated?, error_kind?}
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_activity_owner ON activity(owner, created_at);
```

**New db.py functions** (each opens its own `_conn()`, ids `str(uuid.uuid4())`, timestamps `_now()`, every SELECT/UPDATE/DELETE carries `AND owner = ?`):
- `automation_create(owner, name, action_type, action_json, schedule_kind, interval_secs, daily_at, trust_dial) -> dict` — clamps `trust_dial = min(max(trust_dial, 0), 1)`; computes initial `next_run_at`.
- `automation_list(owner)`, `automation_get(owner, aid)`, `automation_delete(owner, aid) -> bool` — delete also runs, in the same connection/transaction: `UPDATE approvals SET status='expired', decided_at=? WHERE automation_id=? AND owner=? AND status='pending'` and inserts one `expired` activity row per swept approval (never an orphaned-executable approval).
- `automation_patch(owner, aid, *, name=None, enabled=None, trust_dial=None) -> dict | None` — the ONLY `trust_dial` writer; clamps 0..2.
- `automation_mark_run(owner, aid, *, last_run_at, next_run_at, failure_count)` — the scheduler's bookkeeping writer (only these columns + updated_at).
- `approval_create(owner, automation_id, action_type, payload_json, summary, preview_json, expires_at) -> dict` — **dedupe**: if a `pending` row for the same `(owner, automation_id, action_type)` exists, return it unchanged instead of inserting (a dial-0 interval automation cannot flood the list).
- `approval_list_pending(owner)`, `approval_pending_count(owner) -> int` (one indexed COUNT).
- `approval_claim(owner, approval_id, new_status, now) -> dict | None` — the CAS: `UPDATE approvals SET status=?, decided_at=? WHERE id=? AND owner=? AND status='pending' AND expires_at > ?`; rowcount 0 → returns None (caller re-reads to distinguish 404 vs 409).
- `approval_set_failed(owner, approval_id)` / `approval_set_executed(owner, approval_id, executed_at)`.
- `approval_sweep_expired(owner, now) -> list[dict]` — flips overdue pendings to `expired`, returns swept rows so the caller journals them.
- `activity_add(owner, kind, summary, *, automation_id=None, approval_id=None, detail_json=None)` — after insert, prunes oldest rows for this owner beyond `_activity_max()` (`def _activity_max(): return int(os.environ.get("TRUS_ACTIVITY_MAX", "2000"))`).
- `activity_list(owner, limit=50, before: str | None = None)` — newest first, keyset pagination on `created_at`.
- **`adopt_session_data`** gains three lines: `UPDATE automations SET owner=? WHERE owner=?`, same for `approvals` and `activity` — pre-claim automations survive an invite claim (R-902).

Env knobs (functions, never import-time constants; ALL added to conftest's `_isolate_llm_env` delenv list): `TRUS_APPROVAL_TTL_HOURS` (default `"72"`), `TRUS_ACTIVITY_MAX` (default `"2000"`).

## 3. Approvals lifecycle

### 3.1 Park (called by Fork 1's scheduler runner AND by /run)
`services/actions.park(owner, automation, payload_dict, now) -> approval_row`: composes `summary = legibility.will_do(action_type, payload)`, builds `preview_json = legibility.preview(action_type, payload)` (typed PreviewPayload dict), freezes the fully-resolved payload (e.g. the draft body it would send, read NOW), sets `expires_at = now + timedelta(hours=_approval_ttl_hours())`, inserts via `approval_create` (deduped), and journals `activity(kind='held', summary='Holding for your tap: ' + summary)`. Nothing executes.

### 3.2 Approve — executed by the REQUEST HANDLER (sync `def` → threadpool; never the event loop; never the scheduler)
Ruling rationale: the user is waiting at the tap; the payload is frozen (bounded work, zero LLM re-spend for the payload itself); same-request execution makes the HTTP response the truthful outcome with no queue machinery. Revisit (enqueue-for-scheduler) only when a real slow credentialed connector lands.

`POST /api/approvals/{id}/approve` steps:
1. `approval_sweep_expired(owner, now)` + journal swept rows.
2. CAS via `approval_claim(owner, id, 'approved', now)`. None → re-read: row missing → 404; else → **409** `{"detail": {"state": row.status}}` (double-tap in another tab, or expired — the loser learns honestly; executor called at most once, ever).
3. Parse frozen `payload_json` against the typed AutoAction union; unparseable → `approval_set_failed`, journal `failed` ("Couldn't run — stored request was unreadable"), 500 with honest copy (quarantine pattern).
4. `spec = ACTION_SPECS[action_type]`; if `spec.uses_llm`: `_check_gen_budget(owner)` (429 short-circuits BEFORE any spend; approval reverts to nothing-executed via `approval_set_failed` + `failed` journal? No — on 429 the CAS already claimed it: set status back is not allowed; instead journal `failed` with "Paused — usage budget reached" and `approval_set_failed`). 
5. `result = spec.execute(owner, payload)`. Success → `approval_set_executed(...)`, journal `activity(kind='approved', summary=legibility.did_do(action_type, payload, result), detail_json={'simulated': spec.stub, ...})`. Exception → `approval_set_failed(...)`, journal `kind='failed'` with a sanitized reason (the `_llm_error_detail` pattern — raw errors logged server-side, never returned), respond 502 with honest copy.
6. Return `{"approval": ApprovalOut, "activity": ActivityEntry}` so the frontend reconciles optimistically.

### 3.3 Reject
Same CAS to `'rejected'` (404/409 identically), journal `kind='rejected'` (`'You dismissed: ' + summary`), executor unreachable — the CAS is the only gate into execution. Returns the same `{approval, activity}` pair.

### 3.4 The scheduler contract (Fork 1's runner MUST call exactly this seam)
Per due automation: validate `action_json` (corrupt → quarantine: journal `failed`, bump `failure_count`, skip); `requires_approval(action_type, trust_dial)` → True: `park(...)`; False: if `spec.uses_llm` first `_check_gen_budget(owner)` inside try/except HTTPException → on 429 journal `failed` ("Paused — today's usage budget is reached") + back off, zero tokens spent; else `spec.execute(...)` → journal `ran` on success / `failed` + `failure_count += 1` + exponential backoff on exception. **Advance `next_run_at` BEFORE executing** (restart never double-fires). Each tick also runs a global `approval_sweep_expired` pass. Time is injected (`tick(now)`), tests never sleep.

### 3.5 Expiry
Lazy + tick: `GET /api/approvals`, both decision endpoints (sweep-first ordering), and every scheduler tick run the sweep. The approve CAS's `AND expires_at > ?` closes the race window — approve past expiry always 409s even if no sweep ran.

## 4. Wire models & endpoints

### 4.1 Pydantic (new file `backend/src/schema_automations.py` — keeps schema.py's `Automation` visually distant)

```python
class AutoActionWatch(BaseModel):
    type: Literal["watch"] = "watch"
    provider: Literal["weather", "nutrition"]; query: dict[str, str | float] = Field(default_factory=dict)
    module_id: str; component_id: str; op: Literal["over", "under"] | None = None; threshold: float | None = None
class AutoActionSort(BaseModel):
    type: Literal["sort"] = "sort"
    module_id: str; component_id: str; by: Literal["date", "value", "label"] = "date"
class AutoActionTrack(BaseModel):
    type: Literal["track"] = "track"
    module_id: str; component_id: str; metric: str = Field(max_length=100)
class AutoActionSummarize(BaseModel):
    type: Literal["summarize"] = "summarize"
    module_id: str; component_id: str
    source_module_ids: list[str] = Field(default_factory=list, max_length=10)
class AutoActionDraft(BaseModel):
    type: Literal["draft"] = "draft"
    module_id: str; component_id: str
    recipient: str = Field(max_length=200); instruction: str = Field(max_length=500)
class AutoActionArchiveModule(BaseModel):
    type: Literal["archive_module"] = "archive_module"; module_id: str
class AutoActionSendEmail(BaseModel):
    type: Literal["send_email"] = "send_email"
    to: str = Field(max_length=200); subject: str = Field(max_length=200)
    module_id: str | None = None; component_id: str | None = None   # draft-body source
class AutoActionMessageHuman(BaseModel):
    type: Literal["message_human"] = "message_human"
    to: str = Field(max_length=200); text: str = Field(max_length=1000)
class AutoActionPay(BaseModel):
    type: Literal["pay"] = "pay"
    payee: str = Field(max_length=200); amount_usd: float = Field(gt=0, le=10_000)
    memo: str = Field(default="", max_length=200)
class AutoActionDeleteData(BaseModel):
    type: Literal["delete_data"] = "delete_data"
    target: Literal["module", "page"]; target_id: str

AutoAction = Annotated[Union[AutoActionWatch, AutoActionSort, AutoActionTrack,
    AutoActionSummarize, AutoActionDraft, AutoActionArchiveModule, AutoActionSendEmail,
    AutoActionMessageHuman, AutoActionPay, AutoActionDeleteData], Field(discriminator="type")]

class PreviewField(BaseModel):
    label: str; value: str                      # values truncated server-side (<= 200 chars)
class PreviewPayload(BaseModel):                # trusted-render only — flat text, never markup
    title: str
    fields: list[PreviewField] = Field(default_factory=list)   # To / Subject / Amount / Target...
    body: str | None = None                     # e.g. full draft text, mono-rendered
    simulated: bool = False                     # SEAM-1 badge

class AutomationOut(BaseModel):
    id: str; name: str
    action: AutoAction
    action_type: str
    tier_floor: Literal["autonomous", "consequential"]  # from ACTION_SPECS — display only
    irreversible: bool                                  # drives the dial's lock stop
    trust_dial: int; enabled: bool
    schedule_kind: Literal["interval", "daily"]; interval_secs: int | None; daily_at: str | None
    next_run_at: str | None; last_run_at: str | None; created_at: str

class AutomationCreate(BaseModel):
    name: str = Field(max_length=100)
    action: AutoAction
    schedule_kind: Literal["interval", "daily"] = "interval"
    interval_secs: int | None = Field(default=3600, ge=60, le=86400)
    daily_at: str | None = None                         # 'HH:MM' validated
    trust_dial: int = Field(default=1, ge=0, le=1)      # creation can NEVER exceed 1 (AUT-3)

class AutomationPatch(BaseModel):                       # additive-optional; the ONLY dial writer
    name: str | None = Field(default=None, max_length=100)
    enabled: bool | None = None
    trust_dial: int | None = Field(default=None, ge=0, le=2)

class ApprovalOut(BaseModel):
    id: str; automation_id: str; automation_name: str
    action_type: str
    summary: str                                        # future-tense "what it will do"
    preview: PreviewPayload | None
    status: Literal["pending", "approved", "rejected", "expired", "failed"]
    expires_at: str; created_at: str; decided_at: str | None; executed_at: str | None

ActivityKind = Literal["ran", "held", "approved", "rejected", "expired", "failed"]
class ActivityEntry(BaseModel):
    id: str; kind: ActivityKind; summary: str
    automation_id: str | None; automation_name: str | None; approval_id: str | None
    module_id: str | None = None; page_id: str | None = None   # deep-link targets (zoom-to-portal)
    simulated: bool = False
    created_at: str
```

Journal-taxonomy mapping (TAP-3): ran-autonomously → `ran` · needs-tap → `held` · approved+executed → `approved` · rejected → `rejected` · failed → `failed` · TTL passed → `expired`.

### 4.2 Endpoints — new `backend/src/routes/automations.py`; ALL handlers sync `def` (threadpool, never the event loop); first line resolves `owner = _owner_id(request)`; mounted in main.py as `app.include_router(automations.router, prefix="/api")`

| Method & path | Behavior |
|---|---|
| `GET /api/automations` | → `{"automations": [AutomationOut]}`. Corrupt `action_json` rows skipped + logged (quarantine), never 500 the list. |
| `POST /api/automations` | `AutomationCreate` → `AutomationOut` 201. Validates target `module_id`s belong to owner; computes initial `next_run_at`; dial clamped ≤ 1. |
| `PATCH /api/automations/{id}` | `AutomationPatch` → `AutomationOut`. 404 cross-owner. THE only trust_dial writer; 422 outside 0..2 (Pydantic). |
| `DELETE /api/automations/{id}` | → 204. Cascade-expires its pending approvals + journals them (§2). |
| `POST /api/automations/{id}/run` | → `{"activity": ActivityEntry | null, "approval": ApprovalOut | null}`. Run-now through the exact same `requires_approval`/park/execute/budget path as the scheduler. Rate-limited (below). |
| `GET /api/approvals` | → `{"approvals": [ApprovalOut], "pending_count": int}`. Sweeps expiry first; pending only, newest first. |
| `GET /api/approvals/count` | → `{"pending": int}`. One indexed COUNT — the cheap badge poll. |
| `POST /api/approvals/{id}/approve` | §3.2 → `{"approval", "activity"}`; 404 / 409 `{"detail": {"state": ...}}` / 502-honest. |
| `POST /api/approvals/{id}/reject` | §3.3 → `{"approval", "activity"}`. |
| `GET /api/activity?limit=50&before=<iso>` | → `{"entries": [ActivityEntry]}`. Newest first, keyset pagination. |

Rate limiting: approve/reject/run share one module-level `_RateLimiter(60, 300)` instance (the transcribe/live pattern); LLM-backed execution additionally passes `_check_gen_budget(owner)` (already covered in the lifecycle).

Out of scope for this fork, contract stated for the ONB fork: `GenerateResponse` may later gain optional `proposed_automations: list[AutomationCreate]`; `AutomationCreate.trust_dial le=1` already guarantees a model can never propose an elevated dial.

## 5. Legibility copy — new `backend/src/services/legibility.py`

Pure, deterministic, **never LLM** (no spend, no injection vector, golden-string-testable). Explicit per-type functions — NOT `str.format(**payload)` (brace/KeyError hazard). All interpolated user strings truncated to 200 chars via a shared `_trunc()`. Composed once at row-creation time and **frozen** into the `summary` columns — history never rewrites. Failure reasons pass through a sanitizer (the `_llm_error_detail` pattern): internal URLs/response bodies never reach a summary.

`will_do(action_type, payload) -> str` (approval cards, future tense):
- send_email → `Will send an email to {to} — “{subject}” (simulated in this build)`
- message_human → `Will message {to}: “{text[:80]}…” (simulated in this build)`
- pay → `Would pay ${amount_usd:,.2f} to {payee} — simulated in this build`
- delete_data → `Will permanently delete the {target} “{name}” — cannot be undone`
- archive_module → `Will archive “{module_title}” — restorable from Archived`
- dial-0 holds of autonomous types → `Wants to: {did_do-style verb phrase}`

`did_do(action_type, payload, result) -> str` (activity feed, past tense):
- watch → `Checked {label}: {value} — {"flagged" if result["flagged"] else "all quiet"}`
- sort → `Sorted {n} items in “{module_title}” by {by}`
- track → `Tracked {metric}: {value} → “{module_title}”`
- summarize → `Compiled the {name} digest — {n} items`
- draft → `Drafted “{topic}” — waiting in “{module_title}”`
- archive_module → `Archived “{module_title}” — restorable`
- approved rows → `did_do(...)` + ` (simulated)` when `spec.stub`
- held → `Holding for your tap: {will_do(...)}` · rejected → `You dismissed: {summary}` · expired → `Expired unanswered: {summary}` · failed → `“{automation_name}” failed — {safe_reason}`

`preview(action_type, payload) -> PreviewPayload | None`: consequential types only. send_email → fields To/Subject + `body` = resolved draft text, `simulated=True`; pay → fields Payee/Amount/Memo, `simulated=True`; delete_data → fields Target + title "cannot be undone"; archive_module → field Module. Rendered by trusted components as plain text — no markup path exists even for content that transited an LLM.

## 6. Frontend surface

State: `app/page.tsx` gains `const [activityOpen, setActivityOpen] = useState(false)` joining the mutually-exclusive right-aside set (every existing open-handler also calls `setActivityOpen(false)`, and the new open-handler closes the others — the exact existing pattern at page.tsx:679-720). Plus `const [pendingCount, setPendingCount] = useState(0)` polled from `api.approvalCount()` every 30s (interval skipped while `document.hidden`, cleared on unmount) + on window-focus + refreshed after any panel mutation and on panel close.

`lib/api.ts` — add to the `api` object literal: `listAutomations`, `createAutomation`, `patchAutomation(id, patch)`, `deleteAutomation(id)`, `runAutomation(id)`, `listApprovals`, `approvalCount`, `approve(id)`, `reject(id)`, `listActivity(before?)`. `lib/types.ts` — TS mirrors: `AutoAction`, `AutomationOut`, `ApprovalOut`, `PreviewPayload`, `ActivityEntry`, `ActivityKind`.

**Components** (all `"use client"`, charcoal stack, Geist Mono registers):

1. **`components/ActivityPanel.tsx`** — THE trust surface. Right-side `role="dialog"` `aria-modal` aside via `useDialog` (the ProfilePanel pattern verbatim: spread `ref` + `onKeyDown`, `animate-slide-right`, full-width sheet below `sm`). Fetches on open, owns its own list state. Three stacked sections:
   - **NEEDS YOUR TAP** — header register `needs your tap · {n}` (Geist Mono, amber when > 0); `ApprovalCard` list; empty state `nothing waiting on you` (muted).
   - **ACTIVITY** — `ActivityRow` feed, newest first, "load more" via `?before=` cursor.
   - **AUTOMATIONS** (collapsible) — automation management lives HERE (no new nav surface): `AutomationRow` per automation.
   - Rows/cards construct via `lib/assembly.ts` (seed → border → fill → settle); complete reduced-motion static end-state.
   - ApprovalCard / ActivityRow / AutomationRow / TrustDial are separate small files (they carry real logic), ApprovalBadge too.
2. **`components/ApprovalCard.tsx`** — `summary` headline (server string, never client-recomposed); Geist Mono `action_type` chip; expandable typed preview (fields as a definition list, `body` in Geist Mono on the elevated bg, `SIMULATED` chip when `preview.simulated` — the SEAM badge); `EXPIRES IN 2D` muted register. **Approve = the panel's single filled-magenta button**; Dismiss = ghost. One-tap optimistic flow: on tap, buttons swap to an `EXECUTING…` register and the card disables (not removed — honest in-flight); on 200 the card animates out and the returned `ActivityEntry` prepends to the feed (no refetch); on 409 show `already handled` register briefly, remove card, refetch both lists (truthful outcome, not an error toast); on 5xx restore buttons + inline `FAILED — {detail}` danger register (the server journaled `failed`; nothing pretends success).
3. **`components/ActivityRow.tsx`** — status dot + Geist Mono uppercase kind register + summary + relative time. Kind→style const map keyed by `ActivityKind`, muted status colors: `ran` muted green · `held` amber `NEEDS TAP` · `approved` off-white `DONE` (+ ` · SIMULATED` suffix when set) · `rejected` gray `DISMISSED` · `expired` dim gray · `failed` muted red. Rows with `module_id`/`page_id` are buttons that close the panel and fire the existing focus/portal-zoom ("see what it made" — RUN-6).
4. **`components/TrustDial.tsx`** — 3-stop segmented control `Ask always · Standard · Trusted`, bound to `trust_dial`, optimistic PATCH (revert + inline error register on failure). When `automation.irreversible`: the `Trusted` stop still selects (dial 0 vs 1 still matters) but a lock line renders beneath: `🔒 REAL-WORLD ACTIONS (SEND, PAY, DELETE) ALWAYS ASK YOU — HARD FLOOR` — AUT-4 made legible, not hidden. Below the dial one plain-language effect line derived from tier_floor + dial: e.g. `Runs on its own; asks before anything consequential.` / `Asks before doing anything.`
5. **`components/AutomationRow.tsx`** — name, `tier_floor` chip, enabled toggle, schedule register (`every 6h · next 14:02`, Geist Mono), TrustDial, `Run now`, delete (via existing ConfirmDialog).
6. **`components/ApprovalBadge.tsx`** — the can't-miss canvas-home indicator (TAP-4): a fixed pill in the Home top bar. Rendered NOWHERE at 0 (absence is the calm state); at > 0 it is **the home screen's single magenta accent**: filled magenta Geist Mono `2 NEED YOUR TAP`, one scale-settle pulse on count increment (reduced-motion: static), `aria-live="polite"`, click opens ActivityPanel. The Sidebar's Activity item mirrors the count as a small dot+number. (One accent per SCREEN holds: home's accent is the badge; the open panel's accent is Approve.)

## 7. Tests (the DoD hooks — all with injected `now`, no sleeps)

- `tests/test_actions.py`: `requires_approval` truth table over every ACTION_SPECS entry × dial 0/1/2, incl. the parametrized floor test (every `irreversible` spec holds at dial 2 — future types auto-covered) — AUT-1/AUT-4; `archive_module` runs at dial 2, parks at 1; `track` parks at 0, runs at 1; unknown type → refusal journaled.
- `tests/test_approvals.py`: park→approve executes frozen payload (mutate module state between park and approve; executor-spy receives frozen bytes); double-approve → second gets 409, spy called once; reject → executor never called; expiry sweep with injected now flips + journals; approve-past-expiry 409 even without a prior sweep (CAS expires_at guard); LLM-backed approve behind exhausted budget → `failed` journal, LLM spy uncalled; dedupe: two parks of same automation → one pending row; corrupt payload → `failed` status + journal, no 500-crash-loop.
- `tests/test_automations_routes.py`: create clamps dial ≤ 1; PATCH is the only dial writer (scheduler bookkeeping N runs leaves trust_dial byte-identical); PATCH clamps/404s cross-owner; DELETE expires pending approvals; cross-owner isolation — owner B lists empty, approves A's id → 404 AND row still pending AND executor uncalled (RUN-5); handlers are sync def (introspection).
- `tests/test_activity.py`: taxonomy mapping; keyset pagination; per-owner prune at TRUS_ACTIVITY_MAX (owner B untouched); failure summaries never contain base URLs; stub executors mark `simulated`.
- `tests/test_legibility.py`: golden strings per template (frozen copy is permanent — these are load-bearing); truncation; brace-containing user input composes safely.
- Frontend vitest: optimistic approve/reject reducer; kind→register map completeness over `ActivityKind`; a11y — panel passes the useDialog floor, badge is a labeled button.

## 8. Files touched

Backend: `src/services/actions.py` (NEW: ACTION_SPECS, requires_approval, park, executors), `src/services/legibility.py` (NEW: will_do/did_do/preview), `src/schema_automations.py` (NEW: all §4.1 models), `src/db.py` (+3 tables in _SCHEMA, +db functions §2, +3 lines in adopt_session_data), `src/routes/automations.py` (NEW: all §4.2 endpoints), `src/main.py` (+import, +include_router), `tests/test_actions.py`, `tests/test_approvals.py`, `tests/test_automations_routes.py`, `tests/test_activity.py`, `tests/test_legibility.py`, conftest `_isolate_llm_env` (+TRUS_APPROVAL_TTL_HOURS, +TRUS_ACTIVITY_MAX).
Frontend: `src/lib/types.ts`, `src/lib/api.ts`, `src/components/ActivityPanel.tsx`, `ApprovalCard.tsx`, `ActivityRow.tsx`, `TrustDial.tsx`, `AutomationRow.tsx`, `ApprovalBadge.tsx` (all NEW), `src/app/page.tsx` (panel wiring + badge + poll).
Fork-1 seam (stated contract, not built here): the scheduler runner calls `requires_approval` / `park` / `spec.execute` / `_check_gen_budget` / `activity_add` / `automation_mark_run` exactly as §3.4; advances `next_run_at` before executing; sweeps expiry per tick; owns `TRUS_AUTOMATIONS` on/off and tick knobs.

## 9. Known accepted risks
- In-handler approve execution holds a threadpool worker for the executor's duration — acceptable while all irreversible executors are seam stubs; move to enqueue-for-scheduler when a real slow connector lands (changes the approve response contract: accepted vs executed).
- 30s badge polling is the freshness ceiling (a 3am approval shows on next open/focus) — matches the vision's "open it to see what happened"; SSE is a later, separate decision.
- Frozen payload trades freshness for legibility (a draft approved 3 days later sends the 3-day-old body); the 72h TTL bounds it and the approval card's preview IS the frozen content, so what you read is what runs.
- Golden-string tests are load-bearing: frozen summaries make copy bugs permanent in history.


## Key decisions (contested points, ruled)

- Tier location: code, not DB — one frozen ACTION_SPECS registry (Take 1/3 form) over Take 2's ClassVar-per-class, because a single dict is meta-testable in one parametrized floor test and keeps floor/irreversible/uses_llm/stub/executor in one reviewed place.
- Dial 2 must not be a dead control: grafted Take 2's archive_module as the one consequential-but-reversible action (executor = set archived=1, restorable), so 'Trusted' has a real, testable effect today; all wire-crossing verbs stay irreversible=True and always park (AUT-4).
- Naming collision: rejected Take 3's wholesale 'Routine' rename — table `automations`, db `automation_*`, wire models AutomationOut/Create/Patch in a separate schema_automations.py; the only true conflict was the exact class name `Automation`, which no new code uses.
- Approve executes in the request handler (unanimous), sync def in the threadpool, on the FROZEN park-time payload — the response is the truthful outcome, zero cross-thread signaling; enqueue-to-scheduler deferred until a real slow connector exists.
- Approval failure state: Take 3 wins over Take 1 — a failed post-approve execution sets approvals.status='failed' (5-value enum) plus a `failed` journal row, never leaving a dishonest 'approved' row.
- Double-tap / expiry races: single CAS `WHERE status='pending' AND expires_at > ?` (Take 3 + Take 2's risk note) — executor called at most once ever, and approve-past-expiry 409s even if no sweep ran; loser gets 409 {detail:{state}}.
- AUT-3 'system cannot self-raise' enforced structurally: PATCH is the only trust_dial writer; create clamps dial ≤ 1 (Take 3's clamp beats Take 1's reject-entirely — lets ONB propose ask-always automations); scheduler bookkeeping UPDATE touches a disjoint column set.
- Copy: template functions frozen into summary columns at write time, never LLM (unanimous); explicit per-type functions (Take 2/3) over Take 1's .format(**payload) (brace-injection/KeyError hazard); golden-string tests mandatory since frozen copy is permanent.
- Journal taxonomy: ran|held|approved|rejected|expired|failed — Take 2/3's `held` over Take 1's `needs_tap` (matches the status vocabulary).
- Preview: Take 2's typed PreviewPayload (title/fields/body/simulated) over Take 1's flat dict — carries a draft body and the SEAM-1 simulated badge, still trusted-render plain text only.
- Rejected Take 3's multi-action automations (list of ≤5 actions + per-action tier map) as gold-plating — one typed action per automation; also rejected its ONB GenerateResponse extension as out-of-fork (contract noted: create-clamp already blocks model-proposed elevated dials).
- Badge/polling: Take 3's dedicated GET /api/approvals/count (one indexed COUNT, 30s + focus poll) over polling full lists; canvas pill is the home screen's single magenta accent when >0 and absent at 0, Approve is the panel's magenta — one-accent-per-screen holds.
- Hardening grafts kept from Takes 2/3: pending-approval dedupe per (automation, action_type) against dial-0 flooding; per-owner activity prune (TRUS_ACTIVITY_MAX, live_cache pattern); DELETE automation cascade-expires its pending approvals; adopt_session_data adopts all three new tables (only Take 2 caught this); corrupt-row quarantine on list and approve.
- Automation management lives inside ActivityPanel as a collapsible bottom section (unanimous) — did / will-do / controls are one story, no new nav surface; graduates to its own panel later without API change.
- Scheduler boundary: this fork ships the seam (requires_approval/park/execute/budget/journal, advance-next_run_at-before-execute, tick-time expiry sweep) as a stated contract; the tick loop itself is Fork 1's.
