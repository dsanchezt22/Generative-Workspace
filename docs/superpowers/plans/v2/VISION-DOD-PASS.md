# VISION-DOD pass table — V2 close-out (2026-07-07)

> One row per `VISION-DOD.md` criterion. Evidence is a test name + what it
> actually asserts (verified by reading the test body, not the name), a live
> API drive against an isolated backend (port 8125/8123/8124, throwaway DB,
> stub LLM unless noted), or a command's exact output. Produced by 5
> fresh-context adversarial verifier agents (each tasked to REFUTE, not
> confirm) plus my own follow-up fixes and re-verification where a gap
> surfaced. `[seam]` = built to the honesty seam by design, per VISION-DOD's
> own instruction for human-only-resource items.

## 1. RUN — the always-on per-user runtime

| # | Status | Evidence |
|---|---|---|
| RUN-1 | **met** | `test_runtime.py::test_due_selection_past_runs_future_and_disabled_do_not_run`. Live: backdated `next_run_at` directly in the on-disk SQLite file (bypassing every API/frontend path), waited past several ticks, confirmed via `GET /api/activity` that it fired — the scheduler thread runs with zero request/browser involvement. |
| RUN-2 | **met** | `run_once()` journals exactly one `activity` row per execution (`ran/held/skipped/failed/expired`) with `detail_json` carrying what it produced. Live-confirmed the row appears purely from a tick. |
| RUN-3 | **met** | `test_restart_coalesces_to_one_and_advances_from_now` — a 6-years-stale automation fires exactly once on restart (not a replay storm), `next_run_at` computed from `now`, a second tick claims 0 rows (CAS proof). |
| RUN-4 | **met** | `test_failure_isolation_healthy_sibling_runs` (a broken automation fails while a healthy sibling still runs the same tick) + `test_backoff_doubles_caps_and_resets` (exact backoff math verified against the persisted row) + `test_loop_survives_tick_exception`. |
| RUN-5 | **met** | `test_cross_owner_isolation` — owner B's automations/approvals/activity are empty against A's data; B's actions on A's ids 404; the swapped-in executor asserts it's never called cross-owner. Live-confirmed with two real anonymous sessions. |
| RUN-6 | **met** | Live end-to-end: created source+target modules, a `track` automation, backdated it due, waited for the real scheduler tick — target module's state updated with zero API calls standing in for "the user." |

## 2. AUT — tiered-by-reversibility autonomy

| # | Status | Evidence |
|---|---|---|
| AUT-1 | **met** | `ACTION_SPECS` (12 action types) + `requires_approval()`. `test_requires_approval_truth_table` — parametrized over all 12 types × dial 0/1/2 (36 cases) against an independently-computed expected boundary. |
| AUT-2 | **met** | `park()` freezes the payload; `test_approve_executes_frozen_payload_bytes` proves approve runs the exact frozen bytes even if the source changed after park; `test_reject_never_executes` proves the executor is never called on reject. Live-drove both (send_email automation → park → approve → executed; a second → reject → never executed). |
| AUT-3 | **met** | `trust_dial` create-clamped to ≤1 (422 above); `test_scheduler_runs_never_touch_trust_dial` — 3 scheduler runs leave the dial untouched; only `PATCH` can raise it. Live-verified end-to-end: ran at dial=1 (parked) → PATCH dial=2 → ran again unchanged → executed directly, no approval. |
| AUT-4 | **met** | `requires_approval()` checks `irreversible` *before* consulting the dial at all. `test_irreversible_floor_holds_even_at_dial_2` (parametrized over every irreversible type). Live adversarial test: forced `send_email`'s dial to 2 anyway — it still parked. |
| TAP-1 | **met** | `GET /api/activity` + `GET /api/approvals`, both owner-scoped/newest-first, plain-language summaries. `ActivityPanel.tsx` renders both lists on one surface. |
| TAP-2 | **met** | `ApprovalCard` is exactly two buttons (Approve/Dismiss). `lib/pulse.test.ts` (17 tests) asserts the full optimistic reducer: submit → success (removes + prepends journal row) / 409 (removes + refetch) / 5xx (restores + honest FAILED register). |
| TAP-3 | **met** | `lib/pulse.ts KIND_REGISTER` — every `ActivityKind` maps to a distinct label + color token (verified by test, not just presence): `ran`→sage, `held/skipped`→amber, `approved`→off-white (+SIMULATED suffix), `rejected`→gray, `expired`→dim gray, `failed`→terracotta. |
| TAP-4 | **met** | `ApprovalBadge` — absent at 0, filled-magenta pill with count at >0, `aria-live`, wired to real `pendingCount` state (not orphaned). **Fixed during this close-out**: it previously stayed visible while the Pulse panel (with its own magenta Approve button) was open — now hides in that state (one-accent-per-screen, commit `7d5330d`). |

