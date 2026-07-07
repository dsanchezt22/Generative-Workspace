# Trus — Project Status

_An AI-orchestrated personal operating system: describe what you want to organize, and the system generates the exact tool for it._

**Last updated:** 2026-07-07
**Repo:** https://github.com/dsanchezt22/Generative-Workspace
**Branch state:** Stage 1 + 2a + 2b are merged into `main` (merge commit `24f22e3`). Stage 3 (`stage3/differentiators`) is complete at `89f70d6`; final whole-branch review and merge decision remain open. Stage 4 (`stage4/hosted-alpha`, branched off `main` at `5ece326`) is now at `75445c0` with this exit task's evidence recorded below; final whole-branch review and merge decision remain open. **`V2` (branched off `main` at this Stage-4 state) implements the vision in `VISION.md` — see the "V2" section below; final review/merge into `main` remains open, same as Stage 3/4.**

---

## Architecture (the one decision everything rests on)

The AI **never generates UI code**. The orchestrator turns a prompt into a typed
`ModuleConfig` (JSON: which components, how they bind, what's prefilled), and the
frontend renders that config with a fixed, trusted component library. This keeps
output instant, consistent, and impossible to break into "malformed HTML."

```
prompt ──▶ Gemini (orchestrator) ──▶ ModuleConfig (JSON) ──▶ trusted components ──▶ canvas
```

- **Backend:** Python 3.12 (Docker) · FastAPI · SQLite (stdlib) · `google-genai`
- **Frontend:** Next.js 16 · React 19 · TypeScript · Tailwind v4

## Stage 1 — structural blockers (shipped)

Closed the 7 cross-cutting findings from `docs/MVP-GAP-AUDIT.md` that stood between a local demo and a hostable 50-user alpha:

1. **One shared trust domain** → invite-claim identity (`users` table, session `uid`), per-owner scoping of the generation cache and layout library.
2. **Event loop blocked on every model call** → LLM/vision calls moved off the async event loop; one generation no longer freezes health checks and saves for every user.
3. **Silent degradation everywhere** → honest refusal on unreadable input, degraded/cascade output never cached or persisted as a fake success.
4. **No schema versioning for persisted configs** → tolerant reads; one corrupt row quarantines itself instead of 500ing the whole workspace.
5. **Zero observability** → structured logging, per-generation telemetry (`gen_events`), operator summary endpoint.
6. **Data-loss races in the client** → single-writer module saves, rev-based optimistic-concurrency conflict detection across tabs.
7. **Quality gates red at HEAD** → green baseline restored, coverage gate reconciled and raised, frontend test/CI job added.

## Stage 2a — reliability completions (shipped)

Landed the two security decisions from the Stage 1 final review plus the triaged backlog:

- **Security decision A:** Origin gate on state-changing multipart endpoints (upload/import/capture) — closes the `SameSite=None` cross-site CSRF vector.
- **Security decision B:** SSRF guard on studio `image_url` — refuses private/loopback/link-local/metadata targets and redirect bypasses; URL import off by default in prod.
- **R-1102:** destructive actions confirmed or undoable — page delete shows a typed module-count confirm, module removal is archive-first (restorable), permanent delete is confirmed; snapshot restore is now one atomic transaction that preserves module ids (cross-module bindings survive a restore).
- **R-211:** documents ground on every provider, not just Gemini's native multimodal path — server-side text extraction (`pypdf` + plain-text decode) feeds the normal generation path ahead of the honest-refusal fallback.
- **R-1201/R-1202:** telemetry completions — file-upload generations carry real provenance (provider/model), ops summary reports per-user last-seen, `/api/llm/status` is trimmed in prod.
- **R-602/R-1101 backlog:** saver hardening — 404 responses are treated as "forgotten" (no retry loop), `beforeunload` does a best-effort keepalive flush of pending edits, module commits use functional updates (no same-tick stale-closure class), the degraded-generation notice moved off the error-red channel.
- Small-backlog batch: studio layout rows quarantine on parse failure instead of breaking the list; `requirements.txt` (runtime) split from `requirements-dev.txt` (test tooling) so the Docker image doesn't bundle pytest.

## Stage 2b — input surfaces (shipped)

Ships the brief's must-have input story — entry-as-interview, voice rambling, sketch-to-module, and the prescriptive idea-generation package:

- **R-101/R-104/R-105 — entry-as-interview front door:** `IntroSplash`'s decorative overlay replaced with a true pre-workspace entry (rotating "Tell me what's on your mind" headline, a large mic affordance as the primary control, a text field as the visible secondary), shown on a first-visit-empty-workspace session or via EmptyState re-entry; dissolves to canvas on submit, Escape/Skip dismisses, keyboard-reachable (`role="dialog"`, focus starts on the text field).
- **R-201-204 — voice rambling:** new pluggable `POST /api/transcribe` (`TRUS_STT_*` env, OpenAI-compatible `/v1/audio/transcriptions`; unset → honest 422) + a PromptBar mic rework — press-to-start/stop recording, transcript appends into the input (never overwrites), Web Speech interim text as live garnish only, mic-denial degrades to typing without breaking the flow.
- **R-221-223 — sketch overlay → snap:** canvas toolbar Sketch toggle (world-coordinate stroke overlay: pen/eraser/clear), "Snap to modules" rasterizes the sketch and routes it through the existing file-upload vision path with a sketch-tuned hint; overlay clears on success or cancel (ephemeral, R-223).
- **R-102/R-103/R-301 — proposal plans + multi-turn interview:** proposals now carry a one-paragraph `plan` (rendered above the preview stack); the clarifying-question exchange moved server-side (`GenerateRequest.exchange`, hard-capped at 4 answered questions) — fixes the earlier answer-drop bug where PromptBar string-concatenated only the latest answer, and interview-specialized results no longer seed the shared prompt cache.
- **R-302 — conversation context:** the owner's last ~10 messages on the current page feed generation context (not the grounded-file path, and never when there's no page scope); the semantic-cache key stays the raw prompt, so an identical re-prompt still hits.
- **R-104 — per-owner suggestions:** `GET /api/suggestions` — usage-seeded chips drawn from this owner's `gen_cache`/`messages`, R-903-scoped (cross-owner isolation is test-pinned, and reconfirmed in this task's own smoke run below).
- Stage-2a triaged backlog closed alongside: CORS origin-parsing single-sourced into `routes/deps.py`, one `_gemini_model()` helper replacing three copies, `nosemgrep` comments scoped to rule ids, SSRF guard now also checks `is_global` (CGNAT) and refuses redirects, a route-level prod test for `/api/llm/status`.

