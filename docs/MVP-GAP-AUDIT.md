---
title: Trus MVP Gap Audit — Generative Workspace vs. the Trus Brief
type: wiki-page
summary: Verified audit (36-agent, adversarially cross-checked) of the Generative-Workspace repo against the Trus brief — 1 pillar done, 12 partial, 2 missing; feeds the full spec sheet and the MVP attack plan.
tags: [trus, audit, mvp, spec, gap-analysis]
status: open
created: 2026-07-02
updated: 2026-07-02
sources:
  - "Generative-Workspace repo @ commit a41ceb1 (2026-07-02)"
  - "[[trus-brief]] (Trus Comprehensive Project Brief)"
---

> **NON-CANONICAL MIRROR.** Canonical copy: `janus-brain/20-TRUS/spec/mvp-gap-audit-2026-07-02.md`.
> Vault wins on conflict.

# Trus MVP Gap Audit — 2026-07-02

**Method:** 36-agent audit workflow — 5 dimension auditors (backend, frontend, testing, security, performance) + 15 brief-pillar gap analysts, every pillar verdict adversarially verified by an independent second agent, plus a completeness critic. ~2.6M tokens, 840 tool calls. All statuses below are the *verified* (post-refutation) statuses; every claim carries file:line evidence in the underlying run.

**Repo:** `Downloads/Generative-Workspace` (the canonical-codebase question from [[_BRAIN]] open threads is still unresolved — but this repo is by far the most advanced build).

---

## Executive verdict

The repo is a **genuinely strong single-user local demo of the deterministic-rendering core** — the one pillar the brief calls "module generation" is verifiably DONE (30 typed components, decompose→preview→accept→refine, retry + offline fallback, 78% line coverage). It is **not yet the product the brief describes**, and **it cannot host the 50-user alpha in its current form**: no identity, no deployment path, an event loop that freezes for every user whenever one user generates, and several silent data-loss paths.

The brief's three claimed differentiators are, in code:
- **Last-mile actionability** (THE differentiator) → **0% built.** Zero external API surface of any kind.
- **Hybrid LLM/SLM routing** (the moat) → **not implemented.** One model does everything; scaffolds exist (dead `decode_intent`, documented-but-unbuilt escalation thresholds).
- **Vector-DB user memory** → **absent** — deliberately deferred per `docs/llm-research-report.md` (SQLite + brute-force cosine is fine at alpha scale), but there is *no user memory of any kind*, vector or not.

## Scoreboard (verified)

