# V2 committed design — runtime

> Produced by a 3-take + adversarial-judge council on 2026-07-06.
> This is the spec the implementation follows verbatim.


# Trus V2 — FORK 1 COMMITTED DESIGN: the always-on per-owner runtime

The per-owner runtime is LOGICAL: one scheduler daemon thread in the single uvicorn process, multiplexing owner-tagged rows in an `automations` table. Isolation is owner-scoped SQL, exactly like every existing store. Three new tables, one thread, one registry dict, one new route file. No new deps, no APScheduler.

---

## 1. db.py — DDL appended to `_SCHEMA` (all-new tables; NO `_migrate` change needed)

```sql
-- V2 always-on runtime (RUN-1..6). owner = the _owner_id key (claimed uid, or
-- dev-only anon sid). DISTINCT from ModuleConfig.automations (client-side
-- intra-module rules) — these are server-side scheduled agents.
CREATE TABLE IF NOT EXISTS automations (
    id            TEXT PRIMARY KEY,                   -- uuid4
    owner         TEXT NOT NULL,
    kind          TEXT NOT NULL,                      -- live_watch | page_digest | tracker_reminder | profile_miner
    name          TEXT NOT NULL,                      -- plain-language label, shown in Pulse
    spec_json     TEXT NOT NULL,                      -- AutomationSpec (discriminated union), quarantined on read
    state_json    TEXT NOT NULL DEFAULT '{}',         -- executor scratch (edge-trigger 'armed' flag etc.)
    schedule_kind TEXT NOT NULL,                      -- 'interval' | 'daily'
    interval_secs INTEGER,                            -- when interval (wire-enforced 300..86400)
    daily_at      TEXT,                               -- when daily: 'HH:MM' UTC (no tz field in this build)
    tier          TEXT NOT NULL DEFAULT 'autonomous', -- 'autonomous' | 'consequential'; stamped from KIND_TIER, never caller-supplied
    trust         INTEGER NOT NULL DEFAULT 1,         -- the dial 0..3 (AUT-3); written ONLY by PATCH route
    enabled       INTEGER NOT NULL DEFAULT 1,
    next_run      TEXT NOT NULL,                      -- UTC ISO (db._now format); due when <= now; ALSO the claim CAS token
    failures      INTEGER NOT NULL DEFAULT 0,         -- consecutive executor EXCEPTIONS; drives backoff
    last_run_at   TEXT,
    last_status   TEXT,                               -- mirror of latest run outcome (list-view cheapness)
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_automations_due   ON automations(enabled, next_run);
CREATE INDEX IF NOT EXISTS idx_automations_owner ON automations(owner, created_at);

-- Activity journal (RUN-2, TAP-1, SEAM-3): one row per run, inserted as
-- 'running' at start and finalized at finish — a mid-run crash stays visible.
CREATE TABLE IF NOT EXISTS automation_runs (
    id            TEXT PRIMARY KEY,
    automation_id TEXT NOT NULL,
    owner         TEXT NOT NULL,                      -- denormalized: owner-scoped WHERE without join
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    outcome       TEXT NOT NULL DEFAULT 'running',    -- running|ok|noop|error|skipped_budget|skipped_conflict|needs_approval
    summary       TEXT NOT NULL DEFAULT '',           -- ONE sanitized human sentence (never raw upstream bodies/URLs)
    detail_json   TEXT                                -- typed refs: {"module_id":..,"value":..,"approval_id":..,"error_class":..}
);
CREATE INDEX IF NOT EXISTS idx_runs_owner      ON automation_runs(owner, started_at);
CREATE INDEX IF NOT EXISTS idx_runs_automation ON automation_runs(automation_id, started_at);

-- Pending approvals (AUT-1/2/4, TAP-2). action_json is a typed ProposedAction,
-- re-validated through Pydantic on approve — never free-form, never markup.
CREATE TABLE IF NOT EXISTS approvals (
    id            TEXT PRIMARY KEY,
    owner         TEXT NOT NULL,
    automation_id TEXT NOT NULL,
    run_id        TEXT NOT NULL,
    description   TEXT NOT NULL,                      -- legible "exactly what will happen"
    action_json   TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',    -- pending|approved|rejected|expired
    created_at    TEXT NOT NULL,
    resolved_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_approvals_owner ON approvals(owner, status, created_at);
```

### db.py helpers (house style: uuid4 ids, `_now()` timestamps, owner-scoped WHERE everywhere except the two scheduler-only calls marked ⚙)