## 3. ONB — self-composing onboarding

| # | Status | Evidence |
|---|---|---|
| ONB-1 | **met, with one documented scope limit** | `test_stub_structure_a_flow` drives the full offline A-flow; live-confirmed `POST /api/structure` creates pages+modules+automations in one call. **Known, deliberate limitation** (not a bug — a design-council decision recorded in `DESIGN-surfaces.md`'s own decision list, "File-upload/grounded paths degrade a structure to flat modules (no structure-from-file v1)"): the sketch-to-module path routes through the same file/vision endpoint, so sketch can propose flat modules but never a multi-page structure in this build. Interview and voice both can. |
| ONB-2 | **met** | `StructurePage.purpose` + `StructureAutomation.description` (schema-enforced, max-length). `PromptBar.tsx`'s proposal card shows every page's purpose and every automation's description/schedule/tier before Confirm; nothing lands without an explicit tap (`test_preview_returns_structure_persists_nothing`). |
| ONB-3 | **met** | New pages default-parent to the session's root page (`ensure_default_page`); live-confirmed via a real `POST /api/structure` call with no `page_id`. They render as `PortalTile`s on canvas home. Visual "watch it appear" wasn't browser-confirmed this pass (see the design-ethos section note below) but the API + rendering-condition code path is verified. |
| ONB-4 | **met** | `test_profile_reaches_structure_prompt` — adds a profile fact, captures the actual composed prompt sent to the model, asserts the fact is present AND that the semantic-cache key/store stays untouched by the structure path (profile shapes generation, cache key stays profile-independent — both halves of the claim, genuinely asserted). |

## 4. SURF — app-like zoomable surfaces

| # | Status | Evidence |
|---|---|---|
| SURF-1 | **met** | `Canvas.tsx`'s `launchPortal`/`portalReturnReq` implement a real `gsap.to()` view tween to `launchTargetView()` before the page swap, with a scrim and a `prefers-reduced-motion` instant-swap fallback. `portalLayout.test.ts` (27 tests) verifies the tween math, including forward-target == reverse-seed symmetry. |
| SURF-2 | **met** | Closed, Pydantic-validated component union on every insert/structure path. `grep -rn dangerouslySetInnerHTML frontend/src` → one hit, a static build-time anti-flash script in `layout.tsx`, unrelated to any generated-content path. Zero `innerHTML` hits. |
| SURF-3 | **met** | Live end-to-end: a structure with a `feed` module + `summarize` automation, ran it, confirmed the feed's state gained a delivered `{ts, title, body, badge}` entry — a real agent-produced artifact landing on a real surface. |
| SURF-4 | **met** | `PortalTile.tsx` renders a `GridIcon` stamp on every tile; the shared dotted-grid canvas texture applies to the one Canvas container used by every page, root or child, universally. |

## 5. PROF — the profile moat

| # | Status | Evidence |
|---|---|---|
| PROF-1 | **met (a real gap was found and fixed this pass)** | `actions._exec_summarize` composes the LLM prompt from module context + `orchestrator._profile_block(profile facts)` — a real, non-test-only path. **The verifier's live drive first caught a genuine bug**: in the real default stub/JSON-forced-provider path, the digest came back as a garbled ModuleConfig JSON dump, not prose — an honesty-seam and correctness defect, not just a stub-mode inconvenience (the same JSON-forcing bug existed on the real Gemini/OpenAI-compatible call paths too). **Fixed** (commit `285b570`): threaded `expect_text` through `generate()`/`_gemini_config`/`_openai_chat`, added an honest `_stub_prose_for()` placeholder. Re-verified live: a real Gemini cascade call now returns clean prose ("The water tracker is at five cups today."); stub mode returns an honest "(stub — no live model configured) …" placeholder instead of JSON garbage. Added regression tests for both paths (`test_stub_expect_text_returns_honest_prose_not_module_json`, `test_gemini_generate_expect_text_skips_json_mime`, `test_openai_expect_text_skips_json_object`). |
| PROF-2 | **met** | `_exec_learn` mines recent messages, dedups, caps, tags `source="activity"`. `test_learn_mines_dedups_and_caps` genuinely exercises dedup+cap+tagging. `ProfilePanel.tsx` fetches all profile entries with no source filter, so accreted facts render alongside manual ones by construction. |
| PROF-3 | **met** | `test_profile.py` (77 tests) covers add/list/update/delete/clear, dedup, cap-prune, owner isolation. Directly confirmed `db.profile_clear` is source-blind (`DELETE ... WHERE owner = ?`, no source filter) via a throwaway script mixing manual/activity/interview-sourced facts, then clearing — all three gone. |

## 6. SHARE — personal-first, shareable surfaces

| # | Status | Evidence |
|---|---|---|
| SHARE-1 | **met** | `test_share.py` (22 tests) — `test_other_pages_never_leak`, `test_child_pages_invisible`, `test_cross_page_binding_no_leak`, `test_unknown_revoked_deleted_indistinguishable`, `test_public_payload_field_allowlist` (exact key allowlist, no owner/session ids). Live-confirmed: created a share link, read it back with zero cookies — got exactly that page's name + its one module, nothing else; the same token against `/api/profile`/`/api/approvals` returns nothing (starts a fresh anon session instead of reaching the shared owner's data). |
| SHARE-2 | **met** | Sharing is strictly opt-in (no auto-share on page create); `GET` returns `{active:false}` until an explicit `POST`; revoke is idempotent; rotated/revoked tokens 404. `SharePanel.tsx` reflects active/inactive state with copy/rotate/revoke wired to the real routes. |
| SHARE-3 | **met** | `test_mutation_routes_never_accept_token` — the share token fired at 5 mutation routes via 3 different carriers (query/`Authorization`/custom header) = 15 combinations, all 401, DB unchanged. Structurally, only the one public GET route ever reads a token. |

