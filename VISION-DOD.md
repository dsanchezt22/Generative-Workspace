# VISION-DOD — the measurable definition of done for Trus V2

> Derived from `VISION.md` (the spec) on 2026-07-06. This file is the contract the V2
> build loops against: every criterion is checkable by **running something** (a test, a
> command, an API call) or **looking at the real app**. A criterion is *met* only when
> the evidence exists in this run. Criteria that require a human-only resource (real
> credentials, paid accounts, a live deploy) are marked **[seam]**: they are done when
> the full interface exists and the executor is honestly stubbed + badged, never faked.
>
> Verification legend: `T:` pytest/vitest test · `A:` API call against a running
> backend · `B:` browser observation of the running app · `C:` command output.

---

## 1. RUN — the always-on per-user runtime (the literal OS)

- **RUN-1** A per-owner runtime exists inside the backend: automations persist in an
  owner-scoped store and a scheduler ticks them while the server runs, with no browser
  open. `T:` scheduler unit tests. `A:` create an automation, wait past its interval (or
  advance fake time in tests), observe a run recorded with no frontend involved.
- **RUN-2** Automations fire on a schedule (interval/daily) and their every execution is
  journaled (started/finished/outcome/produced-what) in an owner-scoped activity log.
  `T:` runner writes activity rows. `A:` `GET /api/activity` shows the run.
- **RUN-3** The runtime survives restarts: after a server restart, due automations still
  run and none double-fire catastrophically (catch-up policy is deliberate and tested).
  `T:` restart-simulation test.
- **RUN-4** A crashed automation never takes the runtime down: an executor exception is
  journaled as a failed run, the loop continues, and repeated failures back off.
  `T:` failure-isolation test.
- **RUN-5** Per-owner isolation holds: owner A's automations, runs, approvals, and
  activity are invisible to owner B. `T:` cross-owner isolation tests (the Stage-1
  pattern). `A:` two-user smoke.
- **RUN-6** "You open it to see what already happened": with the app closed, an
  automation produces a visible result (e.g. a digest written to a surface, a tracked
  value appended); opening the app shows it without any user action. `A+B:` drive it.

## 2. AUT — tiered-by-reversibility autonomy (the trust spine)

- **AUT-1** Every automation action carries a reversibility tier: **autonomous**
  (watch/sort/track/summarize/draft — executes immediately) vs **consequential**
  (send/pay/message-a-human/delete — parks as a pending approval, never executes
  without a tap). `T:` tier-routing tests on the engine.
- **AUT-2** A consequential action creates a pending approval with a legible
  description of exactly what will happen; **approve** executes it, **reject** discards
  it; both are journaled. `T:` approval lifecycle tests. `A:` approve via
  `POST /api/approvals/{id}/approve` and observe execution.
- **AUT-3** The per-automation **trust dial** exists: the user can raise/lower autonomy
  per automation (e.g. "drafts only" → "auto-send internal"), the dial persists, and the
  engine respects it on the next run. A tier can never be raised by the system itself.
  `T:` dial tests incl. "system cannot self-raise". `B:` dial visible + adjustable.
- **AUT-4** Hard floor: real-world irreversible executors (send to a human, pay, delete
  user data) can **never** run autonomously in this build regardless of dial position —
  they always require the tap. `T:` floor test.

## 3. TAP — "what it did / what needs your tap" is first-class and legible

- **TAP-1** One surface shows, per owner: recent activity (what ran, when, what it
  produced) and pending approvals (what wants to act, exactly what it will do), in plain
  language, newest first. `B:` open the surface. `A:` `GET /api/activity`,
  `GET /api/approvals`.
- **TAP-2** Approving/rejecting is one tap from that surface, with optimistic UI and an
  honest failure state. `B:` tap approve, watch the action execute and journal.
- **TAP-3** The surface distinguishes, at a glance (badge/register, per design ethos):
  ran-autonomously · needs-your-tap · approved-and-executed · failed. `B:` look.
