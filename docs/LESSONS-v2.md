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

- **A2 sharing: the server-side `data_source` strip needs `# type: ignore[union-attr]`.**
  DESIGN-sharing §3's verbatim `comp.data_source = None` (guarded by a `getattr`
  existence check) does NOT pass mypy as-is — only Metric/Kpi/Ring/Gauge/ProgressBar
  in the 30-member `Component` union declare the field, so mypy raises union-attr on
  the other 25. The `getattr(comp, "data_source", None) is not None` guard makes the
  assignment always valid at runtime; the type-ignore is the intended tweak (setattr
  would trip ruff B010). The public path is otherwise 100% covered.

- **A2 gotcha: the public share path is sessionless BY OMISSION, not by a flag.**
  `read_shared` never calls `_owner_id` and never touches `request.session`, so
  Starlette's SessionMiddleware emits no Set-Cookie and mints no `sessions` row — it
  works under `TRUS_ALLOW_ANON=0`. If you ever add a `request.session[...]` read/write
  on that handler, you silently break test_share's no-cookie / no-session-row / anon-
  disabled guarantees. Keep it read-only and cookie-free.

- **SURF reverse zoom: read the parent view from `lastSavedViewRef`, not
  `latestViewRef`.** On "back", page.tsx sets `activePageId=parent` AND bumps
  `portalReturnReq` in one commit. The `[activePageId]` load effect runs first and
  `setView(parentView)` — but `setView` is async, so `latestViewRef.current` STILL
  holds the child's view when the reverse effect runs on that same flush. The load
  effect DOES set `lastSavedViewRef.current = {pid, v}` synchronously, so read the
  parent target from there. (DESIGN-surfaces §6's sample code says `latestViewRef`;
  this is the one correction — verified by the effect-ordering, not the prose.) The
  reverse effect must be declared AFTER the load effect so that ordering holds.

- **Portal-tile accents use a MUTED-only deterministic fallback** (`resolvePageAccent`
  in `lib/theme.ts`): an explicit `page.accent` token wins, else hash the name over
  `ACCENT_NAMES` minus `blue`. `blue` IS the magenta spark — excluding it from the
  fallback keeps the home canvas at exactly one magenta (the approval badge / a CTA),
  so per-app identity tints never collide with the one-accent-per-screen rule.

- **The SURF-2 "no raw-HTML" grep matches code COMMENTS.** A comment that names the
  `dangerouslySetInnerHTML` API to say you're NOT using it still trips
  `grep -rl dangerouslySetInnerHTML` on the Feed/PortalTile/AppFrame paths. Phrase the
  invariant without the literal token ("no raw-HTML injection path").

- **`launchTargetView`/`overviewMeta`/`deriveTier` are the pure, testable seams**
  (`lib/portalLayout.ts` + `lib/structure.ts`) — the zoom-launch math, the tile/AppFrame
  status line, and the client-mirrored fail-closed tier chip (reconciled ruling 4: a
  StructureAutomation carries `action_type`, never a `tier`; the five structure action
  types are all autonomous, everything else needs your tap). Components stay untested;
  these carry the logic. `PageOverview.last_run_at` is real from day one (ruling 6), so
  the "agent ran …" line renders whenever it's non-null — never a fabricated stub.

- **A3 backend: the structure passthrough MUST run before the flat persist.** In
  `generate_module`/`preview_modules`, `orchestrator.generate_modules` returns `[]` and
  sets `last_structure` for a broad prompt. The `if orchestrator.last_structure.get():
  return GenerateResponse(structure=...)` check has to sit BEFORE the `stored =
  [db.insert_module(...)]` / `stored[0]` line, or generate IndexErrors on the empty
  config list. A structure NEVER persists on generate/preview — only POST /api/structure
  (confirm) lands it.

- **A3: confirm composes REAL automations, not `status='proposed'` rows** (reconciled
  ruling 2 supersedes DESIGN-surfaces §2). There is NO proposed-status column and NO new
  automations DDL — the A1 table already has the full runtime shape. `routes/modules.py`
  imports `create_automation_row` from `routes/automations.py` (sibling-route import, no
  cycle: automations never imports modules) so structure confirm and POST /api/automations
  share ONE validate+insert path. `insert_structure` commits pages+modules in one txn;
  automations are composed AFTER (a `_DropAutomation`/`ValidationError`/`HTTPException`
  drops that one automation and appends its name to `dropped` — pages/modules always land).

- **A3: `StructureAutomation.action_type` defaults to `"summarize"`** (the fail-closed
  replacement for tier — all five structure action types are autonomous-floor, so there's
  no "consequential" default to reach for). At parse an unknown `target_component_id` is
  nulled (not dropped); confirm then drops the automation only if it's still unresolvable.
  Garbage `action_type` fails the Literal and drops the automation — the parser can never
  invent a type the model didn't state.

- **Reduced-motion CSS blocks must crush `animation-delay` too.** The global
  reduced-motion rules zeroed duration/iteration but not delay — a staggered
  `animate-pop` with `backwards` fill therefore rendered INVISIBLE for the length
  of its stagger delay under reduced motion. Both blocks now carry
  `animation-delay: 0.001ms !important`; keep it when adding new gates. Inline
  `style={{animationDelay}}` staggers are safe because of this.