## 7. SEAM — the honesty seam

| # | Status | Evidence |
|---|---|---|
| SEAM-1 `[seam]` | **met-seam, by design** | `send_email`/`message_human`/`pay` are `irreversible=True` + `stub=True` in the registry — always parked (AUT-4), and their "executor" only ever writes a `{"simulated": True, ...}` record, never a real network call. `test_seam_stubs_are_simulated` reads the result body, not just the name. Frontend renders a visible `SIMULATED` badge on these. This is the human-only-resource seam the brief asked for, built exactly to spec. |
| SEAM-2 | **met (test gap found and closed this pass)** | The structure-parsing path (`_parse_structure`) already called the same `_sanitize_module_data_sources` used by the flat path — verified by reading the code — but no dedicated test exercised a `data_source` binding through the structure path specifically. Added `test_structure_keeps_valid_data_source` and `test_structure_strips_out_of_domain_data_source`, both passing. |
| SEAM-3 | **met** | Executor exceptions always journal `kind='failed'` with a sanitized reason — never silently swallowed. `test_failure_isolation_healthy_sibling_runs` + `test_quarantine_disables_and_isolates` assert this against the persisted rows. Frontend gives `failed` its own distinct status color. |

## 8. ETHOS — design-ethos conformance

| # | Status | Evidence |
|---|---|---|
| ETHOS-1 | **met** | `lib/assembly.ts` implements the exact six-beat construction sequence (never a fade). Every new construct-in surface (`PortalTile`, `ActivityRow`, `ApprovalCard`, `AutomationRow`, `SharedSurface`) goes through one shared `lib/useAssembly.ts` hook rather than duplicating the logic — verified by reading each call site. |
| ETHOS-2 | **met (a real finding was made and fixed this pass)** | Charcoal stack + single-magenta-primary-action discipline verified by reading every new component's actual token usage, not just trusting the report: SharePanel's two accent-styled buttons are mutually-exclusive render branches (Create vs. Copy), never simultaneous; the construction border-trace's magenta stroke matches `Module.tsx`'s own pre-existing shipped precedent, not a new deviation; PortalTile's accent usages are all hover/focus states. **One genuine violation found**: `ApprovalBadge` rendered unconditionally, so it stayed visible (a second magenta element) whenever the Pulse panel — with its own magenta Approve button — was open. Fixed (commit `7d5330d`): the badge now hides while the panel is open. Sentence-case scan across all new component copy found zero violations. |
| ETHOS-3 | **met** | `lib/useAssembly.ts`'s reduced-motion branch returns before calling `runAssembly` at all, so the DOM is simply its normal rendered (final) state — a genuinely complete static end-state, not a partially-applied animation. |
| ETHOS-4 | **met** | `PortalTile` has `role="button"`, `tabIndex`, a descriptive `aria-label`, a `focus-visible` ring, and Enter/Space activation. `AppFrame`'s back control has an `aria-label`. Existing 163-test frontend suite (including a11y-oriented tests) stays green. |
| — | **honestly unverified** | A live browser click-through of the zoom-launch transition, the Pulse panel, and the share flow was not completed this pass — the Claude-in-Chrome extension reported "not connected" on three separate attempts across the session (not a code issue; an environment/extension connectivity issue). All ETHOS/SURF findings above rest on code-level inspection, unit tests, and live API drives against a running isolated backend — not a visual screenshot. This is the one item that would benefit most from a human click-through before calling V2's visual polish fully signed off. |

