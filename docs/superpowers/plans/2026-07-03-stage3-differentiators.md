# Trus MVP — Stage 3: Differentiators Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Contracts below are binding; the controller's dispatch carries drift notes. Steps use `- [ ]`.

**Goal:** Ship the three things that make Trus the product the brief describes, not just a reliable generator: **last-mile actionability** (live external data — the v0 differentiator), an **evolving user profile** (the "remembers you" memory), and **visible spatial nesting** (the "digital clay" feel) — plus the carried Stage-2b backlog.

**Architecture:** All three extend existing seams. Live data = a new `data_source` field on components + keyless server-side proxies (weather via Open-Meteo, nutrition via Open Food Facts) with SQLite-cached TTL fetches + a frontend refresh hook rendering freshness/provenance; the orchestrator learns to emit bindings and NEVER fabricates a live value it can't source. Profile = a `user_profile` store (per-owner, inspectable/editable facts) that accretes from interviews/usage and is retrieved into the generation prompt — riding Stage-1 identity. Spatial nesting = page-portal tiles rendered on the parent canvas in world coords (Stage-2b's overlay pattern), enterable by click/zoom, with per-owner spatial persistence.

**Tech Stack:** unchanged. No new deps (Open-Meteo + Open Food Facts are keyless REST; zero-dep urllib like the LLM/STT seams).

## Global Constraints