| Pillar (brief) | Status | Effort* | One-line gap |
|---|---|---|---|
| Module generation | ✅ **DONE** | M (hardening) | Works end-to-end; needs referential-integrity validation + 2 crash-path fixes |
| Voice ingestion | 🟡 partial | M | Web Speech dictation only (Chrome-only, no ramble, no audio path, no STT backend) |
| Document upload | 🟡 partial | S | Works on Gemini only; local/Ollama providers silently degrade to stub templates |
| Sketch input | 🟡 partial | M | Vision→ModuleConfig backend exists (capture engine); zero drawing tools on canvas |
| Idea generation | 🟡 partial | M | Preview→confirm + clarifying questions work; no rationale, no suggestions, no conversation memory, multi-question chain drops answers |
| Spatial canvas (nesting) | 🟡 partial | L | Pan/zoom/minimap/viewport-memory solid; nesting is sidebar-only — invisible on canvas; parent-delete orphans subpages |
| Blank-canvas entry | 🟡 partial | M | Splash + rotating phrases + starter chips exist; context-aware suggestions entirely absent; voice-optional not voice-first |
| Hybrid LLM/SLM routing | 🟡 partial | M | Provider abstraction + cascade exist; no tiering, no complexity routing, no escalation, no telemetry |
| Memory / user context | 🟡 partial | M | Semantic cache is a *generation* cache (global, arguably anti-personalization); no user memory, no identity to attach it to |
| Cross-module sync | 🟡 partial | M | Render-time recompute only; 3 racing debounced writers; two tabs = silent data loss; O(N²) per pointer event |
| Auth & accounts | 🟡 partial | M | Anonymous 1-year cookie; no users, no cross-device, no gating, forgeable default secret |
| Community/template library | 🟡 partial | M (defer most) | Global layout library + seed pool exist as *accidental* shared stores; no identity/consent/sharing UX |
| Reliability (daily use) | 🟡 partial | L | Undo/versions/snapshots exist; event-loop freeze, silent save failures, unconfirmed deletes, non-atomic restore |
| Last-mile actionability | ❌ **MISSING** | L | No external data/API surface at all; schema cannot even express "live value" |
| Deployment / alpha readiness | ❌ **MISSING** | M | Zero hosting artifacts; CORS/cookie hardcoded local; "Supabase backend" in brief is a category error (won't host FastAPI; db.py is 770 lines of raw sqlite3) |

\* S=hours · M=1–2 days · L=3–5 days · XL=1–2 wks — per-pillar *MVP-scoped* recommendation, not full brief scope. Sum ≈ **25–35 dev-days** if everything is built → scope must be cut deliberately (that's what the grill + spec are for).

## The 7 structural findings (cross-cutting — these, not features, are the real blockers)

1. **One shared trust domain.** No identity anywhere; `gen_cache` and `layout_library` are global *by design*. Hosted as-is: user A's prompts (with prefilled personal state) replay verbatim into user B's workspace at ≥0.93 similarity; any anonymous caller can delete/poison the shared seed pool. Fine locally, disqualifying hosted.
2. **The event loop blocks on every model call.** LLM/vision calls are sync urllib inside `async def` handlers (60–180s timeouts, ×retry ×cascade). One generation freezes health checks, saves, and canvas loads for **all** users — worst single defect for a 50-user alpha. Fix is small (sync `def` → threadpool, or `run_in_threadpool`).
3. **Silent degradation everywhere.** Provider cascade silently swaps stub templates for real generations **and stores them in the semantic cache** — a transient Ollama outage permanently poisons the prompt's cache entry. Stub-mode refine is a silent fake success (200 + "Refined" toast, nothing changed). Debounced saves swallow failures (console.error only) → user keeps editing unsaved work.
4. **No schema versioning for persisted configs** (critic's top find). Every stored blob — modules, versions, snapshots, seeds — is strict-validated against the *current* Pydantic schema on every read, no `schema_version`, no per-row tolerance: one breaking change to the 30-type union bricks every existing workspace (one bad row 500s the whole `GET /api/modules`).
5. **Zero observability.** No logging import in the entire backend, no error tracking, no analytics, token usage discarded. The alpha gate ("50 users daily") is **unmeasurable**, silent degradations are invisible, and cost-per-generation is unknowable.
6. **Data-loss races in the client.** Three independent debounced writers (Module, Inspector, Canvas) each PATCH the *whole* config — edit-then-drag inside 400ms snaps position back; two tabs = last-writer-wins wipe; refine (60s) clobbers edits made while waiting. No optimistic concurrency, no confirm on page-delete (cascades all modules), snapshot restore is non-atomic and mints new UUIDs (breaks bindings).
7. **Quality gates are red at HEAD.** 1 failing test committed on main (archetypes drift), repo-root coverage gate fails (74.67% < 80%), mypy 2 errors, ESLint 42 errors (blocks nothing — Next 16 no longer runs it in build), frontend has zero tests, CI has no frontend job.

## Per-pillar MVP recommendations (verified, condensed)

- **Voice (M):** keep Web Speech for commands; make it ramble-capable (continuous + append + auto-submit to preview flow); add MediaRecorder→one new `/transcribe` endpoint (Whisper via existing provider seam) as the real path. Zero voice tests today.
- **Documents (S):** add server-side text extraction (pypdf + plain-text decode, ~10 lines + 1 dep) so local providers stop silently degrading; fix the file-path clarifying-question silent drop; don't build a document store.
- **Sketch (M):** don't build a drawing suite. Transparent stroke overlay on the canvas → export bounding-box PNG → the *existing* vision→ModuleConfig capture path; retune CAPTURE_SYSTEM prompt for hand-drawn input.
- **Idea generation (M):** emit a `plan` rationale with proposals; fix the multi-question answer-dropping bug; feed conversation history into generation; surface suggestions (see blank-canvas). `archetypes.py` (dead 358-line intent decoder) is either wired in or deleted.
- **Module generation hardening (M):** ModuleConfig model_validator for id uniqueness + dangling refs (`bound_to`, `source_component_id`, automation ids, button target); fix refine/insights 500s on ClarifyingQuestion; stop caching cascade fallbacks.
- **Spatial canvas (L):** page-portal tiles on the parent canvas (title + cheap bounding-box thumbnail) + drag-to-nest in sidebar (PATCH already exists, no API change) + fix orphaned-subpage bug. Skip true recursive canvas (XL, low payoff at alpha).
- **Actionability (L):** read-only **live-value binding**, not task execution: `data_source: {provider, params, refresh_secs}` on Metric/Kpi/Chart/Gauge, one keyless proxy route (Open-Meteo weather first), orchestrator prompt taught to emit it, small frontend refresh loop. Proves "the box WITH the engine" honestly at demo scale.
- **Blank canvas (M):** `GET /api/suggestions` from gen_cache hits + messages (needs its own query — `cache_rows` omits hits/created_at); voice affordance on the splash; decide on the exact entry-gate copy/mechanic vs. brief ("Tell me what's on your mind" appears nowhere).
- **Routing (M):** task-type tiering on existing plumbing — a `TRUS_LLM_SMALL_*` slot, tier param on `llm.generate()`, escalate-on-validation-failure (documented in `docs/llm-research-report.md:20` but unbuilt), basic per-call telemetry (model, latency, tokens). Makes the pitch's moat claim *honest*.
- **Memory (M):** skip Pinecone/Weaviate at alpha scale (documented decision, correct). `user_memory` table + embedding retrieval into the orchestrator prompt; **prerequisite: identity**.
- **Sync (M):** skip WebSockets. Four surgical fixes: optimistic same-tab bubbling; single-writer persistence per module (layout-only vs state-only patches); React.memo + memoized crossModuleValues (currently O(N²) per pointermove); namespace metric aggregation by module. Two-tab safety via version/etag check on PATCH.
- **Auth (M):** invite-link identity on existing session plumbing — `users` table, 50 pre-provisioned signed single-use invite URLs, `user_id` on session. No passwords/OAuth/email infra. Also fixes: per-user scoping of cache/library, DAU measurement, spend attribution.
- **Deployment (M):** drop "Supabase backend" from the architecture story. Backend → Fly/Railway/Render (15-line Dockerfile, persistent volume, `TRUS_DB_PATH` override exists); frontend → Vercel (builds clean; `NEXT_PUBLIC_API_BASE` is the only seam); env-driven CORS + `https_only` cookie + real `SESSION_SECRET`; WAL + busy_timeout on SQLite.
- **Community library (defer):** no commissions/credits/marketplace at alpha (no user model). Cheapest intentional version: display-name on session + "add to canvas" from the studio library (insert endpoint already exists, UI-wiring only).
- **Reliability (L):** the "never lose work, never freeze" pass — threadpool fix, WAL, save-status indicator with retry + beforeunload flush, confirm-or-trash on deletes, atomic UUID-preserving snapshot restore, React error boundary, data export.

## Critic blind spots (now on the record)

- **Mobile/touch:** pointer-only canvas, wheel-only zoom (and the wheel `preventDefault` is a no-op under React 17+ passive listeners — zoom-blocks page scroll), no pinch. For a student cohort this is a **go/no-go scope decision**, not a polish item.
- **Accessibility:** zero keyboard access to canvas/modules, no dialog semantics on any overlay; only `prefers-reduced-motion` is handled.
- **Generation-quality eval harness:** prompt→config quality IS the product; the only live-model tests are permanently skipped; prompt edits ship with zero regression protection. No golden-prompt set, no schema-validity/refusal-rate tracking.
- **Privacy posture:** a personal OS holding health/mood/finance data stores everything plaintext, ships every prompt to Gemini or an arbitrary endpoint, with no consent surface or privacy policy — and the brief *sells* privacy as a B2B asset.
- **Licensing:** no LICENSE file; GSAP's non-OSI license needs a check before "community library" ever ships; no terms concept for user-submitted templates.
- **Cost economics:** docs price providers, code discards usage — per-user scoping of the cache (required for privacy) *multiplies* LLM spend; nobody can currently compute cost-per-generation.

## Quality-gate snapshot (HEAD = a41ceb1)

| Gate | State |
|---|---|
| Backend pytest | **1 failed** (test_archetypes.py — committed red), 151 passed, 2 skipped (live-model pair) |
| Coverage | 78% line (backend config) / **74.67% branch — FAILS the 80% repo-root gate** |
| mypy | **2 errors** (capture.py:33/35) |
| tsc --noEmit / next build | ✅ clean (build verified passing) |
| ESLint | **42 errors** (enforced nowhere) |
| Frontend tests | **0** (no framework, no CI job) |
| Dead code | ~430 backend lines (archetypes.py + orchestrator single-module path) + GenerationBeam.tsx |

## What this feeds

1. **The full spec sheet** → `20-TRUS/spec/` (this folder), per [[_README]]: product/MVP spec distinct from the website spec. The spec must make the *deliberate* calls this audit surfaced: MVP pillar cut-line, mobile in/out, actionability depth, routing honesty, identity model, hosting target.
2. **The grill** → stress-test the scope decisions before planning.
3. **/ultraplan** → the implementation attack plan, sequenced against the structural findings first (trust domain, event loop, silent degradation, schema versioning, observability) since every feature builds on them.

## Related
- [[trus-brief]] · [[_BRAIN]] · [[product]] · [[architecture]] · [[deterministic-rendering]] · [[hybrid-LLM-SLM-routing]] · [[last-mile-execution]] · [[blank-canvas-problem]] · [[semantic-cache]] · [[trusted-component-library]]
- Full machine-readable audit: session task output `wtzr2ipmt` (252KB, per-finding file:line evidence)