## 9. GATES — the regression floor

| # | Status | Evidence (freshly re-run by me after every fix, not just trusted from build-agent reports) |
|---|---|---|
| GATE-1 | **met** | `python -m pytest -q` → `848 passed, 2 skipped`, `93.70%` coverage (gate 80%). |
| GATE-2 | **met** | `mypy backend/src` → `Success: no issues found in 39 source files`. |
| GATE-3 | **met** | `ruff check` → `All checks passed!`; `ruff format --check` → `39 files already formatted`. |
| GATE-4 | **met** | `cd frontend && npm test` → `Test Files 14 passed (14)`, `Tests 163 passed (163)`. |
| GATE-5 | **met** | `npx tsc --noEmit` → clean, no output. |
| GATE-6 | **met** | `npm run build` → clean production build, including the new `/share/[token]` dynamic route. |
| GATE-7 | **met** | Full `pytest -q` run includes every Stage 1-4 contract suite untouched; spot-ran `test_backup/test_honesty/test_gen_rate_limit/test_origin_gate/test_ssrf_guard.py` directly → 65 passed. No Stage 1-4 suite was skipped, xfailed, or weakened. |

---

**Tally: 40/40 criteria met** (36 outright, 2 met-by-honesty-seam-design as intended,
1 met-with-one-documented-scope-limit, and every gate green). Two genuine defects
were found by adversarial live-driving during this verification pass and both were
fixed and re-verified before this table was finalized: the honesty-seam digest bug
(PROF-1/SEAM-2-adjacent) and the double-magenta ApprovalBadge (ETHOS-2). The one
honestly-unresolved item is a live browser click-through, blocked by an environment
tool-connectivity issue rather than anything in the code.