New env: `TRUS_STT_BASE_URL` / `TRUS_STT_MODEL` / `TRUS_STT_API_KEY` (all optional — absent means voice transcription is an honest 422, never a silent failure). Documented in `.env.example`, the conftest isolation list, and `deploy/README.md`'s env table.

## Stage 3 — differentiators (shipped)

Ships the three things that make Trus more than a reliable generator — last-mile actionability, a memory that evolves, and a spatial "digital clay" feel — plus the carried Stage-2b backlog:

- **Stage-2b backlog burn-down:** composed-prompt token cap (`_MAX_PROMPT_CHARS` ≈12000, lowest-priority blocks — conversation, then module-context — truncated first; the raw user prompt and exchange answers are never touched); transcribe rate limiting (a reusable `_RateLimiter`, ≤20 calls/5min per owner, 429 on the 21st — now also the live-data route's limiter); server-side suggestion noise filter (📎/refine-join/short-fragment junk is stripped in `db.py` before it ever leaves the API, not just the frontend); sketch raster dimension clamp (the offscreen export canvas is capped at ~2048px/side via a downscale factor); an entry-screen focus trap (mirrors `ConfirmDialog`); and a `preview` flag on `generate_from_file` wired into the file-attach caller so a file upload goes through the same preview→confirm stack as a text prompt (the sketch-snap caller stays direct-insert — a documented scope call: unifying it would require lifting `PromptBar`'s preview state into a shared parent, judged too large for this task).
- **R-701/R-702/R-704/R-705 — live external data:** a new `data_source` field (`{provider, query, refresh_secs, label}`) on Metric, Kpi, Ring, Gauge, and ProgressBar. `GET /api/live/{provider}` (owner-gated, rate-limited) is backed by `services/live_data.py` — keyless Open-Meteo for weather (geocodes a place name, or takes lat/lon directly) and Open Food Facts for nutrition (kcal/100g) — both SQLite-cached with a `refresh_secs` TTL; a provider failure returns the last-cached value marked `stale`, or an honest null value with the error surfaced — nothing is ever fabricated. The orchestrator's decompose prompt now emits `data_source` bindings for the two launched domains (calorie/food → nutrition, weather/trip/hike → weather) and strips any out-of-domain or malformed binding on both the decompose *and* refine parse paths, so the component survives as plain manual entry rather than the whole module failing validation — an unlaunched domain (stocks, flights) never gets a fake live badge (R-705). The frontend's `useLiveValue` hook polls on mount and every `refresh_secs`, renders an "as of … · via Open-Meteo/Open Food Facts" freshness line, degrades to a muted stale badge on provider failure while the control stays manually editable (R-703, verified concretely on Ring/Gauge's bound input), and falls back to the plain manual field when `TRUS_LIVE_DATA=off`.
- **R-801/R-802/R-803/R-804/R-1003 — evolving user profile:** a new owner-scoped `user_profile` store (`kind` ∈ goal/preference/pattern/fact, `source` ∈ interview/manual, capped at 50 facts/owner with oldest-pruned, deduped per owner+kind) behind `GET/POST/PATCH/DELETE /api/profile` and a clear-all `DELETE /api/profile`. Accretion fires on a **confirmed** module insert that carries the interview exchange (`POST /api/modules`) — moved there from generate/preview after review, so nothing accretes from a proposal the user never accepted — storing the user's own stated answers verbatim, tagged goal/fact by a `want`/`goal`/`track` keyword heuristic. Accretion currently covers **interview answers only** — the other R-802 `source` enum values (`prompt`, `activity`: prompt + workspace-activity accretion) are reserved in the schema but unwritten, a Stage-4 item. A bounded "What I know about you:" block (~800 chars, most-recent facts first) feeds `generate_modules`'s composed system message — confirmed to never affect the semantic-cache key (an identical prompt still cache-hits with a fresh profile present) and never reached on the grounded-file path. `ProfilePanel` (new, opened from the sidebar) lists facts grouped by kind, each inline-editable and deletable, with a confirmed "clear all"; `DELETE /api/profile` is a real hard SQL delete — the erasure surface for now (a full-account cascade across every owner-scoped table doesn't exist yet and is a Stage-4 item, documented inline in the route).
- **R-502/R-503/R-504 — visible spatial nesting:** child pages render as world-coordinate, draggable, enterable **portal tiles** on the parent's canvas (the same transform modules and the sketch overlay use) — a restrained dashed-panel affordance showing a live "N tools" count (`GET /api/pages/counts`, no child module configs loaded) and keyboard-reachable via `role="button"` + Enter/Space. Placement (`portal_x`/`portal_y`, an additive migration, owner-scoped) persists server-side across devices via `PATCH /api/pages/{id}` — note this cross-device persistence covers portal/page **positions** only; the per-page **viewport** (pan/zoom) is still client-only in `localStorage` (a deliberate Stage-4 item: viewport-per-page cross-device persistence). Fixed a real orphaning bug along the way: `pages.parent_id` has no FK cascade, so `db.delete_page` now reparents a deleted page's children to its own parent (the grandparent, or root if top-level) before deleting — a parent delete never silently drops children from the tree, and a fix-round follow-up moved auto-placed portals onto a shelf above the module grid so they're never rendered underneath (and unclickable behind) a module card.

New env: `TRUS_LIVE_DATA` (default `on`; `off` disables live fetches and every `data_source`-capable component falls back to plain manual entry) — documented in `.env.example` and the conftest isolation list.

## Stage 4 — hosted-alpha polish (shipped)

Turns "runs on a laptop" into "50 Stanford students can use it daily" — touch-viable mobile, the accessibility floor, per-user cost/rate limits, a backup+restore story, and deploy readiness, plus the carried Stage-3 backlog:

- **R-1202 completion — generate-route rate limiting + cost ceiling:** a shared per-owner `_RateLimiter` now sits in front of all 5 LLM-backed handlers in `routes/modules.py` (generate, preview, generate_from_file, refine, insights) — the last unmetered-spend surface the Stage-1 audit flagged (transcribe/live already had their own) — 429 with an honest "too many generations" message past `TRUS_GEN_RATE_MAX`/`TRUS_GEN_RATE_WINDOW`. An optional per-owner **daily cost cap** (`db.owner_cost_today` off `gen_events`) 429s "reached today's usage budget" once `TRUS_DAILY_COST_CAP_USD` is set and crossed (cap unset, cap=0, or $0 token rates all correctly never block). `/api/ops/summary` now carries a per-user tokens/cost rollup alongside the existing last-seen data.
- **R-1304 — touch-viable mobile:** pinch-zoom (two-pointer gesture, distance-ratio zoom toward the midpoint, reuses the existing zoom clamp; pure gesture math extracted to a lib + vitest), a viewport meta tag (`width=device-width, initial-scale=1`, deliberately no `maximum-scale=1` so browser accessibility zoom still works), and responsive panels/prompt-bar/entry-screen/module-card legibility at 375px (no clipped text, no horizontal page scroll) — plus a fix-round pass (PromptBar `min-w-0`, pinch-resume-on-third-touch-lift, header no-overflow at 375px).
- **R-1306 — accessibility floor:** modules are keyboard-focusable (tabIndex, Enter/Space opens detail, arrow keys nudge position, Delete archives with the existing confirm, a visible focus ring); dialog semantics (`role="dialog"`/`aria-modal`, Escape-to-close, focus-trap, focus-restore-on-close) landed on the 9 overlays that lacked them (DetailView, CommandPalette, ShortcutsModal, ConversationPanel, Inspector, AppearanceMenu, SnapshotsPanel, ProfilePanel, ArchivedPanel — ConfirmDialog/EntryScreen already had the pattern from Stage 2b/3); skip-to-content + landmark roles (main/nav/complementary) let a keyboard/screen-reader user reach the canvas without tabbing the whole sidebar.
- **R-1106 — backup + restore:** `python -m src.backup {backup|list|restore}` — WAL-checkpoints (`PRAGMA wal_checkpoint(TRUNCATE)`) then copies `TRUS_DB_PATH` to a timestamped file under `TRUS_BACKUP_DIR`, retaining the last `TRUS_BACKUP_KEEP` (default 7); `restore` takes an atomic temp-file-then-replace swap and rejects empty/non-Trus DBs outright (nonzero exit, nothing touched) after a follow-up fix hardened the original swap; a safety snapshot of the pre-restore state is written before every restore. `deploy/BACKUP.md` documents the RPO≤24h target, cron scheduling, and the "exercise a restore once before the alpha" operator checklist item.
- **R-802 completion — prompt + activity profile accretion:** on a confirmed `POST /api/modules` insert, a goal/preference-stating prompt (whole-word `want`/`goal`/`track`/`prefer` or a `trying to` phrase — a fix-round pass tightened this to whole-word matching so build prompts like "add a tracking field" don't seed noise) yields a `source="prompt"` fact, and an inserted tool whose title matches a known domain (nutrition/workouts/budget/habits/sleep/reading/mood) yields a `source="activity"` fact — both ≤1/insert, same cap-50/dedup/owner-scoped store as the Stage-3 interview facts.
- **Live-data hardening:** `live_cache` now evicts oldest-by-`fetched_at` past a row cap (`TRUS_LIVE_CACHE_MAX`, default 5000); `/api/live` carries a structured `disabled: true` flag that the frontend reads directly instead of string-matching a message; `useLiveValue` clears its poll interval once it learns `disabled` (no wasted budget with `TRUS_LIVE_DATA=off`); GaugeField now shows a loading shimmer instead of a blank center number.
- **R-503/R-504 completion — spatial backlog:** page create/PATCH validates `parent_id` is an owned, existing page (422 otherwise — closes the dangling-parent-makes-page-invisible surface the Stage-3 review flagged); per-page viewport (`view_x`/`view_y`/`view_zoom`) now persists server-side, owner-scoped, so a user's pan/zoom resumes across devices instead of living only in `localStorage`. (The sketch-preview-confirm unification landed too, ahead of schedule — see Stage 3's note; sketch snaps now route through the same preview→confirm stack as a file attach.)
- **R-906 pre-flight — deploy readiness:** `backend/Dockerfile` + `deploy/fly.toml.example` carry every env var introduced since Stage 1 with sane prod defaults; `deploy/README.md` is a complete runbook (secrets, the `/data` volume incl. backups, CORS/PUBLIC_URL pairing, invite provisioning, backup cron, the R-906 phone-over-cellular smoke test, the Fly-volume-ownership gotcha); a new `deploy/PREFLIGHT.md` is the operator's pre-invite checklist. No live deploy — that's Task 10, the operator checkpoint.

New env: `TRUS_GEN_RATE_MAX` / `TRUS_GEN_RATE_WINDOW` (generate-route rate limit, default 30/300s), `TRUS_DAILY_COST_CAP_USD` (optional per-owner daily $ cap), `TRUS_TOKEN_COST_IN` / `TRUS_TOKEN_COST_OUT` (per-1k-token $ for the cost estimate; default 0 → cost shown as tokens only), `TRUS_BACKUP_DIR` / `TRUS_BACKUP_KEEP` (backup destination + retention count, default `/data/backups` / 7), `TRUS_LIVE_CACHE_MAX` (live_cache row cap, default 5000).

## Current gates (this run, 2026-07-05, HEAD `75445c0`, branch `stage4/hosted-alpha`)

| Gate | Result |
|---|---|
| `python -m pytest -q` (repo root, coverage gate on) — run 3× | **657 passed, 2 skipped**, 94.97% coverage (gate: 80%) — identical on all three runs; the known intermittent flake in `test_gen_rate_limit.py` did **not** recur across any of the three runs |
| `mypy backend/src` | clean, 33 source files |
| `ruff check backend/src` | all checks passed |
| `ruff format --check backend/src` | 33 files already formatted |
| `cd frontend && npm test` | 10 test files, **122 passed** |
| `npx tsc --noEmit` | clean |
| `npm run build` | clean production build (4 static routes) |

API-level smoke against a fresh backend on a spare port (8121, isolated `TRUS_DB_PATH` in a temp dir — the user's `:8000`/`:3000` and live `trus.db` were never touched), `TRUS_LLM_PROVIDER=stub`, `TRUS_GEN_RATE_MAX=3`: two invite-claims (Alice/Bob) both 200 and `/api/auth/me` confirms each; Alice's 4th `preview` call in-window → 429 "too many generations"; Bob's spend seeded directly via `db.add_gen_event` (mirroring the unit-test pattern) past a `TRUS_DAILY_COST_CAP_USD=0.001` cap → the next `preview` call 429s "reached today's usage budget"; `GET /api/ops/summary?token=...` shows the per-user cost/token rollup (Bob $0.20, Alice $0 on stub generations) and 401s on a wrong token; `POST /api/pages` with a nonexistent `parent_id` → 422 "Parent page not found", a valid create → 201; `PATCH` a page's `view_x`/`view_y`/`view_zoom` → `GET /api/pages` reads them back; a confirmed `POST /api/modules` insert with a goal-stating prompt ("I want to track my reading habit…") and a "Reading Log" tool → `GET /api/profile` shows both a `source="prompt"` goal fact and a `source="activity"` pattern fact; `python -m src.backup backup` against the live in-use DB writes a valid timestamped copy, `list` shows it, `restore` round-trips (both profile facts intact after restore) with an automatic pre-restore safety snapshot, and a 0-byte file is refused with a nonzero exit; `live_cache` eviction is covered by its own unit tests (`test_live_cache_set_evicts_oldest_over_cap` et al., part of the pytest run above) rather than re-driven over HTTP. Server killed and temp dir removed after; transcript in `.superpowers/sdd/stage4-task-9-report.md`.

## Stage 3 exit gates (previous run, 2026-07-05, HEAD `89f70d6`)

| Gate | Result |
|---|---|
| `python -m pytest -q` (repo root, coverage gate on) — run 3× | **567 passed, 2 skipped**, 94.80% coverage (gate: 80%) — identical on all three runs; the previously-de-flaked migration race test (`test_concurrent_migration_on_stale_db_does_not_double_alter`) held stable across all three |
| `mypy backend/src` | clean, 32 source files |
| `ruff check backend/src` | all checks passed |
| `ruff format --check backend/src` | 32 files already formatted |
| `cd frontend && npm test` | 7 test files, **85 passed** |
| `npx tsc --noEmit` | clean |
| `npm run build` | clean production build (4 static routes) |

API-level smoke against a fresh backend on a spare port (8120, isolated `TRUS_DB_PATH` in a temp dir — the user's `:8000`/`:3000` and live `trus.db` were never touched): invite-claim flow for two users (Alice/Bob via `python -m src.invites create`) both claim 200 and `/api/auth/me` confirms each; `GET /api/live/weather?place=London` — a real Open-Meteo fetch, 27.8°C; `GET /api/live/nutrition?food=banana` — a real Open Food Facts fetch (the first call hit a transient 503 from OFF's side, honestly surfaced as a null value + `error` field rather than fabricated, exactly the honesty-seam contract; a retry succeeded at 88.1 kcal/100g, and a second food — apple, 63.0 kcal/100g — confirmed a fresh cache key); `GET /api/live/weather` with no params → 422; profile CRUD round-trip (POST → GET shows it → PATCH → DELETE → GET confirms gone) plus cross-owner isolation (Bob's `GET /api/profile` never sees Alice's fact; Bob's `PATCH` on Alice's page also 404s); a 3-level page tree (GrandParent → Mid → Leaf) with the Leaf's `portal_x`/`portal_y` persisted via `PATCH /api/pages/{id}` and read back; deleting Mid (the middle page) reparents Leaf to GrandParent — present, not gone, portal position intact. All passed; transcript in `.superpowers/sdd/stage3-task-10-report.md`.

## Docs

- `docs/MVP-SPEC.md` — the requirements contract (R-IDs cited in commits).
- `docs/MVP-GAP-AUDIT.md` — the audit that drove Stage 1's structural findings.
- `docs/superpowers/plans/` — the Stage 1, Stage 2a, Stage 2b, Stage 3, and Stage 4 implementation plans, task-by-task.
- `deploy/README.md` — hosting (Fly + Vercel), env contract, invite provisioning, post-deploy smoke test.
- `deploy/BACKUP.md` — SQLite backup+restore runbook (R-1106).
- `deploy/PREFLIGHT.md` — operator pre-invite checklist (R-906).

## Next

Stage 4 remaining = **Task 10, OPERATOR DEPLOY** (needs Janus's Fly/Railway + Vercel accounts, not agent-executable) + the carried Stage-4-tail backlog. Stage 3's and Stage 4's final whole-branch reviews and merge decisions remain open.

---

## V2 — self-composing, always-on personal OS

**Branch:** `V2` (off `main` at the Stage-4 state above). **Status:** every buildable
VISION-DOD.md criterion is met (40/40 — see the pass table below); final whole-branch
review and merge decision into `main` remain open, same posture as Stage 3/4.

Ships the ceiling-raise `VISION.md` describes: an always-on per-owner automation
runtime (a scheduler thread ticking real, persistent automations with zero browser
involvement); a 12-type tiered-by-reversibility action registry with a hard floor —
real-world irreversible actions (send/message/pay) can never run autonomously,
always park for a tap, and their executors are honestly-badged simulated stubs, never
a real send; the "Pulse" tap surface (what ran / what needs you, one-tap
approve/reject); self-composing structures (one prompt → multiple wired app-pages +
real automations, previewed before anything lands); app-grade zoomable surfaces
(portal tiles read as apps, entering one is a spatial zoom-launch, not a hard cut);
the accreting profile as a real input to automation behavior; and per-surface
read-only sharing via an unguessable, revocable link.

- `VISION.md` — the north star. `VISION-DOD.md` — the 40-criterion measurable contract.
- `docs/superpowers/plans/v2/DESIGN-RECONCILED.md` — the authoritative architecture
  (rules over the four per-fork `DESIGN-{runtime,autonomy,surfaces,sharing}.md` docs
  where they conflict).
- `docs/superpowers/plans/v2/VISION-DOD-PASS.md` — the full pass table, one row per
  criterion, with evidence (test name + what it asserts, or a live API drive).
- `docs/LESSONS-v2.md` — accumulated build gotchas, read before extending V2.
- **Gates:** `python -m pytest -q` → 848 passed, 93.70% coverage (80% gate) · mypy/ruff
  clean · frontend 163 tests · `tsc`/`next build` clean.
- **Needs a human:** (1) real send/message/pay credentials, if those stubs are ever
  wired to real providers — not required for anything shipped here; (2) optionally,
  `ollama serve` (a local model is already configured in `.env`, just not running) for
  local, non-cascaded generation — a real Gemini key already configured there means
  live (non-stub) generation works today via cascade; (3) the pre-existing Stage-4
  Task 10 operator deploy, unaffected by V2.