- **TAP-4** An unopened-approvals indicator is visible from the canvas home (the user
  can't miss "something needs me"). `B:` look.

## 4. ONB — the self-composing interface (setup burden is the product)

- **ONB-1** One plain-language prompt (the same entry the interview/voice/sketch paths
  feed) can yield a proposed **structure**: multiple app-surfaces (pages with modules)
  plus wired automations — not a single widget. The proposal is previewed and confirmed
  before anything lands. `T:` orchestrator structure tests (stub provider). `A:` generate
  → structure proposal → confirm → pages+modules+automations exist.
- **ONB-2** The proposal is honest and curated: it says what each surface is for and
  what each automation will do + at what tier; nothing lands that wasn't shown.
  `B:` read the proposal.
- **ONB-3** The confirmed structure is spatial: surfaces land as portals on the canvas
  home (the personal-OS home screen), expandable/refinable afterwards in plain language.
  `B:` see portals appear; refine one.
- **ONB-4** The profile feeds composition: with profile facts present, the composed
  structure reflects them (and the semantic cache key stays profile-independent, the
  Stage-3 contract). `T:` profile-block test on the structure path.

## 5. SURF — app-like zoomable surfaces (no more trivial widgets)

- **SURF-1** A generated surface can be a full multi-module **app view**: entering its
  portal is a spatial zoom (not a hard cut) into a page-level surface with its own
  layout of modules — DOS-grade, not a lone card. `B:` zoom in/out. 
- **SURF-2** The ModuleConfig/trusted-component contract holds: everything new renders
  through typed configs + the trusted library; no model-authored markup anywhere.
  `T:` schema validation tests. `C:` grep — no dangerouslySetInnerHTML on generated
  content paths.
- **SURF-3** Surfaces can be **backed by the runtime**: a surface shows what its agent
  did (e.g. a digest module fed by an automation run) with live/API badging per the
  honesty seam. `A+B:` drive one end-to-end (automation run → surface shows product).
- **SURF-4** Canvas identity holds: dotted-grid texture, GridIcon stamp, charcoal stack
  on every new surface. `B:` look.

## 6. PROF — the sandbox + accreting profile (the moat)

- **PROF-1** Automations read the profile: at least one automation's behavior visibly
  differs based on stored profile facts. `T:` profile-read test.
- **PROF-2** Automations write back: runs can accrete owner-scoped facts/patterns
  (source-tagged, capped, deduped — the Stage-3/4 store), and ProfilePanel shows them.
  `T:` accretion-from-run test. `B:` ProfilePanel.
- **PROF-3** The user stays sovereign: every profile fact remains editable/deletable and
  clear-all still works with the new sources present. `T:` existing profile CRUD suite
  stays green.

## 7. SHARE — personal-first, shareable surfaces

- **SHARE-1** A single surface (page) can be shared read-only via an unguessable link,
  scoped to exactly that surface — never the whole workspace, never the profile, never
  approvals. `T:` share-scope tests (path traversal to other pages/owners 404s).
  `A:` share → fetch as anonymous → see only that surface.
- **SHARE-2** Sharing is opt-in per surface, revocable, and its state is visible on the
  surface. `T:` revoke test. `B:` share affordance + revoke.
- **SHARE-3** The shared view is read-only: no mutation route accepts the share
  credential. `T:` mutation-refusal tests.

## 8. SEAM — the honesty seam (nothing fabricated, ever)

- **SEAM-1** Every real-world executor that needs human-only resources (send email,
  message a human, pay, connect a credentialed account) exists as a **real interface +
  clearly-stubbed executor**: the UI shows exactly what would happen, output is badged
  as draft/simulated, and nothing claims success it didn't have. **[seam]**
  `B:` inspect each. `T:` stub executors marked + tested.
- **SEAM-2** Live data keeps the Stage-3 contract on every new surface: real fetch or
  honest stale/error — never fabricated values; `TRUS_LIVE_DATA=off` degrades to manual
  entry. `T:` existing live suite green + new-surface variants.
- **SEAM-3** Failed automation runs are shown as failures in the activity surface (no
  silent degradation). `T:` failure-visibility test. `B:` look.

## 9. ETHOS — design-ethos conformance (the §10 checklist, run for real)

- **ETHOS-1** New surfaces **construct themselves** (seed → border/fill → settle in the
  module-assembly shape), never merely fade. `B:` watch a surface generate.
- **ETHOS-2** One magenta primary action per screen; charcoal stack; off-white text;
  muted status colors; Geist Mono for data/state registers. `B:` inspect each new
  surface against §10.
- **ETHOS-3** A complete reduced-motion static end-state exists for every new motion.
  `B:` toggle prefers-reduced-motion.
- **ETHOS-4** The a11y floor holds on new surfaces: dialog semantics, focus management,
  keyboard reachability (the Stage-4 R-1306 patterns). `T:` where testable. `B:` tab
  through.

## 10. GATES — the regression floor (V2 is a ceiling-raise, not a trade)

- **GATE-1** `python -m pytest -q` green with the 80% branch-coverage gate ON.
- **GATE-2** `mypy backend/src` clean. **GATE-3** `ruff check` + `ruff format --check`
  clean. **GATE-4** `cd frontend && npm test` green. **GATE-5** `npx tsc --noEmit`
  clean. **GATE-6** `npm run build` clean.
- **GATE-7** The Stage 1–4 behavior contracts still hold (owner isolation, honesty
  seam, rate/cost limits, a11y, backup) — their suites run green untouched.

---

### Deliberately out of scope for this run (recorded, not forgotten)

Live deploy (Stage-4 Task 10, operator-only) · real credential connectors (Gmail/
calendar/bank OAuth — **[seam]** only) · payments · multi-machine per-user runtimes
(the single-machine constraint from `deploy/README.md` stands; the per-owner runtime is
logical, not physical, in this build) · GTM/pricing (out of scope per VISION.md itself).