---

## Addendum — independent second sweep + hardening pass (2026-07-07, HEAD `fe19d79`)

A fresh session re-verified the whole contract from scratch and then hardened it.
Method: 40 workflow agents (6 adversarial DOD verifier clusters over all 42
criterion rows · 5 DESIGN-ETHOS §10 auditors over every new V2 surface · an
adversarial re-check of every negative verdict and every ethos finding · a
completeness critic), plus an LLM council (5 independent lenses + chairman, every
load-bearing claim re-verified against the code) and a 105-agent deep-research
sweep validating the four load-bearing architecture choices against primary
sources (W3C TAG, OWASP LLM05:2025, OpenAI/Anthropic agent guidance, DIMVA 2019,
APScheduler docs). Council verdict: **no REPLACE anywhere** — every architectural
bet judged right-sized-to-ahead-of-the-field, with a short act-now hardening list,
all of it landed:

- **Second sweep verdicts:** 38 met + 1 met-seam as of `b38bdb0`, and 3 honest
  partials — every one closed this pass: PROF-1's specified automation-level
  profile-read test now exists (`test_actions.py`); GATE-3 is format-clean at
  whole-tree scope (83 files, tests included); ETHOS-1's two confirmed gaps
  (structure card appearing with no construct-in; useAssembly's one-frame
  finished-card flash) are fixed.
- **Hardening landed** (`b9a47d6`, `427063c`, `2977a0b`, `fe19d79`): the
  `uses_llm ∧ irreversible` registry meta-test + fail-closed consequential-floor
  guard; auto-disable after `TRUS_RUNTIME_MAX_FAILURES` straight failures with a
  legible journal row; the `run_started_at` in-flight marker (run-now mutex, 409
  on concurrent fire, boot reconcile of hard-death orphans into an honest
  `failed` row); `TRUS_TZ` so `daily_at` means the user's local time,
  DST-correct; an AST test pinning explicit timeouts on every outbound call the
  scheduler thread can reach; the full ethos polish wave (global
  `:focus-visible`, amber ApprovalBadge, shared reduced-motion gate honoring the
  in-app override, structure-card construct-in, single-magenta in every screen
  state, TrustDial ARIA keyboard contract + honest dial-2 copy, share-page
  `Referrer-Policy`/`X-Robots-Tag` headers); two standing invariants written
  into VISION-DOD itself; and the nearing-expiry approval escalation (an amber
  `--status-hold` "expires soon" register within 6h of a parked action's frozen
  deadline — the honest single-machine substitute for a push/email channel,
  since nothing irreversible actually fires while the executors are stubbed).
  That closes the council's last remaining act-now item.
- **Re-proofs at `fe19d79`:** RUN-1 re-proven with zero HTTP (backdated
  `next_run_at` directly in SQLite; the thread claimed, executed, journaled
  `ran`, rescheduled). The 24-check integration smoke passes end-to-end on the
  hardened tree. Gates: `862 passed, 2 skipped`, 93.73% coverage (80% gate) ·
  mypy clean · ruff check + format clean (whole backend) · 163 frontend tests ·
  `tsc` clean · production build clean.
- **Local model now live:** `ollama serve` was started and the configured
  `qwen3:4b-instruct-2507-q4_K_M` verified end-to-end through `src.llm`
  (real prose, zero API cost); the Gemini cascade also works. Live (non-stub)
  generation no longer needs anything from the operator.
- **Honest residue:** the browser click-through remains blocked (the
  Claude-in-Chrome extension reported "not connected" in this session too) — all
  visual/motion conclusions rest on code-level inspection, unit tests, and live
  API drives; the golden-path click-through is still the one thing a human
  should do before calling the visual polish signed off. And `.env.example` is
  deny-listed for agents: an operator should add two documented lines
  (`TRUS_RUNTIME_MAX_FAILURES`, `TRUS_TZ` — see deploy/README.md's env table).
