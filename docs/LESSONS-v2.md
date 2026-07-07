# LESSONS — V2 build scratchpad

One lesson per entry, one-line summary first. Real component-tree facts, corrections,
confirmed approaches and why. Read before big moves. Don't duplicate what the repo
already records (STATUS.md, plans, CLAUDE.md).

---

- **Toolchain on this machine lives outside PATH defaults.** System python is 3.9;
  the project venv is `.venv/` (Python 3.12 via `uv venv`), created 2026-07-06 —
  run gates as `.venv/bin/python -m pytest -q` etc. mypy+ruff are installed in the
  venv but NOT in requirements-dev.txt (matches CI-less local setup). Frontend needs
  `npm install` after fresh clone (vitest is a devDependency).

- **`.env*` files are permission-blocked for agents in this session.** Don't try to
  read them; probe the running server's `/api/llm/status` instead to learn the
  active provider.

- **The existing `ModuleConfig.automations` is a client-side intra-module rule
  engine** (checked→increment/flag). The V2 always-on runtime is a separate
  server-side concept — never overload the old field.

- **Env knobs must be read fresh per call** (function, not module constant) or
  conftest's `_isolate_llm_env` can't isolate them per test; add every new
  `TRUS_*` knob to that delenv list (backend/tests/conftest.py:42).

- **Injectable time, never sleeps:** the `_RateLimiter.allow(now=...)` pattern
  (routes/deps.py:41) is the house style for testing time-dependent code; the V2
  scheduler must take an injectable clock the same way.

- **Scheduler-thread DB safety is already there:** db.py's per-call `_conn()`
  (WAL + busy_timeout 5000) is thread-safe as-is; multi-step atomic work stays on
  ONE `_conn()` (restore_snapshot is the canonical pattern).

- **Portal tiles paint below modules and auto-place on a shelf at y ≤ -168** so
  they never collide with the module grid (origin 32,96). Keep any portal visual
  upgrade inside the same world-transform layer.

- **`animate-slide-right` creates a transform containing block** — fixed-position
  children (ConfirmDialog) of a sliding panel must be siblings/portals, never
  nested (ArchivedPanel.tsx:32).

- **Zoom clamp [0.3, 2] is duplicated** in Canvas.tsx:166 AND lib/viewPersist.ts:21
  — change both or neither.

- **The status palette only had terracotta + sage; "held/needs-tap" needed a
  third.** The Pulse design calls for amber on `held`/`skipped` journal rows and
  the "needs your tap" header, but globals.css had no amber token (only
  `--status-err`/`--status-ok`). Added `--status-hold` (#cf9f52, muted amber) +
  `--status-hold-dim` in the `:root` ethos block, same muted family as the other
  two (never neon). Reach for it for any future "pending your attention" state so
  it stays distinct from `failed` (terracotta). `--gray-mid` is the "dim gray"
  used for `expired` — a step below `--muted`.

- **Pulse rows construct-in via `lib/useAssembly.ts`, not a bespoke gate.** It
  wraps `runAssembly` with the exact reduced-motion gate from Module.tsx:102-111.
  `runAssembly` skips whichever `data-assembly` beats a row omits, so a card only
  needs the scaffold it renders (ApprovalCard/AutomationRow carry border-svg +
  scan; ActivityRow is lighter — label + body only, calmer for a dense feed).

- **`Date.now()` in render trips `react-hooks/purity`.** For relative-time
  registers, capture the clock once with a lazy `useState(() => Date.now())` in
  the panel and pass `now` down as a prop — children stay pure and every "ago"
  reads consistently as of panel-open. (Backend endpoints for a surface may not
  exist yet while building the frontend — build to the contract; `npm run build`
  is static, it never hits the server.)

- **A1 spine: the executor signature deviates from DESIGN-autonomy** — it is
  `execute(owner, payload, ExecContext) -> ExecResult`, not `(owner, payload) ->
  dict`. `watch` is edge-triggered on the automation's own `state_json.armed`, so
  it needs the current scratch state + injected `now` in, and the new state back
  out. `ExecContext` = `{automation_id, page_id, state, now, interval_secs}`;
  `ExecResult` = `{result, state}` (state None = leave scratch untouched). The
  reconciled doc's "engine wired to the action model" authorizes this — the one
  intentional signature deviation.

- **Frozen-payload enrichment rides on Pydantic v2's default `extra="ignore"`.**
  `actions.park` freezes a payload dict that may carry keys the `AutoAction` model
  doesn't declare (send_email's resolved `body`, archive/delete display
  `*_title/_name`). On approve, `parse_action` re-validates the frozen JSON for
  safety, but the executor runs on `json.loads(payload_json)` — the RAW frozen
  dict — NOT `action.model_dump()` (which would drop the enriched keys). If a new
  AutoAction ever sets `extra="forbid"`, park-freeze + approve-revalidate will
  start 500-ing; keep them extra-tolerant.