- Spec `docs/MVP-SPEC.md`; cite R-IDs. Invariants: I-1 config-not-code; honesty seam (provenance, degradation visible, nothing degraded/fabricated cached, stub refuses what needs a live source); R-903 per-owner isolation everywhere (profile + spatial state + any per-user cache).
- Gates per task: `python -m pytest -q` (repo root, 80% gate ON) / `mypy backend/src` / `ruff check backend/src`; frontend tasks + `cd frontend && npm test && npx tsc --noEmit && npm run build` (rm -rf .next first if iCloud " 2" dup-file tsc errors).
- **Branch `stage3/differentiators` off `main` (24f22e3, the merged MVP).** Repo path has SPACES. `git add` specific files. Commit `type(scope): summary` + R-ID body + `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Env introduced: none required (both providers keyless). Optional `TRUS_LIVE_DATA` (default `on`; `off` disables live fetches → components render manual-entry only). Add to `.env.example` + conftest isolation.
- New-surface design bar: R-1305 vs `DESIGN-ETHOS.md`; profile surface + portal tiles get dialog/keyboard semantics (R-1306 floor).

---

### Task 1: Stage-2b backlog burn-down (S/M)
Six carried items — do each with a test where a seam exists:
- **Composed-prompt token cap** (`orchestrator.py`): the seeded system now stacks seed-JSON + module-context + exchange fold + conversation block; add ONE composed-size guard — a module-level `_MAX_PROMPT_CHARS` (~12000) applied after composition: truncate the LOWEST-priority blocks first (conversation, then module-context detail) to fit, keeping the raw user prompt + exchange answers intact. Test: an oversized composition truncates conversation before exchange, never drops the user prompt.
- **Transcribe rate limiting** (`routes/transcribe.py`): a per-owner in-memory sliding-window limiter (e.g. ≤20 transcribes / 5 min) → 429 with an honest message. Small `_RateLimiter` helper (reusable — the generate routes are the next customer, note it). Test: 21st call in-window → 429.
- **Server-side suggestion filter** (`db.suggestion_prompts` or the route): move the 📎/refine/short filter from `frontend/src/lib/suggestions.ts` to the backend so any consumer gets clean data; keep the frontend filter as belt-and-braces but the API must not return noise. Test: a 📎 log line + a refine join never appear in the API response.
- **Sketch raster dimension clamp** (`frontend/src/lib/sketchExport.ts`): `strokeBounds` result clamped so the offscreen raster never exceeds ~2048px on a side (downscale factor returned); vitest for the clamp.
- **Entry focus trap** (`EntryScreen.tsx`): trap Tab/Shift+Tab within the dialog while open + restore focus to the opener on close (mirror ConfirmDialog's trap from 2a-3). Manual-trace.
- **Sketch/file preview-confirm unification** (defer decision): the file-upload + sketch paths insert directly, not preview→confirm (R-223 "on confirm"). SCOPE CHECK: routing both through the preview stack is L and touches the file route's response contract. DECISION for the controller at dispatch: if clean, add a `preview: bool` to the file route that returns `previews` instead of inserting (like the text preview path) and have sketch/file callers use it; if it balloons, defer to a follow-up and log it. Do the smaller honest version.
Commit(s): backend items in one, frontend items in one — `chore: stage-2b backlog (token cap, transcribe rate limit, server-side suggestion filter)` and `chore(frontend): sketch raster clamp, entry focus trap`.

### Task 2: Live-data framework + weather provider (R-701/R-704 + first domain)
Backend:
- `schema.py`: add optional `data_source: DataSource | None = None` to the components that can show a live value — Metric, Kpi, and (if they exist) any single-value display component (read schema.py; do NOT add to inputs like text_input). `DataSource` = `{provider: Literal["weather","nutrition"], query: dict, refresh_secs: int = 600, label: str | None}`. Validation: `provider` in the allow-list; `query` bounded (dict of str→str/num, ≤10 keys). Mirror in `frontend/src/lib/types.ts`.
- New `backend/src/services/live_data.py`: `fetch(provider, query, owner) -> {value, unit, as_of, source, stale}` — dispatches to a per-provider fetcher; server-side SQLite-cached with `refresh_secs` TTL (new `live_cache` table: provider, query_hash, value_json, fetched_at; per-provider, NOT per-owner — public data, but rate-limit fetches). Weather fetcher: Open-Meteo (`https://api.open-meteo.com/v1/forecast?latitude=&longitude=&current=temperature_2m,...`) — keyless; `query` carries lat/lon (or a city→geocode via Open-Meteo's geocoding endpoint). Zero-dep urllib, timeout, honest error → `stale=True` with last-cached value if any, else a null value with `source`/error surfaced.
- New route `GET /api/live/{provider}` (owner-gated, Origin not needed for GET but rate-limited via Task 1's limiter): validates provider+query, calls `live_data.fetch`, returns the value payload. This is what the frontend refresh hook calls.
- `TRUS_LIVE_DATA=off` → the route returns a disabled marker; components render manual-entry.
TDD: weather fetch (mocked urlopen) returns value+as_of; TTL cache hit skips the fetch; provider error → stale+last-value; disabled env → disabled marker; bad provider/query → 422; owner-gated.
Commit: `feat(backend): live-data framework + keyless weather provider (R-701/R-704)`.

### Task 3: Nutrition provider (R-702 second domain)
`live_data.py` nutrition fetcher: Open Food Facts (`https://world.openfoodfacts.org/api/v2/search?...`) or the simpler product endpoint — `query` carries a food name; return calories (+ unit "kcal", per-100g or per-serving with the basis in `source`). Keyless. Same cache/TTL/honest-error shape. The "calorie tracker" demo (spec R-702 AC) drives this. TDD mirrors weather. Commit: `feat(backend): nutrition provider for live-data (R-702)`.

### Task 4: Orchestrator emits live bindings + honest non-fabrication (R-702/R-703/R-705)
`orchestrator.py`: the DECOMPOSE/system prompt learns that Metric/Kpi components MAY carry a `data_source` when the user's intent implies live data — calorie/food → nutrition, weather/trip/run → weather — and that it MUST NOT fabricate a data_source for any OTHER domain (R-705: unlaunched domains get manual-entry, no fake live badge). `_parse_modules` validates emitted `data_source` against the allow-list and DROPS an invalid/out-of-domain one (repair, don't reject the whole module — component keeps working as manual entry). Add the two launch domains to the prompt with concrete examples. TDD: a food-tracker prompt (mocked model emitting a nutrition data_source) validates through; an out-of-domain data_source (e.g. "stocks") is stripped, component survives as manual; the honest-refusal/no-fabrication path pinned. NOTE: keep the semantic-cache-key invariant — data_source is part of the config value, not the key. Commit: `feat(backend): orchestrator emits live-data bindings, never fabricates out-of-domain (R-702/R-705)`.