```python
def automation_create(owner, kind, name, spec_json, schedule_kind, interval_secs, daily_at, tier, trust, next_run) -> dict
def automation_list(owner) -> list[sqlite3.Row]
def automation_get(owner, automation_id) -> sqlite3.Row | None
def automation_update(owner, automation_id, *, name=_UNSET, enabled=_UNSET, trust=_UNSET,
                      interval_secs=_UNSET, daily_at=_UNSET, next_run=_UNSET) -> sqlite3.Row | None
    # the existing update_page _UNSET pattern; bumps updated_at; rowcount 0 → None (cross-owner 404)
def automation_delete(owner, automation_id) -> bool
    # also: UPDATE approvals SET status='expired', resolved_at=? WHERE automation_id=? AND owner=? AND status='pending'
    # runs are KEPT (history stays honest; automation_id becomes a tombstone)
⚙ def automations_due(now_iso, limit) -> list[sqlite3.Row]
    # SELECT * FROM automations WHERE enabled=1 AND next_run <= ? ORDER BY next_run LIMIT ?
    # cross-owner by design: the scheduler is the one trusted caller; rows pin their owner
⚙ def automation_claim(automation_id, expected_next_run, new_next_run) -> bool
    # UPDATE automations SET next_run=?, updated_at=? WHERE id=? AND next_run=? AND enabled=1  → rowcount==1
def automation_finish(automation_id, *, failures, last_run_at, last_status, next_run=_UNSET, state_json=_UNSET, enabled=_UNSET) -> None
def run_start(automation_id, owner, started_at) -> str            # INSERT outcome='running', returns run id
def run_finish(run_id, outcome, summary, detail_json, finished_at) -> None
    # then prune: DELETE oldest rows for this owner past _runs_max() — live_cache_set's
    # LIMIT max(0, COUNT-cap) pattern; cap via TRUS_RUNS_MAX (default 500), read fresh
⚙ def runs_finalize_interrupted(now_iso) -> int
    # UPDATE automation_runs SET outcome='error', summary='Interrupted by a server restart.', finished_at=?
    # WHERE outcome='running'  — startup sweep (replaces Take 3's running_since machinery)
def runs_list(owner, limit=50) -> list[sqlite3.Row]               # LEFT JOIN automations for name; newest first
def approval_create(owner, automation_id, run_id, description, action_json) -> dict
def approval_list(owner, status=None) -> list[sqlite3.Row]
def approval_resolve(owner, approval_id, status) -> sqlite3.Row | None
    # UPDATE ... SET status=?, resolved_at=? WHERE id=? AND owner=? AND status='pending'
    # rowcount 0 → None: double-approve is race-safe by construction
```