- **uses_llm actions freeze the SPEC, not composed content** (zero-spend park). A
  dial-0-held summarize/draft/learn has no preview and its `_freeze_payload` is a
  no-op; approve runs the budget gate then composes. Only non-LLM consequential
  actions resolve content at park time.

- **Test owners need a `sessions` row before `insert_module`/`add_message`.** The
  V2 tables are FK-free on owner, but modules/messages still reference
  `sessions(id)`. In tests, either use a TestClient (its first request mints the
  anon session) or `INSERT OR IGNORE INTO sessions` for a chosen owner id, else
  you get `FOREIGN KEY constraint failed` from the default-page insert.

- **`runtime._runtime_limiter` is a module-level instance** (its own gen-rate
  budget, separate from routes.deps `_gen_limiter`). It persists across tests;
  clear `._hits` in an autouse fixture, or use unique owner ids, so `budget_ok`
  stays deterministic when `now` is injected at a fixed timestamp.

- **The `"shared"` Module variant reuses the card but not the canvas motion
  scaffold.** In non-canvas mode Module renders neither the `border-svg`/`scan`
  assembly elements nor runs its own `useIsoLayoutEffect` assembly (both gated on
  `isCanvas`). So the read-only shared surface drives construct-in by attaching
  `lib/useAssembly.ts` to each tile's absolutely-positioned WRAPPER — `runAssembly`
  finds only the `label`+`body` beats that DO render and skips the missing ones
  (seed + surface-fill + label-wipe + settle, no border trace). Read-only-ness is
  belt-and-braces: `setField` early-returns on `shared` AND the fields sit in a
  `<fieldset disabled className="contents">` (`contents` keeps it layout-neutral, so
  canvas/detail/preview are untouched).

- **`crossModuleValues`/`computeMetric` moved verbatim to `lib/crossModule.ts`**
  (Canvas + SharedSurface both import). They stay typed to `StoredModule[]`; the
  whitelisted `SharedModule` payload (id/config/updated_at only) is mapped up to
  StoredModule shape in SharedSurface (`rev:0, archived:false, page_id:null` — inert
  on a read-only surface) so both the renderer and the helper type-check. Off-page
  `source_module_id` resolves to undefined over the delivered page-scoped list and
  falls back to saved state — zero special-case code.

- **Shared surface layout normalizes by min x/y, not just the bounding box.**
  `lib/sharedLayout.ts` subtracts the minimum x/y across modules so nothing lands at
  a negative offset the viewer can't scroll to; the container `minHeight` is only a
  FLOOR (module `layout.height` is usually 0 / content-sized) — absolutely-positioned
  tiles extend the `overflow-auto` scroll area past it. Reuses the `.canvas-grid`
  dot-grid class for the charcoal texture. SharePanel's ConfirmDialog is a SIBLING of
  the `animate-slide-right` aside (the containing-block lesson, again).
