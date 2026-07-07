# V2 — THE reconciled architecture (authoritative over the four fork docs)

> The four council docs (DESIGN-runtime, DESIGN-autonomy, DESIGN-surfaces,
> DESIGN-sharing) were produced by independent judges and overlap on the
> automation model. **This document rules every conflict.** Where a fork doc
> disagrees with this one, THIS one wins. Where this doc is silent, the fork
> doc stands.

## Ruling 1 — the automation model is ACTION-CENTRIC (autonomy's shape, runtime's engine)

An automation IS one typed action on a schedule. DESIGN-autonomy's `ACTION_SPECS`
registry + `requires_approval()` + `legibility.py` + frozen-payload approvals +
`activity` journal are the model. DESIGN-runtime's **engine mechanics** are kept
and wired to that model: the `Scheduler` thread (injectable `now_fn`, `Event.wait`
loop, public `tick(now)`), the CAS claim (advance-`next_run_at`-before-execute,
`WHERE next_run_at = ?`), coalescing catch-up after restart, exponential backoff
on executor **exceptions only**, the budget gate (own `_RateLimiter` instance +
the shared `TRUS_DAILY_COST_CAP_USD` wallet via `db.owner_cost_today`, gen_events
`kind="automation"` on every LLM run), corrupt-`action_json` quarantine
(auto-disable + legible journal row), and `_write_state` (rev-retry ×3 → yield).

DESIGN-runtime's spec kinds map into action types: `live_watch`→`watch`,
`page_digest`→`summarize`, `profile_miner`→`learn` (new), `tracker_reminder`→
`remind` (new). DESIGN-runtime's ProposedAction/side-action machinery is **cut**:
executors never emit secondary actions; the whole run either executes or parks.

## Ruling 2 — the single `automations` table

```sql
CREATE TABLE IF NOT EXISTS automations (
    id            TEXT PRIMARY KEY,
    owner         TEXT NOT NULL,
    page_id       TEXT REFERENCES pages(id) ON DELETE CASCADE,  -- the surface it belongs to (nullable)
    name          TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',   -- plain-language "exactly what it does" (ONB-2)
    action_type   TEXT NOT NULL,              -- key into services/actions.ACTION_SPECS
    action_json   TEXT NOT NULL,              -- typed AutoAction (discriminated union), quarantined on read
    state_json    TEXT NOT NULL DEFAULT '{}', -- executor scratch (watch edge-trigger 'armed' flag)
    schedule_kind TEXT NOT NULL,              -- 'interval' | 'daily'
    interval_secs INTEGER,                    -- 300..604800 (weekly allowed)
    daily_at      TEXT,                       -- 'HH:MM' UTC
    trust_dial    INTEGER NOT NULL DEFAULT 1, -- 0 ask-always | 1 standard | 2 trusted; PATCH is the ONLY writer
    enabled       INTEGER NOT NULL DEFAULT 1,
    next_run_at   TEXT,                       -- due when <= now; ALSO the CAS claim token
    last_run_at   TEXT,
    last_status   TEXT,                       -- mirror of latest activity kind for cheap list views
    failure_count INTEGER NOT NULL DEFAULT 0, -- consecutive executor EXCEPTIONS; drives backoff
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_automations_due   ON automations(enabled, next_run_at);
CREATE INDEX IF NOT EXISTS idx_automations_owner ON automations(owner, created_at);
```

DESIGN-surfaces' `status='proposed'` column is **cut** — the runtime lands in this
same build, so a confirmed structure creates real, enabled automations through the
same path as `POST /api/automations`. `approvals` and `activity` tables are
DESIGN-autonomy's verbatim (5-status approvals with frozen payload + preview +
`expires_at`; append-only activity with per-owner prune). No `automation_runs`
table.

## Ruling 3 — the action registry (12 types, every one with a real executor)

| action_type | floor | irreversible | uses_llm | stub | executor product |
|---|---|---|---|---|---|
| watch | autonomous | no | no | no | live_data fetch, edge-triggered threshold via `state_json.armed`, writes value via `_write_state`; optional feed entry on alert |
| sort | autonomous | no | no | no | sorts a list/checklist/table component's items by date/value/label |
| track | autonomous | no | no | no | appends `{date, value}` of a **source** component (number, or count of list/checklist items) into a target chart/sparkline series |
| remind | autonomous | no | no | no | reads a Tracker/checklist; journals which subjects are pending today; appends a feed entry when a feed target is wired |
| summarize | autonomous | no | yes | no | LLM digest of the page's modules (+ profile block — PROF-1) → **appends a Feed entry** (or replaces a Note's text when target is a note) |
| draft | autonomous | no | yes | no | LLM-composed draft (from `instruction`) → Feed entry with badge `draft` |
| learn | autonomous | no | yes | no | mines recent user messages → ≤3 pattern facts via `db.profile_add(source="activity")` (PROF-2) |
| archive_module | consequential | no | no | no | sets archived=1 (restorable) — the dial-2 unlock |
| send_email | consequential | **yes** | no | **yes** | SEAM stub: writes a `simulated` Feed/journal record, never claims sending |
| message_human | consequential | **yes** | no | **yes** | SEAM stub, same |
| pay | consequential | **yes** | no | **yes** | SEAM stub, same |
| delete_data | consequential | **yes** | no | no | REALLY deletes the target module/page (owner-scoped) — that is why it is hard-floored |

`requires_approval(action_type, trust_dial)` is DESIGN-autonomy's pure function,
unchanged. Dial semantics 0/1/2 (Ask always / Standard / Trusted) unchanged.