**`adopt_session_data` (REQUIRED edit, Take 2's catch):** add three UPDATEs so a user claiming an invite keeps their pre-claim runtime:
```python
c.execute("UPDATE automations     SET owner = ? WHERE owner = ?", (user_id, old_owner))
c.execute("UPDATE automation_runs SET owner = ? WHERE owner = ?", (user_id, old_owner))
c.execute("UPDATE approvals       SET owner = ? WHERE owner = ?", (user_id, old_owner))
```
backup.py needs NO change (it snapshots the whole DB file; `_REQUIRED_TABLES` stays `("sessions","users")`).

---

## 2. schema.py — wire models (one additive section at the end)

```python
# ── V2 runtime: server-side automations (distinct from ModuleConfig.automations) ──

class LiveWatchSpec(BaseModel):
    kind: Literal["live_watch"] = "live_watch"
    provider: Literal["weather", "nutrition"]                    # mirrors DataSource.provider exactly
    query: dict[str, str | float] = Field(default_factory=dict)  # reuse DataSource's 10-key validator body
    op: Literal["over", "under"] = "over"
    threshold: float
    module_id: str                                               # write target (owner-checked at create + exec)
    component_id: str                                            # observed value lands in state[component_id]

class PageDigestSpec(BaseModel):
    kind: Literal["page_digest"] = "page_digest"
    page_id: str
    module_id: str                                               # a module holding a Note component
    component_id: str                                            # the Note's id — digest text lands in state[component_id]

class TrackerReminderSpec(BaseModel):
    kind: Literal["tracker_reminder"] = "tracker_reminder"
    module_id: str
    component_id: str                                            # a Tracker component

class ProfileMinerSpec(BaseModel):
    kind: Literal["profile_miner"] = "profile_miner"
    lookback_days: int = Field(default=7, ge=1, le=30)
    max_facts: int = Field(default=3, ge=1, le=5)

AutomationSpec = Annotated[
    LiveWatchSpec | PageDigestSpec | TrackerReminderSpec | ProfileMinerSpec,
    Field(discriminator="kind"),
]

# Tiered actions (AUT-1/2/4): what an executor RETURNS when it wants a side
# effect beyond its own module write. The ENGINE routes it (apply or park) —
# executors never park/apply actions themselves.
class UpdateProfileAction(BaseModel):
    type: Literal["update_profile"] = "update_profile"
    fact_kind: Literal["goal", "preference", "pattern", "fact"] = "pattern"
    text: str = Field(max_length=500)

class SendMessageAction(BaseModel):                              # SEAM-1 stub; AUT-4 hard floor
    type: Literal["send_message"] = "send_message"
    to: str = Field(max_length=200)
    body: str = Field(max_length=2000)

ProposedAction = Annotated[UpdateProfileAction | SendMessageAction, Field(discriminator="type")]

class AutomationCreate(BaseModel):
    name: str = Field(max_length=120)
    spec: AutomationSpec
    schedule_kind: Literal["interval", "daily"] = "interval"
    interval_secs: int | None = Field(default=3600, ge=300, le=86400)
    daily_at: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")  # UTC
    trust: int = Field(default=1, ge=0, le=3)
    # @model_validator: schedule_kind='interval' requires interval_secs; 'daily' requires daily_at

class AutomationPatch(BaseModel):                                # all optional — additive PATCH
    name: str | None = Field(default=None, max_length=120)
    enabled: bool | None = None
    trust: int | None = Field(default=None, ge=0, le=3)          # AUT-3: ONLY this route writes trust
    interval_secs: int | None = Field(default=None, ge=300, le=86400)
    daily_at: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")

class AutomationOut(BaseModel):                                  # owner NEVER serialized out
    id: str; kind: str; name: str
    spec: AutomationSpec | None                                  # None when quarantined-corrupt (still listed, visibly)
    schedule_kind: str; interval_secs: int | None; daily_at: str | None
    tier: Literal["autonomous", "consequential"]; trust: int
    enabled: bool; next_run: str; failures: int
    last_run_at: str | None; last_status: str | None
    created_at: str; updated_at: str

class ActivityEntry(BaseModel):
    id: str; automation_id: str; automation_name: str            # '' when automation deleted (tombstone)
    started_at: str; finished_at: str | None
    outcome: Literal["running", "ok", "noop", "error", "skipped_budget", "skipped_conflict", "needs_approval"]
    summary: str
    detail: dict[str, Any] | None = None

class ApprovalOut(BaseModel):
    id: str; automation_id: str; description: str
    action: ProposedAction
    status: Literal["pending", "approved", "rejected", "expired"]
    created_at: str; resolved_at: str | None

# ONB-1 wiring (additive-optional; existing contracts untouched).
# module_id/page_id fields inside spec MAY be sentinels at proposal time:
#   "$0","$1",… = index into the confirm request's `configs`; "$page" = the insert target page.
class ProposedAutomation(AutomationCreate):
    pass                                                          # same shape; sentinel resolution happens at confirm

# GenerateResponse gains:      proposed_automations: list[ProposedAutomation] | None = None
# InsertModulesRequest gains:  automations: list[ProposedAutomation] | None = None
```

Engine constants (in `services/executors.py`, data not code so AUT-4's floor is declarative):
```python
KIND_TIER  = {"live_watch": "autonomous", "page_digest": "autonomous",
              "tracker_reminder": "autonomous", "profile_miner": "autonomous"}
LLM_KINDS  = frozenset({"page_digest", "profile_miner"})
MIN_TRUST  = {"update_profile": 1}          # action applies autonomously at trust >= this
HARD_FLOOR = frozenset({"send_message"})    # ALWAYS parks, any dial position (AUT-4)
```

---

## 3. File layout

```
backend/src/services/runtime.py     # Scheduler + tick + claim + backoff + budget gate + tier routing
backend/src/services/executors.py   # _EXECUTORS registry, 4 executors, _write_state, apply_action, constants above
backend/src/routes/automations.py   # /api/automations, /api/activity, /api/approvals (one file)
backend/src/schema.py               # §2 models (additive section)
backend/src/db.py                   # §1 DDL + helpers + adopt_session_data edit
backend/src/main.py                 # lifespan start/stop (§4)
backend/src/services/orchestrator.py# generate_modules also emits validated proposed_automations (§6)
backend/src/routes/modules.py       # confirm route resolves sentinels + creates automations (§6)
backend/tests/test_runtime.py  test_executors.py  test_automations_routes.py
frontend/src/components/PulsePanel.tsx ; lib/api.ts ; lib/types.ts ; app/page.tsx (§7)
```

No `budget.py`, no `runtime_schema.py`, no `running_since` column — all judged unnecessary machinery.

---

## 4. Scheduler — `backend/src/services/runtime.py`

Env knobs — ALL read fresh per call via functions, ALL added to conftest `_isolate_llm_env` delenv list; conftest additionally sets `TRUS_RUNTIME=0` so TestClient lifespans never start the thread:

```
TRUS_RUNTIME=1  TRUS_RUNTIME_TICK_SECS=15  TRUS_RUNTIME_BATCH=20
TRUS_RUNTIME_BACKOFF_BASE=60  TRUS_RUNTIME_BACKOFF_CAP=21600
TRUS_RUNTIME_GEN_RATE_MAX=10  TRUS_RUNTIME_GEN_RATE_WINDOW=3600  TRUS_RUNS_MAX=500
```

```python
from src.routes.deps import _RateLimiter          # class reuse only; no import cycle (deps imports db/schema only)

_runtime_limiter = _RateLimiter(max_calls=10, window_secs=3600)   # scheduler's OWN instance —
                                                                  # never eats the interactive _gen_limiter budget

def budget_ok(owner: str, now: datetime) -> bool:
    """Bool-returning twin of routes/deps._check_gen_budget (no HTTPException off-request).
    Rate: per-owner via _runtime_limiter.allow(owner, now=now.timestamp(), max_calls=..., window_secs=...)
    — envs read fresh. Cost: the SAME TRUS_DAILY_COST_CAP_USD against db.owner_cost_today(owner):
    scheduled + interactive spend share ONE owner-day wallet (deliberate)."""

class Scheduler:
    def __init__(self, now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self._now_fn = now_fn                     # injectable clock — tests never sleep
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        self._thread = threading.Thread(target=self._loop, name="trus-runtime", daemon=True)
        self._thread.start()

    def stop(self, join_timeout: float = 5.0):    # graceful shutdown from lifespan
        self._stop.set()
        if self._thread: self._thread.join(timeout=join_timeout)

    def _loop(self):
        db.runs_finalize_interrupted(self._now_fn().isoformat())   # startup sweep: stale 'running' → 'error' (SEAM-3)
        while not self._stop.wait(_tick_secs()):                   # Event.wait IS the sleep → instant shutdown
            if os.environ.get("TRUS_RUNTIME", "1") != "1": continue
            try:
                self.tick(self._now_fn())
            except Exception:                                      # outer belt: a tick bug never kills the runtime
                _log.exception("runtime tick failed")

    def tick(self, now: datetime) -> int:                          # PUBLIC — tests drive this directly, no thread
        ran = 0
        for row in db.automations_due(now.isoformat(), limit=_batch()):
            if self._stop.is_set(): break                          # finish current row, take no new work
            # ADVANCE-BEFORE-EXECUTE with CAS: the UPDATE is the claim. (a) a crash
            # mid-run can never hot-loop or double-fire; (b) restart catch-up needs no
            # extra code; (c) `AND next_run = ?` makes a future second worker lose cleanly.
            nxt = _compute_next_run(row, now)                      # ALWAYS from now — never from the stale slot
            if not db.automation_claim(row["id"], expected_next_run=row["next_run"], new_next_run=nxt.isoformat()):
                continue
            self._run_one(row, now); ran += 1
        return ran

    def _run_one(self, row, now):
        run_id = db.run_start(row["id"], row["owner"], now.isoformat())
        try:
            try:
                spec = _SPEC_ADAPTER.validate_json(row["spec_json"])       # TypeAdapter(AutomationSpec)
            except ValidationError:                                        # quarantine (the _stored_from_row pattern):
                db.automation_finish(row["id"], failures=row["failures"], last_run_at=now.isoformat(),
                                     last_status="error", enabled=0)       # auto-disable, never a tick crash
                db.run_finish(run_id, "error", "Automation config unreadable; paused.", None, now.isoformat())
                return
            if row["kind"] in executors.LLM_KINDS and not budget_ok(row["owner"], now):
                result = executors.ExecResult("skipped_budget", "Held: generation budget reached today.", None, [], None)
            else:
                result = executors.run(row["kind"], row["owner"], spec, json.loads(row["state_json"]), now)
            for action in result.actions:                                  # tier routing (AUT-1/AUT-4)
                self._route_action(row, run_id, action)
            outcome = "needs_approval" if (result.actions and self._parked_any) else result.outcome
            db.run_finish(run_id, outcome, result.summary, json.dumps(result.detail) if result.detail else None,
                          self._now_fn().isoformat())
            db.automation_finish(row["id"], failures=0, last_run_at=now.isoformat(), last_status=outcome,
                                 state_json=json.dumps(result.state) if result.state is not None else _UNSET)
        except Exception as e:                                             # failure isolation (RUN-4)
            _log.exception("automation %s failed", row["id"])              # raw detail → server log ONLY
            failures = row["failures"] + 1
            backoff = min(_backoff_base() * (2 ** failures), _backoff_cap())
            db.run_finish(run_id, "error", "Run failed.",                  # sanitized (F7): class name only
                          json.dumps({"error_class": type(e).__name__}), self._now_fn().isoformat())
            db.automation_finish(row["id"], failures=failures, last_run_at=now.isoformat(), last_status="error",
                                 next_run=(now + timedelta(seconds=backoff)).isoformat())

    def _route_action(self, row, run_id, action) -> None:
        parked = (action.type in executors.HARD_FLOOR
                  or row["tier"] == "consequential"
                  or row["trust"] < executors.MIN_TRUST.get(action.type, 0))
        if parked:
            db.approval_create(row["owner"], row["id"], run_id,
                               executors.describe(action), action.model_dump_json())
        else:
            executors.apply_action(row["owner"], action)

def _compute_next_run(row, now: datetime) -> datetime:
    if row["schedule_kind"] == "interval":
        return now + timedelta(seconds=row["interval_secs"])
    h, m = row["daily_at"].split(":")                              # next HH:MM UTC strictly after now
    cand = now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
    return cand if cand > now else cand + timedelta(days=1)
```

**Policies, stated:**
- **Catch-up (RUN-3): coalesce to exactly one.** Anything due at first tick after a restart runs once; `next_run` is computed from *now*. Three days down ≠ 72 replayed digests. A threshold crossing during downtime is unobserved — documented in LiveWatchSpec's docstring.
- **Locking:** WAL + busy_timeout 5000 (already in `_conn`) handles DB contention; the CAS claim is the only cross-writer coordination needed. No Python-level locks beyond the `_stop` Event.
- **failures increments ONLY on exceptions escaping the executor.** `skipped_budget`, `skipped_conflict`, provider-error payloads, and `noop` never back off (expected conditions, not faults).
- **Backoff:** exponential `base·2^failures`, capped at 6h; overwrites the claim-time `next_run`; reset to 0 on any non-exception finish.

**main.py lifespan (the only main.py change):**
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    sched = None
    if os.environ.get("TRUS_RUNTIME", "1") == "1":
        sched = runtime.Scheduler()
        sched.start()                     # its own thread — never the asyncio event loop
    yield
    if sched: sched.stop()
app.include_router(automations.router, prefix="/api")   # + import in the routes block
```

---

## 5. Executors — `backend/src/services/executors.py`

```python
@dataclass
class ExecResult:
    outcome: Literal["ok", "noop", "error", "skipped_conflict"]
    summary: str                                   # ONE plain-language Pulse line, written for a human
    detail: dict | None = None
    actions: list[ProposedAction] = field(default_factory=list)
    state: dict | None = None                      # persisted back to state_json when not None

Executor = Callable[[str, AutomationSpec, dict, datetime], ExecResult]   # (owner, spec, state, now)
_EXECUTORS: dict[str, Executor] = {...}            # the live_data._FETCHERS pattern — the test seam

def run(kind, owner, spec, state, now) -> ExecResult:
    return _EXECUTORS[kind](owner, spec, state, now)
```

**Shared write rule — `_write_state`, the ONLY way executors touch modules (state-only, never structural, HUMAN WINS):**
```python
def _write_state(owner: str, module_id: str, component_id: str, value: Any) -> bool:
    for _ in range(3):
        mod = db.get_module(owner, module_id)                 # owner-scoped ⇒ foreign id is a miss, not a leak
        if mod is None: return False
        cfg = mod.config.model_copy(deep=True)
        cfg.state[component_id] = value                       # components/layout NEVER touched by the runtime
        try:
            db.update_module(owner, module_id, cfg, expected_rev=mod.rev)   # optimistic, NOT expected_rev=None
            return True
        except db.RevConflict:
            continue                                          # re-read, reapply; after 3 losses → yield
    return False                                              # caller journals outcome='skipped_conflict'
```

1. **`live_watch`** (keyless, no LLM). `payload = live_data.fetch(spec.provider, spec.query, refresh_secs=interval)` — reuses cache + never-raises contract. `payload["error"]` → `ExecResult("error", <honest provider message>)`, no exception, no backoff (SEAM-2). Edge-triggered via state: crossing `(op, threshold)` while `state.get("armed", True)` → `_write_state(module_id, component_id, value)`; summary `"SF is 32.4°C — over your 30° threshold."`; `detail={"module_id":…, "value":…, "alert": True}`; returns `state={"armed": False}`. Back on the safe side → re-arm (`state={"armed": True}`, outcome `noop`, summary `"31→28°C, back under threshold."`). Non-event tick → `noop`, `"Checked: 27.1°C, under 30."` Write lost 3× → `skipped_conflict`.
2. **`page_digest`** (LLM). Loads `db.list_modules(owner, spec.page_id)`; builds the prompt with `orchestrator._module_context(configs)` + `orchestrator._profile_block(db.profile_list(owner))` (PROF-1: profile visibly shapes the digest), capped via the `_cap_composed_prompt` bound; fixed system prompt: *"Summarize this page's current state in ≤80 words of plain text. No markup, no lists."* Calls `llm.generate`; records `db.add_gen_event(owner, kind="automation", …)` so the cost cap self-enforces. Product: `_write_state(spec.module_id, spec.component_id, text)` — the LLM contributes a string VALUE into an existing typed Note; config-not-code holds end to end. `detail={"module_id": spec.module_id}` for the Pulse deep-link (RUN-6/SURF-3 demo). LLMError → `ExecResult("error", deps._llm_error_detail(e))` (already-sanitized line).
3. **`tracker_reminder`** (keyless, no LLM). Reads the Tracker's `state[component_id]["rows"]`; rows whose `done` lacks today's ISO date (today = `now.date().isoformat()` — injected, testable) → `ok`, summary `"Reminder: 2 of 3 habits not done today (water, stretch)."`, `detail={"pending":[…]}`. All done → `noop`. The journal entry IS the product — no messaging channel is faked (SEAM-1 honesty).
4. **`profile_miner`** (LLM). Pulls the owner's recent user-role `messages` (bounded query, `lookback_days`) + `db.profile_list(owner)`; asks `llm.generate` for ≤`max_facts` one-line pattern strings as a JSON list (`orchestrator._strip_codefence` + defensive parse; garbage → `noop` "found nothing new"). Each string → `UpdateProfileAction(fact_kind="pattern", text=…)` in `result.actions`. The ENGINE routes: trust ≥1 → applied; trust 0 → parked as approvals — the keyless exercise of the full AUT-2 lifecycle. Records gen_event.

**Action sink (the single trusted apply path — the approve route calls the same function):**
```python
def describe(action) -> str:
    # update_profile: f'Save to your profile: "{text}"'
    # send_message:   f'Draft a message to {to}. Sending is NOT connected — approving saves a draft only.'

def apply_action(owner: str, action: ProposedAction) -> str:      # returns the journal summary line
    if action.type == "update_profile":
        db.profile_add(owner, action.fact_kind, action.text, source="activity")   # dedup + 50-cap free (PROF-2/3)
        return f'Saved to profile: "{action.text}"'
    if action.type == "send_message":                              # SEAM-1 stub, badged, claims nothing
        return f"Draft only — sending is not connected yet. Draft to {action.to}: {action.body[:120]}"
```
`send_message` is in `HARD_FLOOR`: it parks at every dial position, and even an approve executes only the badged stub (AUT-4 + SEAM-1 in one artifact). No launch executor emits it; it exists for the floor test and the approvals UI — the interface is real, the executor honestly stubbed.

---

## 6. Lifecycle: create / wire-at-confirm / pause / delete / approve

### routes/automations.py — all sync `def` (threadpool); first line `owner = _owner_id(request)`; owner never read from the body

- `GET  /api/automations` → `list[AutomationOut]` (corrupt-spec rows included with `spec=None`, `last_status="error"`, `enabled=false` — visible, not hidden)
- `POST /api/automations` (`AutomationCreate`) → 201 `AutomationOut`. Validates referenced `module_id`/`page_id` are owned via `db.get_module`/`db.get_page` (owner-scoped ⇒ foreign = missing = 404). Stamps `tier = KIND_TIER[spec.kind]` — tier is never caller-supplied. `next_run = _compute_next_run(row, now)`.
- `PATCH /api/automations/{id}` (`AutomationPatch`) → pause/resume (`enabled`), the trust dial, schedule tweaks. Resume recomputes `next_run` from now and resets `failures=0`. **This is the ONLY code path in the repo that writes `trust`** — AUT-3's "system cannot self-raise" is structural (runtime.py/executors.py contain no trust write; asserted by test).
- `DELETE /api/automations/{id}` → 204; runs kept, pending approvals expired (see `automation_delete`).
- `GET  /api/activity?limit=50` → `list[ActivityEntry]`, newest first (TAP-1).
- `GET  /api/approvals?status=pending` → `list[ApprovalOut]`.
- `POST /api/approvals/{id}/approve` → `approval_resolve(owner, id, "approved")`; None → 409 (already resolved / not yours→404 by owner scope). Then parse `action_json` through `ProposedAction` TypeAdapter (typed, never free-form) → `summary = executors.apply_action(owner, action)` → journal a fresh `automation_runs` row `outcome="ok", summary=f"You approved: {summary}"`. Target-module-gone `update_profile` never breaks (profile_add is module-free); a future module-targeting action that misses resolves the approval as `expired`.
- `POST /api/approvals/{id}/reject` → resolve `rejected` + journal `"You rejected: {description}"` (AUT-2: both paths journaled).

### Wired at structure-confirm (ONB-1/ONB-2)

- `orchestrator.generate_modules` additionally asks the structure prompt for automations and emits `proposed_automations: list[ProposedAutomation]` on `GenerateResponse` — each parsed through the discriminated union with the `_sanitize_data_source` posture: **invalid/hallucinated proposals are dropped, never inserted**. Specs may carry sentinels (`"$0"`…`"$n"` for module_id fields, `"$page"` for page_id).
- The insert/confirm route (`routes/modules.py`) accepts `InsertModulesRequest.automations`, inserts modules first, resolves `"$N"` → the Nth freshly-inserted module id and `"$page"` → the target page id, re-validates, then calls the SAME creation function the POST route uses (one code path; unresolvable → dropped and reported in the response). Nothing lands that wasn't previewed; digest target Notes are part of the previewed `configs`, so executors never create modules.
- Manual creation uses `POST /api/automations` (a "wire an automation" affordance can come later; the API is the contract now).

---

## 7. Frontend (the TAP surface)

- **`components/PulsePanel.tsx`** — right-side `role=dialog` aside via `useDialog`, owned by `app/page.tsx` state, mutually exclusive with the other panels (same pattern as ProfilePanel). Two registers, newest first: **Needs your tap** (pending approvals: `description` in plain text; **Approve** is the screen's ONE magenta action; Reject is charcoal-ghost; optimistic UI with rollback + honest inline failure on non-2xx — TAP-2) and **What happened** (activity rows; Geist Mono timestamps/outcomes). Outcome badges (TAP-3): `ok/noop` off-white mono · `needs_approval` magenta dot · `error` muted red · `skipped_*` muted amber. Below the registers: this owner's automations with pause toggle, delete, and the **trust dial** — a 4-stop segmented control labeled `watch only · act quietly · act & tell me · full autonomy`, footnote: *"sending, paying and deleting always ask."* Rows construct in via `lib/assembly.ts` (border→fill→settle); static end-state under `prefers-reduced-motion`.
- **TAP-4 chip**: a Geist Mono chip near the dock on the canvas home — `● 2 need you` — from polling `GET /api/approvals?status=pending` every 60s (no websockets); clicking opens PulsePanel; hidden at zero.
- **`lib/api.ts`** — add to the existing `api` object literal:
  ```ts
  automations: {
    list: () => get<AutomationOut[]>("/api/automations"),
    create: (body: AutomationCreate) => post<AutomationOut>("/api/automations", body),
    patch: (id: string, body: AutomationPatch) => patch<AutomationOut>(`/api/automations/${id}`, body),
    remove: (id: string) => del(`/api/automations/${id}`),
  },
  activity: { list: (limit = 50) => get<ActivityEntry[]>(`/api/activity?limit=${limit}`) },
  approvals: {
    list: (status = "pending") => get<ApprovalOut[]>(`/api/approvals?status=${status}`),
    approve: (id: string) => post<void>(`/api/approvals/${id}/approve`),
    reject: (id: string) => post<void>(`/api/approvals/${id}/reject`),
  },
  ```
- **`lib/types.ts`** — TS mirrors of `AutomationOut`, `AutomationCreate`, `AutomationPatch`, `ActivityEntry`, `ApprovalOut`, `AutomationSpec` (discriminated on `kind`), `ProposedAction` (discriminated on `type`). The confirm flow's request type gains `automations?: ProposedAutomation[]`; the generate response type gains `proposed_automations?: ProposedAutomation[]` and the preview UI lists each as "name — what it will do — tier" (ONB-2).

---

## 8. Test strategy (injectable now, ZERO sleeps)

conftest: `_isolate_llm_env` delenv gains `TRUS_RUNTIME, TRUS_RUNTIME_TICK_SECS, TRUS_RUNTIME_BATCH, TRUS_RUNTIME_BACKOFF_BASE, TRUS_RUNTIME_BACKOFF_CAP, TRUS_RUNTIME_GEN_RATE_MAX, TRUS_RUNTIME_GEN_RATE_WINDOW, TRUS_RUNS_MAX`; then `monkeypatch.setenv("TRUS_RUNTIME", "0")` so no test starts the thread implicitly.

**test_runtime.py** — `Scheduler(now_fn=…)` constructed but `tick(now=fixed_dt)` called directly; executors monkeypatched into `executors._EXECUTORS` (the `_FETCHERS` seam):
1. Due selection: past `next_run` runs; future doesn't; disabled doesn't.
2. RUN-3 restart-coalesce: interval automation 3 intervals stale → exactly ONE run; `next_run == now + interval` (not stale+interval); second `tick(now)` → zero runs (CAS claim proven).
3. Daily `_compute_next_run`: now 07:29 vs `daily_at="07:30"` → today 07:30; now 07:31 → tomorrow.
4. RUN-4 isolation+backoff: raising executor A + healthy B in one tick → B ran; A's run row `error` with `detail.error_class` only (no raw message substring — F7 test); `failures` 1→2→3 doubles `next_run` offset, capped at `TRUS_RUNTIME_BACKOFF_CAP`; success resets to 0.
5. Loop survival: `tick` monkeypatched to raise, `_loop` driven with pre-set stop Event (wait returns immediately) → exception logged, no propagation.
6. Startup sweep: seeded `running` row → `runs_finalize_interrupted` marks it `error`.
7. Spec quarantine: garbage `spec_json` → automation `enabled=0`, run `error` "config unreadable", sibling rows still run, list route still shows it.
8. Budget: `TRUS_DAILY_COST_CAP_USD=0.01` + seeded over-cap gen_events → LLM kind journals `skipped_budget`, `llm.generate` spy asserts ZERO calls, `next_run` advanced, `failures` unchanged; rate limiter driven purely via `allow(owner, now=ts)` with advancing floats; owner A over-cap doesn't block owner B.
9. Tier/trust routing: trust 0 → `update_profile` parks; trust 1 → applies; `send_message` parks at trust 3 (AUT-4 floor); `KIND_TIER` monkeypatched to `consequential` → parks regardless of dial.
10. Shutdown: `stop()` then `tick` → no new work; `start()`/`stop()` real-thread joins within timeout (Event-driven, no sleep).

**test_executors.py**:
- live_watch: `live_data.fetch` monkeypatched — crossing writes state + disarms; second above-threshold tick is `noop` (armed=False); back-under re-arms; provider-error payload → `error` outcome, `failures` NOT incremented; foreign module_id → write refused (owner-scoped miss), honest summary.
- `_write_state`: `update_module` raising RevConflict once → retried and applied on the fresh rev (user's concurrent edit preserved); three times → `False` → `skipped_conflict`, module untouched.
- page_digest: stub-LLM mode writes the Note's `state[component_id]`, records `gen_events kind="automation"`, `detail.module_id` set; profile fact present → prompt contains it (PROF-1, via `llm._last_call`-style capture).
- tracker_reminder: frozen `now` → correct pending subjects; all-done → `noop`.
- profile_miner: stubbed JSON list → actions emitted; applied facts land via `profile_add` (dedup + cap hold, PROF-2); junk output → `noop`.

**test_automations_routes.py** (TestClient, existing anon-session fixtures):
- RUN-5: full two-client Stage-1 pattern — owner A's automations/activity/approvals invisible to B on every route (list empty, id-addressed 404).
- CRUD: create validates owned module/page (foreign → 404); pause/resume recomputes `next_run` and resets failures; trust bounds 0..3; tier in POST body ignored (server-stamped).
- AUT-3 self-raise: after a full tick that emits actions, the `trust` column is unchanged; grep-level assertion that `runtime.py`/`executors.py` never UPDATE trust.
- AUT-2 lifecycle: trust-0 miner run → `needs_approval` run + pending approval; approve → `profile_add` called, resolved, `"You approved:"` run row; reject → nothing applied, journaled; double-approve → 409 (`approval_resolve` rowcount CAS).
- ONB-1: `InsertModulesRequest.automations` with `"$0"`/`"$page"` sentinels → automations bound to real inserted ids; invalid proposal dropped and reported.
- Journal cap: `TRUS_RUNS_MAX=10`, 11 runs → oldest pruned.
- adopt_session_data: anon owner with automation+run+approval claims invite → all three rows re-owned.

**Wire tests** (in existing schema test file): `AutomationSpec`/`ProposedAction` discriminated-union validation; unknown `kind`/`type` rejected; `AutomationCreate` schedule cross-field validator.


## Key decisions (contested points, ruled)

- Skeleton: Take 1 (tables in db._SCHEMA, models in schema.py, runtime.py + executors.py + one routes file, KIND_TIER server-stamped) — it matches house conventions with the fewest moving parts; Takes 2/3 grafted on top.
- Claim protocol: advance-before-execute with Take 2's CAS (`UPDATE … WHERE next_run = ?`) — rejected Take 3's running_since column + stale-takeover as redundant machinery for a single scheduler thread; crash-mid-run visibility comes from the startup sweep finalizing stale 'running' journal rows as 'error' instead.
- Catch-up after restart (RUN-3): coalesce to exactly one run, next_run always computed from now — unanimous across takes; a downtime threshold crossing is unobserved, documented in the spec docstring.
- Module writes: Take 2/3's optimistic expected_rev with 3 retries then yield (skipped_conflict) — rejected Take 1's expected_rev=None because an automation must never win a race against the human's live edit; executors write state only, never components/layout, and never insert modules (rejected Take 3's first-run module creation — targets are created and previewed at confirm time).
- Trust dial: INTEGER 0..3 with per-action MIN_TRUST + HARD_FLOOR set (Takes 2/3) — rejected Take 1's two-state Literal as under-delivering AUT-3's dial and forcing a wire migration later; only the PATCH route writes trust (self-raise impossible structurally).
- Hard floor + honesty seam in one artifact: SendMessageAction exists as a typed action in HARD_FLOOR whose apply is a badged draft-only stub (Take 2) — this is what makes AUT-4 and SEAM-1 testable now, keyless.
- Schedules: interval (300s floor) | daily HH:MM UTC only — rejected Take 2's zoneinfo tz field as gold-plating with a DST bug surface; additive tz column later if users demand local-time digests; rejected Take 3's 60s floor as a hot-loop invitation.
- Budget: bool-returning gate inside runtime.py reusing the _RateLimiter class from routes/deps (no import cycle) with its own limiter instance (TRUS_RUNTIME_GEN_RATE_MAX 10/h per owner) + the SAME shared TRUS_DAILY_COST_CAP_USD wallet via owner_cost_today; every LLM run logs add_gen_event(kind='automation') — rejected Take 2's budget.py extraction as refactor churn.
- Backoff only on exceptions escaping the executor; provider-error payloads, budget skips, and rev-conflict yields journal honestly but never increment failures (Take 2's insight: external flakiness is not the automation being broken).
- Corrupt spec_json: Take 3's quarantine — auto-disable + legible journal row + still visible in the list route, mirroring _stored_from_row; never a tick crash.
- ONB wiring: Take 1's sentinel scheme ('$N' → Nth inserted module, '$page' → target page) on additive-optional GenerateResponse.proposed_automations / InsertModulesRequest.automations, resolved at confirm through the same creation path as manual POST; invalid proposals dropped and reported, nothing lands unshown.
- Required side-fixes surfaced by review: adopt_session_data gains UPDATEs for automations/automation_runs/approvals (Take 2's verified catch — invite-claim would orphan the runtime otherwise); backup.py needs NO change (whole-file snapshot); journal pruned per owner to TRUS_RUNS_MAX=500 via the live_cache_set LIMIT pattern.
- Every run is journaled including noop (RUN-2 says 'every execution'); watcher noise is bounded by edge-triggering (armed flag in state_json) and the prune cap, and the Pulse renders noops in the quiet register.
- Naming: user-facing surface is 'Pulse' (Take 2), tables/models say automations/automation_runs/approvals; the client-side ModuleConfig.automations concept is untouched and never overloaded.