### Task 5: Live-data frontend — render live values with freshness + refresh + graceful failure (R-701/R-703)
Frontend: the Metric/Kpi renderers (find them in `components/primitives/` — MetricField/KpiField) gain a live-value path: when the component config has `data_source`, a `useLiveValue(dataSource)` hook (new `lib/useLiveValue.ts`) fetches `GET /api/live/{provider}` on mount + every `refresh_secs`, renders the value with an "as of …" freshness line + source provenance ("via Open-Meteo"); on failure/stale renders the last value with a muted "stale" badge and the module stays manually editable (R-703); disabled/`off` → falls back to the manual field. The refresh loop cleans up on unmount (no leaked interval). Extract the fetch/format pure logic where testable (vitest); the hook is manual-trace. R-1305 design check: freshness/provenance styling matches the ethos (muted, no new palette). Commit: `feat(frontend): components render live external values with freshness + graceful failure (R-701/R-703)`.

### Task 6: Profile store + accretion (R-801/R-802)
Backend:
- New `user_profile` table (per-owner: id, owner, kind ∈ {goal, preference, pattern, fact}, text, source ∈ {interview, prompt, activity, manual}, created_at, updated_at). `db.profile_list(owner)`, `profile_add(owner, kind, text, source)`, `profile_update(owner, id, text)`, `profile_delete(owner, id)`, `profile_clear(owner)`. R-903: all owner-scoped.
- Accretion (R-802 — "without forms"): after a completed interview (the exchange resolved into a build), extract profile-worthy facts — SIMPLEST honest version: a small orchestrator step that, on a confirmed generation with an exchange, asks the model (one cheap call, or reuse the decompose call's output) to emit 0–3 short profile facts (goals/preferences it learned) → `profile_add(source="interview")`. Guard: nothing enters the profile the user can't see (it all lands in the inspectable store). Keep it bounded (≤~50 facts/owner; oldest low-value pruned or just capped). If the extraction call is too heavy for MVP, the fallback is: store the user's own stated goals from interview answers verbatim as `fact` — document which you did.
- Routes: `GET /api/profile`, `POST /api/profile` (manual add), `PATCH /api/profile/{id}`, `DELETE /api/profile/{id}`, `DELETE /api/profile` (clear) — all owner-gated.
TDD: add/list/update/delete/clear owner-scoped; cross-owner isolation; interview accretion produces a visible fact; cap enforced. Commit: `feat(backend): evolving user profile store + interview accretion (R-801/R-802)`.

### Task 7: Profile feeds generation + true erasure (R-803/R-804/R-1003)
Backend: `generate_modules`/`preview` context gains a bounded "What I know about you:" block from `profile_list(owner)` (top ~10 by recency/kind, ≤~800 chars), composed into the seeded system alongside the conversation block — so a returning user's proposals are shaped by their profile (R-803). NOT the cache key (invariant). NOT on the grounded-file path. Account deletion / `profile_clear` is real deletion (R-804); wire profile into any existing account-erasure path (R-1003) — if none exists yet, `profile_clear` + a note that full-account erasure is a Stage-4 item. TDD: profile fact reaches the model input; two owners' profiles never cross; identical re-prompt still cache-hits (profile in system msg, not key); clear → gone. Composed-prompt cap from Task 1 must account for this new block. Commit: `feat(backend): profile shapes generation; profile erasure is real (R-803/R-804)`.

### Task 8: Profile surface — inspectable + editable (R-801 frontend)
Frontend: a Profile panel (new `components/ProfilePanel.tsx`, opened from a header/sidebar affordance like Snapshots/Archived) listing the owner's profile facts grouped by kind, each editable (inline) and deletable, with a "clear all" (confirmed via ConfirmDialog), and a manual "add a fact" input. Fetches `GET /api/profile`; mutations via the profile routes; optimistic + honest error. This is the R-801 "a real surface where the user can see, correct, and delete what Trus believes about them." R-1305 + R-1306 (dialog semantics, keyboard). Manual-trace + tsc/build. Commit: `feat(frontend): inspectable/editable profile surface (R-801)`.

### Task 9: Visible spatial nesting — page portals on the canvas (R-502/R-503/R-504)
Frontend (the "digital clay" feel):
- On a parent page's canvas, render a **portal tile** for each CHILD page (from the existing `parent_id` tree) as a world-coord object (reuse Canvas's transform, like the sketch overlay): title + icon + a cheap preview (child module count, or bounding-box thumbnail if trivial) + an "enter" affordance. Placement persists per user (new position fields on the page or a per-owner spatial store — smallest: reuse the pages table with `portal_x/portal_y` columns via additive migration, owner-scoped by the page's session).
- **Enter**: click/zoom-into a portal → navigate to that child page (the existing page switch); leaving is spatially obvious (breadcrumb + the parent shows where you came from). R-504: portal arrangement + per-page viewport persist across devices (viewport persistence is currently localStorage — move page/portal positions server-side; viewport-per-page can stay client if cross-device is too heavy, but note it).
- **Reparent/safe delete** (R-503): the sidebar already nests; add drag-to-reparent OR at minimum ensure deleting a parent handles children visibly (Stage-2a already made page-delete confirm+cascade with true count — verify child pages are counted/handled, not silently orphaned; the DB has parent_id with no FK cascade — a parent delete must reparent children to root or confirm-cascade them; fix if orphaning is still possible).
Backend: additive `portal_x/portal_y` (nullable) on pages + `db.update_page` accepts them (owner-scoped); a migration. TDD backend: portal position persists + owner-scoped; parent-delete does not orphan (reparent-to-root or cascade with the children counted). Frontend: portal render + enter + drag-place manual-trace; extract any pure geometry to a lib + vitest.
Commit: `feat: visible page-portal nesting on the canvas (R-502/R-503/R-504)`.

### Task 10: STATUS + stage exit + final review
STATUS.md Stage 3 section; full gate run recorded; API smoke (live weather+nutrition fetch with mocked providers or against the real keyless endpoints if network allows — note which; profile CRUD + isolation; portal position persist) on isolated port; controller does the visual browser smoke (a calorie tracker showing a live nutrition value, a weather value, the profile panel, a page portal you can enter). Commit `chore: stage-3 exit`. Then final whole-branch review (fable, base = stage3 branch point) → fix wave → user report.

## Stage-Exit Checklist (spec ACs)
- R-701/R-702 AC: "help me track calories" → a module where entering a food yields a real calorie value from a live source; "plan my Saturday hike" → a module showing the actual forecast. Both render freshness ("as of…") + provenance.
- R-703 AC: kill the provider → stale badge, module still manually usable, workspace unharmed.
- R-705: an unlaunched-domain intent (stocks/flights) does NOT get a fake live value — manual entry, no live badge.
- R-801 AC: profile surface shows facts; user can edit + delete; a manual add appears.
- R-802 AC: after an interview stating a goal, the profile surface shows a corresponding entry with no form-filling.
- R-803 AC: same prompt from a fresh vs established profile yields proposals differing in ways traceable to profile entries (manual/eval trace).
- R-804/R-1003: clear/delete is real — a distinctive profile string is gone after clear.
- R-502 AC: child pages appear as enterable portals on the parent canvas; enter + return without the sidebar; three levels deep works.
- R-503: parent delete never silently orphans children.
- R-504: portal arrangement persists across devices.
- R-903: live-cache is public-data-only; profile + portal state strictly owner-scoped (test-pinned).
- Honesty seam holds (stub refuses live fetches gracefully / renders manual; nothing fabricated or degraded cached).
- All gates green; vault decisions-log + memory updated; merge decision to the user.