**Park is zero-spend (deviation from DESIGN-autonomy §3.1):** for `uses_llm`
actions the frozen payload is the action spec (the instruction), NOT pre-composed
content — composing at park would spend tokens on possibly-rejected work. Approve
runs `_check_gen_budget` then composes+executes (autonomy §3.2 step 4 already
covers the budget path). For non-LLM consequential actions the payload is fully
resolved at park (e.g. send_email's body read from its source component NOW), and
the preview shows exactly those frozen bytes.

## Ruling 4 — wire models

- `backend/src/schema_automations.py` (DESIGN-autonomy §4.1) holds the AutoAction
  union + AutomationOut/Create/Patch + ApprovalOut + ActivityEntry + PreviewPayload.
  Additions: `AutoActionLearn {type:"learn", lookback_days: int = 7 (1..30), max_facts: int = 3 (1..5)}`,
  `AutoActionRemind {type:"remind", module_id, component_id, feed_module_id?: str|None, feed_component_id?: str|None}`,
  `AutoActionWatch` gains `feed_module_id?/feed_component_id?` (optional alert
  landing), `AutoActionTrack` becomes `{module_id, component_id (target series),
  source_module_id, source_component_id, label?: str}`. `AutomationOut` gains
  `description: str` and `page_id: str | None`. `AutomationCreate` gains
  `description: str = ""` and `page_id: str | None = None` (validated owner-owned
  when set); `interval_secs` bounds ge=300 le=604800.
- Structure models (DESIGN-surfaces §1) live in `schema.py` with ONE change:
  `StructureAutomation` drops `tier` (fail-closed is now the registry's job) and
  gains `action_type: Literal["watch","summarize","track","remind","draft"]`,
  plus optional fields the composer needs: `provider/query/op/threshold`
  (watch), `instruction` (draft), `source_component_id` (track). At confirm the
  server composes the typed AutoAction from the created pages/modules; an
  automation whose targets can't be resolved is **dropped and reported** in
  `InsertStructureResponse.dropped: list[str]` (names) — never a dangling row.
  Schedule mapping at confirm: hourly→interval 3600 · daily→daily_at "07:00" ·
  weekly→interval 604800. Tier shown in the proposal card is derived client-side
  from action_type via a mirrored registry const; the server derives it from
  ACTION_SPECS. Created-at-confirm automations get trust_dial=1.

## Ruling 5 — journal vocabulary

`ActivityKind = ran | held | approved | rejected | expired | failed | skipped`.
`skipped` covers budget holds and rev-conflict yields (runtime's `skipped_budget`
/`skipped_conflict` → kind `skipped`, the summary says which; `detail_json.reason`
= `"budget" | "conflict"`). A no-event watch tick journals `ran` with an honest
"checked, all quiet" summary. Every scheduler execution journals exactly one row
(RUN-2). `activity.detail_json` may carry `module_id`/`page_id` deep links (RUN-6).

## Ruling 6 — sequencing seams the implementers must respect

- `page_overview` (DESIGN-surfaces §2) fills `last_run_at` from
  `MAX(automations.last_run_at)` per page and counts `automations` per page —
  real data from day one, never null-forever.
- `adopt_session_data` gains FOUR updates: automations, approvals, activity,
  share_links.
- conftest `_isolate_llm_env` gains: TRUS_RUNTIME, TRUS_RUNTIME_TICK_SECS,
  TRUS_RUNTIME_BATCH, TRUS_RUNTIME_BACKOFF_BASE, TRUS_RUNTIME_BACKOFF_CAP,
  TRUS_RUNTIME_GEN_RATE_MAX, TRUS_RUNTIME_GEN_RATE_WINDOW, TRUS_ACTIVITY_MAX,
  TRUS_APPROVAL_TTL_HOURS, TRUS_SHARE_RATE_MAX, TRUS_SHARE_RATE_WINDOW — and
  conftest force-sets `TRUS_RUNTIME=0` so no test starts the thread implicitly.
- main.py lifespan starts/stops the Scheduler behind `TRUS_RUNTIME` (default "1").
- Frontend surface names: component `ActivityPanel.tsx`, UI header **"Pulse"**;
  badge copy `N NEED YOUR TAP`. TrustDial is 3-stop (0/1/2). Everything else per
  DESIGN-autonomy §6, DESIGN-surfaces §5–7, DESIGN-sharing §4.

## Build waves (file-ownership disjoint; gates green at every wave boundary)

1. **A1 backend spine**: db.py (automations/approvals/activity DDL + helpers +
   adopt) · schema_automations.py · services/actions.py · services/legibility.py ·
   services/runtime.py · routes/automations.py · main.py · conftest · full test
   files per DESIGN-autonomy §7 + DESIGN-runtime §8 (merged, minus cut concepts).
   ∥ **F1 Pulse frontend** (ActivityPanel/ApprovalCard/ActivityRow/TrustDial/
   AutomationRow/ApprovalBadge + api/types + page.tsx wiring + vitest).
2. **A2 sharing backend** (db share functions + share_links DDL + schema models +
   routes/share.py + main.py + conftest + test_share.py).
   ∥ **F3 sharing frontend** (SharePanel, SharedSurface, Module "shared" variant,
   lib/crossModule extraction, app/share/[token], api/types, vitest) — F3 starts
   after F1 lands (page.tsx/api.ts single-writer).
3. **A3 surfaces backend** (schema structure models + Feed + orchestrator prompt/
   parse/contextvar/cache-guard/degrade + stub pick_structure + routes: structure
   confirm + overview + db insert_structure/page_overview/pages.accent).
4. **F2 surfaces frontend** (PortalTile, launch zoom, AppFrame, Feed primitive,
   structure proposal card, api/types, portalLayout, vitest).
5. Ethos/motion pass → full sweep → browser drive → closeout.