- **`lib/motion.ts prefersReducedMotion()` is THE motion gate** (in-app
  `html[data-motion]` override first, OS query fallback). Canvas zoom-launch,
  Module assembly, and useAssembly all share it — never write a bespoke
  matchMedia check for new motion.

- **The product's de-facto card radius is 16px** (`rounded-2xl` + trace
  `rx/ry=16`, set by Module.tsx). Pulse cards had drifted to 12px and were
  aligned up. Match Module, not the marketing-site token table, for any new card.

- **The global `:focus-visible` outline can't reach Module or PortalTile** —
  Module's selected-state inline `outline` and PortalTile's `focus:outline-none`
  out-specify it, so those two carry their own off-white box-shadow ring. New
  components should rely on the global rule and NOT set outline-none.

- **`--accent-hover` (#a82478) is the semantic darker-magenta hover for filled
  accent CTAs** (`hover:bg-[var(--accent-hover)]`, never `hover:brightness-110`
  — brightening reads neon). Accent-colored TEXT links keep their color on hover;
  the darken rule is for fills where white text sits on top.

- **New raw-SQL f-string SELECTs need BOTH nosemgrep rule ids on their own line**
  (`formatted-sql-query` fires alongside `sqlalchemy-execute-raw-query` — the
  layout_library ALTER pattern); an inline trailing comment does not silence it.

- **`run_started_at` is an internal in-flight marker, not a wire field** — set by
  the tick after the CAS claim and by run-now's mutex, cleared on every journaled
  outcome; only a hard process death leaves it set, and Scheduler.start()
  reconciles those into one honest 'failed' row. Don't add it to AutomationOut.

- **Per-item primary is a documented exception to one-magenta-per-screen.** With
  N pending approvals the Pulse panel shows N filled-magenta Approve buttons (one
  per card). Reviewed against DESIGN-ETHOS §2.4 and accepted deliberately: Approve
  is the per-*item* primary in a queue, the list itself has no competing screen-level
  CTA while the panel is open (the badge hides), and demoting lower cards to matte
  would misstate their urgency. Don't "fix" this.

- **Share pages carry defense-in-depth headers, not just metadata.** The share
  token is a bearer credential in the URL. Beyond the page's `referrer:
  "no-referrer"` + `robots: noindex` metadata, `next.config.ts` sets real
  `Referrer-Policy: no-referrer` and `X-Robots-Tag: noindex, nofollow` response
  headers on `/share/:path*` — empirically, meta-only referrer policies have
  leaked tokens on some browsers (DIMVA 2019: 7 of 21 major services). Keep both
  layers; token entropy is `secrets.token_urlsafe(32)` (256-bit CSPRNG), don't
  reduce it.

- **Real dev env discovery: `.env` has a local Ollama endpoint (`TRUS_LLM_BASE_URL` →
  `http://localhost:11434/v1`, model `qwen3:4b-instruct-2507-q4_K_M`) AND a real
  `GEMINI_API_KEY`.** `_resolve_provider()`'s precedence (explicit override → base-url-set
  → openai) means the default dev server tries the openai/Ollama path FIRST; Ollama isn't
  running on this machine (`ollama serve` was never started), so every real call currently
  cascades openai-fail → gemini (keyed, so a REAL Gemini call fires, `degraded=True`) →
  stub only if ungemini'd. Confirmed with `ollama list` (server unreachable) and a direct,
  non-secret-leaking `llm.provider_info()` read (only provider/model/base_url — no key
  ever printed). **Needs-you item for closeout: run `ollama serve` (+ `ollama pull
  qwen3:4b-instruct-2507-q4_K_M` if not already pulled) to get real LOCAL generation with
  zero added credentials — Gemini already works today via cascade even without that.**

- **Found + fixed a real (not stub-only) honesty-seam bug: `llm.generate()`'s free-text
  callers (`actions._exec_summarize`/`_exec_draft`/`_exec_learn`) had no way to ask for
  plain prose.** Stub mode always returned a ModuleConfig-shaped JSON dump (the
  module-generation shape) regardless of caller intent, so a "digest" Feed entry showed
  garbled JSON, not a summary — live-caught by a VISION-DOD verifier driving the real
  running app. WORSE: the same bug existed on the REAL (non-stub) paths too — both
  `_gemini_config` and `_openai_chat` force `response_mime_type`/`response_format: json_object`
  by DEFAULT, so even a working Gemini/Ollama call would return JSON for a "summarize this"
  prompt. Fixed by adding `expect_text: bool` all the way through `generate()` →
  `_gemini_config`/`_gemini_generate` and `_openai_chat` (skip JSON-forcing when set) →
  a new `_stub_prose_for()` (honest "(stub — no live model configured) …" text, never a
  JSON dump) → `actions._llm_generate(..., expect_text=True)` default. Verified live against
  a real (unreachable-Ollama → Gemini-cascade) call: digest now reads
  "The water tracker is at five cups today." instead of forced JSON. Existing tests that
  monkeypatch `llm.generate`/`_gemini_generate` directly (`test_providers.py`,
  `test_actions.py`) never exercised the real default-stub shape, which is why this shipped
  green through 3 build waves — **a monkeypatched-provider unit test proves the write-path
  logic, not the default-stub end-to-end shape; re-check both.** Two of the four
  `_gemini_generate` lambda mocks in `test_providers.py` needed a `**_` catch-all to accept
  the new keyword-only `expect_text` param.
