# V2 build — HANDOFF / resume checkpoint

> Written 2026-07-06/07 to let a fresh session (different window, reset context)
> pick up this autonomous build exactly where it stands. Read this file first,
> then VISION.md → VISION-DOD.md → docs/superpowers/plans/v2/DESIGN-RECONCILED.md
> if you need the architecture again.

## What this is

An autonomous, uninterrupted run turning Trus (Stages 1-4, shipped on `main`)
into the V2 vision in `VISION.md`: a self-composing, always-on personal OS. The
full run brief (mission, operating mode, exit condition, methodology) is long —
if it's not in this session's context, it was recovered from
`~/.claude/history.jsonl` (search for "Do not end on a promise of work not done"
— that's the tail of the brief) in the session that started this build. The
short version: build until every `VISION-DOD.md` criterion is met or honestly
seamed, never stop to ask, never end on a promise of undone work.

## Repo / branch state (verify with `git log --oneline -3` and `git status`)

- Repo: `/Users/Diego/Generative-Workspace`, branch `V2`.
- HEAD as of this checkpoint: `a20559f` ("V2 self-composing structure of
  surfaces (SURF/ONB-1)"). Working tree clean. `origin/V2` is caught up to this
  commit (pushed) — **verify this hasn't drifted** with `git log origin/V2..V2`.
- All commits present, oldest-to-newest: VISION-DOD.md → the 4 council design
  docs + DESIGN-RECONCILED.md → Pulse (frontend) → trust-spine (backend) →
  sharing (backend+frontend) → surfaces (backend+frontend).

## Build status — all 6 build waves are DONE and gates are green

| Wave | What | Status | Evidence |
|---|---|---|---|
| A1 | Backend: always-on runtime + tiered autonomy (scheduler, actions, approvals, activity, routes) | ✅ done | 796 backend tests (was 665), mypy/ruff clean |
| F1 | Frontend: Pulse ("what happened / needs your tap") panel + badge | ✅ done | 140 frontend tests (was 123) |
| A2 | Backend: per-surface read-only sharing | ✅ done | 818 backend tests |
| F3 | Frontend: sharing (SharePanel, `/share/[token]`, Module "shared" variant) | ✅ done | 150 frontend tests |
| A3 | Backend: self-composing structure generation (Feed component, orchestrator STRUCTURES prompt, `/api/structure`, `/api/pages/overview`) | ✅ done | 842 backend tests (final), 93.68% coverage |
| F2 | Frontend: app-like zoomable surfaces (PortalTile, zoom-launch transition, AppFrame, Feed primitive, structure proposal card) | ✅ done | 163 frontend tests (final) |

**Full-tree gate re-verification I ran myself after all waves landed** (not
just trusting agent reports):
```
.venv/bin/python -m pytest -q         → 842 passed, 2 skipped, 93.68% coverage (gate 80%)
.venv/bin/python -m mypy backend/src  → Success: no issues found in 39 source files
.venv/bin/python -m ruff check backend/src         → All checks passed!
.venv/bin/python -m ruff format --check backend/src → 39 files already formatted
cd frontend && npm test               → 14 test files, 163 tests passed
npx tsc --noEmit                      → clean
npm run build                         → ✓ Compiled successfully
```

**Integration smoke** (`/private/tmp/claude-501/-Users-Diego/3f506130-7d84-4e90-b40b-abab2a56581b/scratchpad/smoke_v2.py`
— reusable, spins up an isolated backend on :8123 with a temp DB, exercises the
whole spine): **24/24 passed** — automation create/run-now/track-writes-series,
dial-0 parks + approve executes, hard-floor (send_email) always parks + approve
is an honest simulated stub, cross-owner isolation on automations/approvals,
share create/public-read/revoke, structure preview(stub)/confirm creates real
automations. Also separately proved the **scheduler thread fires with zero
HTTP requests involved** (backdated `next_run_at` directly in sqlite, waited
past several ticks, read `activity`/`modules` tables directly) — this is the
hardest-to-fake criterion (RUN-1) and it's for-real.

All deviations reported by build agents were reviewed and accepted (documented
inline in each commit + in `docs/LESSONS-v2.md`). Nothing outstanding from the
build waves themselves.

## What's currently in flight (check before restarting anything)

1. **Two isolated dev servers may still be running** for manual/browser
   verification — spare ports, throwaway DB, the user's real `:8000`/`:3000`
   and `trus.db` were never touched:
   - Backend: `uvicorn src.main:app --port 8125` (env: `TRUS_DB_PATH=.../scratchpad/drive.db`,
     `TRUS_LLM_PROVIDER=stub`, `TRUS_RUNTIME=1`, `TRUS_RUNTIME_TICK_SECS=5`,
     `TRUS_ALLOW_ANON=1`, `TRUS_CORS_ORIGINS=http://localhost:3001`).
   - Frontend: `NEXT_PUBLIC_API_BASE=http://localhost:8125 npm run dev -- -p 3001`.
   - Check with `ps aux | grep -E "uvicorn|next dev"`; kill both before touching
     the real dev ports if you don't need them, or reuse them — they're clean.
2. **A `Workflow` verification run may be mid-flight or finished**: 5
   fresh-context adversarial verifier agents checking every `VISION-DOD.md`
   criterion against real evidence (tests they read the body of, code paths,
   or curling the live :8125 backend). Run ID `wf_e238591d-1f9`. Check status:
   ```
   ls /Users/Diego/.claude/projects/-Users-Diego/3f506130-7d84-4e90-b40b-abab2a56581b/subagents/workflows/wf_e238591d-1f9/
   ```
   If it has a `result` entry per cluster in `journal.jsonl`, it's done — read
   the journal for the verdicts (5 clusters: RUN, AUT+TAP, ONB+SURF,
   PROF+SHARE, SEAM+ETHOS+GATE). If not, resume/re-launch with:
   ```
   Workflow({scriptPath: "/Users/Diego/.claude/projects/-Users-Diego-Generative-Workspace/3f506130-7d84-4e90-b40b-abab2a56581b/workflows/scripts/vision-dod-verify-wf_e238591d-1f9.js", resumeFromRunId: "wf_e238591d-1f9"})
   ```
   (It failed once already on a session-limit error with 0 agents completing —
   that run is cached-empty, a resume will just re-run all 5 fresh.)
3. **Two teammate agents are idle and available**, holding useful context —
   prefer resuming them over spawning fresh ones:
   - `A1-backend-spine` — built all 3 backend waves, knows the schema/services/routes cold.
   - `F1-pulse-frontend` — built all 3 frontend waves (yes, one agent did Pulse,
     then was re-tasked for surfaces after the sharing-frontend agent finished;
     `F3-sharing-frontend` also exists/finished and may still be idle).
   Resume via `SendMessage({to: "A1-backend-spine", message: "..."})` etc.

## What's left (in order)

### 1. Task #9 — Design-ethos motion + polish pass (NOT STARTED)
Run the DESIGN-ETHOS.md §10 checklist for real against every new surface:
Pulse panel/cards/badge, SharePanel/SharedSurface, PortalTile/AppFrame/Feed,
the structure proposal card. Concretely check (don't just read code — load the
running app and look, or grep + reason if the browser is unavailable):
- Charcoal stack, exactly one magenta per screen, Geist Mono on data registers,
  muted status colors (note: a new `--status-hold`/`--status-hold-dim` amber
  token was added for held/needs-tap — confirm it reads as muted, not neon).
- Construction-not-fade motion on every new surface (Pulse rows use the new
  `lib/useAssembly.ts` helper; PortalTile/Feed use it too per F2's report) —
  and a **complete, correct reduced-motion static end-state** for each.
- Sentence case everywhere, no title case slipped in.
- The zoom-launch transition (F2's biggest new motion) — verify visually if at
  all possible; F2 self-reported one deviation (reverse-view source is
  `lastSavedViewRef` not `latestViewRef`, verified by effect-ordering reasoning,
  not a live click-through) — this is the single highest-value thing to
  actually click through in a browser if you can get one connected.

### 2. Task #10 — Finish the full verification sweep
- Read the VISION-DOD verifier workflow results (see "in flight" above) and
  fix any real gaps it finds. Don't accept a finding at face value — these are
  adversarial-verifier claims; spot-check anything surprising the way you'd
  scrutinize a build agent's report.
- **Browser drive was blocked** last attempt: the Claude-in-Chrome extension
  reported "not connected" (`mcp__claude-in-chrome__tabs_context_mcp` failed
  twice). If a fresh session has a working browser connection, drive the app
  at `http://localhost:3001` (against the isolated `:8125` backend above, or
  spin up fresh ones) through the golden path: EntryScreen → a broad prompt
  ("organize my whole life") → structure proposal card → confirm → portals
  construct on canvas → click a portal → zoom-launch into it → AppFrame chrome
  → back → Pulse panel (create/run an automation, approve/reject) → SharePanel
  (create a link, open it in a fresh/incognito-style tab or curl it) → check
  console for errors throughout. If the browser genuinely can't be connected,
  say so explicitly in the closeout rather than claiming it was checked —
  code-level + API-level evidence (already gathered) is the fallback, not a
  substitute for the real thing when it's available.
- Build the **VISION-DOD.md pass table**: walk all 40 criteria, mark
  met / met-seam / partial / unmet, one line of evidence each (a test name +
  what it asserts, an API response, a screenshot observation). This table is
  required content for the closeout (task #11).

### 3. Task #11 — Closeout
Per the original brief's exact required shape (re-read it if unclear — see
"What this is" above): a plain summary, outcome-first, complete sentences,
written as if the user did not watch the work happen. Must include:
- What Trus V2 now does that Stages 1-4 didn't (self-composing structures with
  real wired automations; the always-on scheduler; the tap surface; app-grade
  zoomable portals; per-surface sharing).
- The VISION-DOD.md pass table (see above) with evidence per row.
- Which VISION.md capabilities are fully live vs. built-to-the-honesty-seam
  and why. **Known seam items** (confirmed real, not faked): `send_email`,
  `message_human`, `pay` all park at every trust-dial position (hard floor,
  AUT-4) and their "approve" path is an honestly-badged simulated stub — no
  real credentials, no real sends, exactly per the brief's "genuinely
  irreversible real-world action" prohibition.
- The **"needs you" list** — human-only items requiring real credentials/paid
  accounts/live deploy. So far, identified: (a) a real LLM provider key
  (Gemini or an OpenAI-compatible endpoint) to move off `TRUS_LLM_PROVIDER=stub`
  for actually-generated (not templated) structures/digests/drafts; (b) real
  email/messaging/payment credentials if send_email/message_human/pay are ever
  to execute for real (currently correctly stubbed, not blocking); (c) the
  Stage-4 Task 10 operator deploy (Fly/Railway + Vercel accounts) — pre-existing,
  not new to V2; (d) STT keys for voice (pre-existing Stage-2b item, unaffected).
- Anything still open (there should be nothing "buildable but undone" left by
  the time you write this — if there is, go build it first per the brief).

## Key files to re-ground in, if needed

- `/Users/Diego/Generative-Workspace/VISION.md` — the spec.
- `/Users/Diego/Generative-Workspace/VISION-DOD.md` — the 40-criterion contract.
- `/Users/Diego/Generative-Workspace/docs/superpowers/plans/v2/DESIGN-RECONCILED.md`
  — the authoritative architecture (rules over the 4 individual DESIGN-*.md
  fork docs where they conflict).
- `/Users/Diego/Generative-Workspace/docs/superpowers/plans/v2/DESIGN-{runtime,autonomy,surfaces,sharing}.md`
  — the detailed per-fork specs the builds followed.
- `/Users/Diego/Generative-Workspace/docs/LESSONS-v2.md` — ~15 accumulated
  gotchas from every wave (read before making changes — several are load-bearing,
  e.g. the containing-block issue, the amber token, `Date.now()` purity).
- `/Users/Diego/Generative-Workspace/DESIGN-ETHOS.md` — §10 is the checklist
  for task #9.
- `/Users/Diego/Generative-Workspace/STATUS.md` — the pre-V2 (Stage 1-4)
  status doc; update it as part of closeout if the user's conventions expect
  that (check how VISION.md / prior STATUS.md entries reference each other).

## Do NOT

- Don't re-run the design council or re-derive the architecture — it's done
  and reconciled; DESIGN-RECONCILED.md is binding.
- Don't re-build any of the 6 waves — they're done, tested, committed, pushed.
- Don't touch `main` or the user's real `:8000`/`:3000` dev servers/`trus.db`.
- Don't provision real credentials, spend real money, deploy live, or send
  real messages — those stay in the "needs you" list per the brief's own rule.
- Don't end a turn on a promise of work not done — if you can build it, build
  it; only the closeout's "needs you" list should contain undone-but-real items.
