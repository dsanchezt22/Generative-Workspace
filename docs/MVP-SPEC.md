---
title: Trus MVP Product Spec — Requirements Sheet
type: wiki-page
summary: The canonical, numbered requirements spec for the full-brief Trus MVP — what the product must do and to what bar; deliberately silent on how to build it.
tags: [trus, spec, mvp, requirements]
status: open
version: 1.0
created: 2026-07-02
updated: 2026-07-02
reviewed: adversarial 5-lens panel 2026-07-02 (decision fidelity, brief coverage, requirements purity, testability, audit alignment) — 50 findings applied
sources:
  - "[[trus-brief]] (Trus Comprehensive Project Brief)"
  - "[[mvp-gap-audit-2026-07-02]] (verified repo-vs-brief audit @ a41ceb1)"
  - "Grill session 2026-07-02 (17 scope decisions, logged in [[../decisions-log]])"
mirror: "Generative-Workspace/docs/MVP-SPEC.md (non-canonical copy — this file wins on conflict)"
---

> **NON-CANONICAL MIRROR.** The canonical spec lives in the vault at
> `janus-brain/20-TRUS/spec/MVP-SPEC.md` — on any conflict, the vault copy wins.
> Edit there; re-mirror here.

# Trus MVP Product Spec (v1.0)

## 0. How to read this spec

- This is a **requirements document, not a build plan**. It defines *what* the MVP must do and the bar it must meet. Mechanisms, stacks, libraries, and model choices are the builder's to decide — except where a requirement's outcome genuinely constrains them. (Decision: grill Q11 — "no requirement for LLM/SLM build structure.")
- **MUST** = required for the MVP to be considered done. **SHOULD** = expected; skipping requires a logged reason. **MAY** = explicitly permitted, never required.
- **Priority:** `P0` = alpha-blocking (no invite goes out without it) · `P1` = required for "full-brief MVP done" · `P2` = polish within scope.
- Every requirement has an ID (`R-xxx`). Cite IDs in commits, plans, and reviews. Acceptance criteria (**AC**) are written to be testable by a non-author. **Where a requirement carries no explicit AC, the requirement sentence itself is the acceptance test and must be verifiable by a non-author as written.**
- **Traceability definition (used by R-104, R-803):** an output is *traceable* to a user's history/profile when a non-author, shown the output and the history/profile side by side, can point to the specific entry it derives from — **and** a control account lacking that entry does not receive that output under the same prompt (repeat runs if needed so profile, not sampling noise, explains the difference).
- **Scope decision (grill Q1):** this MVP is the **full brief MVP** — all three must-haves *plus* the differentiators — hosted at the end (R-906). **Cadence (Q2): quality-gated, no calendar deadline.** A stage exits only when its ACs and the engineering gates (§15) pass.

## 1. Definitions

| Term | Meaning |
|---|---|
| **Module** | A functional tool (tracker, planner, dashboard, CRM…) rendered from a typed config by the trusted component library. Never AI-written UI code. |
| **Component** | One primitive inside a module (table, chart, kanban, gauge…). The library currently has 30 types. |
| **Page** | A canvas holding modules; pages nest (§6). |
| **Workspace** | A user's full tree of pages + modules + profile. |
| **Proposal** | A previewed set of modules + a plan/rationale, awaiting user confirm/adjust/reject. |
| **Interview** | The multi-turn clarifying dialogue that turns messy input into a proposal (§3). |
| **Profile** | The explicit, user-visible memory Trus keeps about a user (§9). |
| **Alpha cohort** | The 50 hand-picked users; the success gate is daily use, measurably (§13). |
| **Reference environments** | The performance test targets named in R-1301: a laptop browser under 4× CPU throttle, plus two named phones (≤3 years old, one iOS Safari, one Android Chrome) recorded in the test doc. |

## 2. Product invariants (carry over from the brief — non-negotiable)

- **I-1.** The AI **never emits UI code**. All output is typed config rendered by the trusted component library. *(This is the one architectural invariant the spec keeps, because it is a product-safety property, not a build choice.)*
- **I-2.** Trus is **prescriptive, not just generative**: the user is never required to prompt-engineer, face an empty canvas, or design structure themselves.
- **I-3.** **Reliability beats breadth**: no feature ships that undermines "works every day."
- **I-4.** The user stays **in the driver's seat**: everything generated is editable, movable, deletable, and undoable by hand.

## 3. Entry & interview (blank-canvas problem) — `R-100`

The brief's settled solution, unified with interview mode (grill Q7 "mix", Q8 "entry = interview").

- **R-101 (MUST, P0).** A new user's first surface is a **pre-workspace entry screen**: an animated rotating prompt in the spirit of "Tell me what's on your mind," with **voice as the primary affordance** and typing as the visible secondary. It accepts input directly — it is a door, not a splash.
  **AC:** From a fresh invite, the user can start speaking or typing within one interaction. Starting voice capture takes no more interactions than starting typing, and the voice affordance is the visually dominant input control. No decorative overlay must be dismissed before input is possible.
- **R-102 (MUST, P0).** Responding starts the **interview**: Trus asks clarifying questions one at a time (typically 2–4, **never more than 4**) before proposing. Every answer is retained (multi-question chains must not drop earlier answers). The user can skip to "just build it" at any point.
  **AC:** A 3-question chain produces a proposal reflecting all 3 answers. The interview never asks a fifth question before proposing. Skip works at every step.
- **R-103 (MUST, P0).** The interview ends in a **proposal**: the previewed modules plus a short plan — *what* Trus intends to build and *why* it fits what was said. The user can confirm, adjust (in words), or reject.
  **AC:** Every proposal renders a human-readable rationale; confirm places modules; nothing persists on reject.
- **R-104 (MUST, P1).** Returning users land on their canvas. Empty states and the prompt surface offer **suggestions traceable (per §0) to that user's own usage** (prior prompts, modules, profile) — not a hardcoded list.
  **AC:** After seeded usage, at least some suggestions pass the §0 traceability test; a brand-new user sees starter suggestions clearly distinct from a veteran's.
  *(Deliberate amendment of the brief: the brief's settled version seeds suggestions from prior **similar users**; that is amended to per-user seeding for the alpha because cross-user seeding conflicts with the isolation default (R-903, R-1004) and depends on the excluded data flywheel (§16). Q8.)*
- **R-105 (SHOULD, P2).** The entry experience (voice-first interview) is re-enterable for any new empty page, not only first-run.

## 4. Multimodal input — `R-200`

### Voice (brief must-have #1; grill Q6)
- **R-201 (MUST, P0).** A user can **speak for multiple minutes** — a genuine ramble — and Trus captures all of it as input. Works on current Chrome, Safari, Firefox, and on iOS/Android mobile browsers.
  **AC:** A ≥3-minute ramble arrives intact (no truncation at pauses, no overwrite of earlier speech) on desktop Chrome, desktop Safari, desktop Firefox, iOS Safari, and Android Chrome.
- **R-202 (MUST, P0).** Voice input flows into the same interview → proposal loop as text (R-102/103). Voice is never a dead-end transcript.
- **R-203 (SHOULD, P1).** While speaking, the user gets **live feedback** (words appearing or an equivalent listening indicator) so it "feels like a therapist," per the brief. *(SHOULD, not MUST: the brief's own phrasing is aspirational — "should feel like a therapist" — and the non-negotiable core, voice as the primary affordance, is already MUST in R-101.)*
- **R-204 (MUST, P0).** Mic-permission denial and transcription failure degrade gracefully to typing, with a clear message — never a silent dead mic.

### Documents (brief: "feed real operational docs into Trus live")
- **R-211 (MUST, P0).** Uploading a PDF, plain-text, Markdown, or CSV document produces proposals **grounded in the document's actual content**. No shipped configuration may return generic templates while claiming success — if a configuration cannot ground a document, the user is told. *(Audit context: local-provider silent stub degradation is the named defect; fixing it or not shipping such configurations both satisfy this requirement.)*
  **AC:** A multi-page PDF yields proposals containing at least 3 specific facts/terms present in the document and absent from a no-document control run of the same prompt. Forcing the known degraded path yields an honest failure notice — never a silent template presented as success.
- **R-212 (MUST, P1).** The document path supports clarifying questions (today they are silently dropped) and reports unsupported file types honestly.
- **R-213 (SHOULD, P1).** Images (screenshots, photos of documents) are accepted as input to the same loop.
- **R-214 (SHOULD, P2).** Document-grounded refinement: after generation, follow-up instructions can still reference the uploaded document's content. *(If not met, the limitation must be visible to the user, not silent.)*

### Sketch (brief: first-class input; grill Q9)
- **R-221 (MUST, P1).** The user can **draw directly on the canvas**: a sketch overlay with at minimum pen, eraser, and clear.
- **R-222 (MUST, P1).** A drawn sketch can be **snapped into functional modules** through the same proposal loop (preview → confirm). The sketch is ephemeral scaffolding — it is consumed by the snap, not persisted as canvas ink.
  **AC:** A fixed set of ≥5 hand-drawn wireframe fixtures (boxes + labels, kept with the tests) each yield a proposal in which a non-author can match each labeled region of the sketch to a proposed component; at least 4 of 5 fixtures pass.
- **R-223 (MAY).** Persistent ink/annotation is out of MVP scope (§16) — the overlay exists to become modules.

### Text
- **R-231 (MUST, P0).** The existing prompt path remains: free-text prompts up to at least 10,000 characters (the ramble-transcript ceiling) flow through interview → proposal → modules.

## 5. Idea generation & module generation — `R-300` / `R-400`

### Idea generation (brief must-have #2; grill Q7)
- **R-301 (MUST, P0).** Every proposal carries a **plan/rationale** (R-103) — the "prescriptive" evidence.
- **R-302 (MUST, P0).** Generation is **context-aware**: proposals reflect the user's current canvas, recent conversation, and profile (§9). The same words from two different users may legitimately produce different structures.
  **AC:** A user with an existing "Marathon" page asking to "track my runs" gets a proposal that acknowledges/extends what exists rather than duplicating it.
- **R-303 (MUST, P1).** Multi-tool decomposition holds: a broad intent ("plan my Japan trip") proposes a coordinated *set* of modules, not one generic box.
- **R-304 (MUST, P0).** The system may **refuse honestly** (out-of-scope requests) and may **ask** (clarifying question) — and each of the three outcomes (build / ask / refuse) is presented distinctly. No crash paths on any of the three (audit: two routes currently 500 on questions).

### Module generation (brief must-have #3 — DONE per audit; these are the hardening requirements)
- **R-401 (MUST, P0).** Prompt → **functional multi-module workspace** rendered from the trusted library (existing capability, preserved under invariant I-1).
- **R-402 (MUST, P0).** **Structural validity is guaranteed**: no module reaching the canvas may contain dangling internal references (bindings, automations, button targets, summary pointers) or duplicate component ids. Invalid model output is repaired or rejected before the user ever sees it.
  **AC:** Adversarial config fixtures (dangling `bound_to`, duplicate ids, unknown refs) never render broken on the canvas.
- **R-403 (MUST, P0).** **No silent degradation anywhere in generation**: if output comes from a fallback (offline templates, degraded provider), the user sees that it did; degraded output is never stored as if it were a real generation (audit: cache-poisoning defect); a refine that did nothing must say so rather than fake success.
  **AC:** With the primary model forced down mid-session, the next generation either fails honestly or is visibly labeled as fallback — and no fallback output appears in any cache/seed store as a real generation.
- **R-404 (MUST, P1).** An AI refine landing on a module **never discards user edits** made while it ran (ties to R-602).
- **R-405 (SHOULD, P1).** **Component capability does not regress**: module structures generable at spec time remain generable, and library changes must not break previously stored modules (ties to R-1105). *(The current count, 30 types, is a proxy indicator — capability, not the number, is the requirement.)*

## 6. Spatial canvas & nested pages ("Digital Clay") — `R-500`

Grill Q13: **visible nesting** is the requirement; continuous-zoom universe is excluded (§16).

- **R-501 (MUST, P0).** An infinite pan/zoom canvas where modules are placed, dragged, and resized (existing) — and **zoom/pan works on touch devices** (pinch, drag) per the mobile decision (Q5). The current wheel-zoom defect is a named P0 fix.
- **R-502 (MUST, P1).** **Nesting is visible on the canvas**: a child page appears as a spatial object (portal) on its parent's canvas — placeable, recognizable (title + some preview of what's inside), and **enterable** (click or zoom-in). Leaving is as spatially obvious as entering.
  **AC:** A user can build Work → Projects → Project-X three levels deep, see each child on its parent's canvas, enter by interacting with the portal, and return without using the sidebar.
- **R-503 (MUST, P1).** Hierarchy operations are safe: pages can be nested and re-nested after creation; deleting a parent handles children **visibly** (reparent or explicit confirmed cascade) — never silent orphaning (audit defect).
- **R-504 (MUST, P1).** **Spatial memory is durable per user**: module positions, page arrangement, and viewport-per-page persist across devices and browsers (today viewport memory is per-browser only).
  **AC:** Arrange a page on device A; open device B: same arrangement and resume-view.
- **R-505 (SHOULD, P2).** An overview affordance (minimap or birds-eye) reflecting the hierarchy, not just the current page.

## 7. Cross-module data & sync — `R-600`

Grill Q14: **live-in-view, no silent loss**; the brief's "largest open technical risk" gets its bar here.

- **R-601 (MUST, P0).** **Live in view:** an edit to any module is reflected in every dependent module currently on screen **within 200ms** on the reference environments (§1), without waiting on any network round-trip.
- **R-602 (MUST, P0).** **No silent data loss, ever:** concurrent edits (two tabs, refine-during-edit, rapid typing during save, **edit-then-move within the save debounce window**) must resolve visibly — merge, prompt, or explicit conflict — never last-writer-wins wipe. The audit's racing-writer defects are the named failure modes this requirement retires.
  **AC:** Two-tab edit test: edits in both tabs; neither user's work vanishes without an on-screen trace. Refine-during-edit test: user keystrokes survive. Edit-then-drag test: editing a field then immediately dragging the module leaves both the edit and the new position intact.
- **R-603 (MUST, P1).** **Fresh on open:** opening the workspace on any device shows current data — *current* = all changes that had successfully saved (per R-1101's truthful save state) before the open. Live cross-device push is *not* required (collaboration is post-MVP, §16).
- **R-604 (MUST, P1).** **Bindings actually work when generated:** if a proposal wires module B to aggregate/reference module A, that binding functions on the canvas *(repo-verified at a41ceb1: the model is never given real module ids, so emitted cross-module references can never resolve — full evidence in the audit's underlying run)*. Aggregations must be scoped so unrelated same-named fields don't pollute each other.
  **AC:** "Dashboard summarizing my three trackers" produces a dashboard whose numbers change when the trackers change.
- **R-605 (MUST, P1).** Sync guarantees hold at **50+ modules on a page** without interaction jank (ties to R-1301).

## 8. Live data — last-mile actionability — `R-700`

Grill Q10: read-only live values, two launch domains: **weather + nutrition** (the brief's own calorie story).

- **R-701 (MUST, P1).** Generated modules can carry **live external values**: a component can display real, current data from an external source with visible freshness ("as of…") and provenance (which source).
- **R-702 (MUST, P1).** The orchestration **emits live bindings when intent implies them**: a calorie/food module gets working nutrition lookup; weather-relevant intents (trip planner, run tracker) get live weather. **Weather and nutrition are the only live-data domains in MVP scope (§16).**
  **AC (the demo test):** "help me track calories" → a module where entering a food yields a real calorie value from a live source. "plan my Saturday hike" → a module showing the actual forecast.
- **R-703 (MUST, P1).** External-source failure degrades **visibly and locally**: a stale/unavailable badge on the value; the module keeps working for manual entry; the workspace is never harmed by a dead provider.
- **R-704 (SHOULD, P2).** Live values are **one coherent capability, not two special cases**: both launch domains present freshness, provenance, and failure states identically (R-701/R-703), and future sources must not break users' stored workspaces (ties to R-1105). *(Extensibility mechanics are a builder default — see Appendix A.)*
- **R-705.** Write-side execution (booking, sending, calendar writes) is excluded from MVP (§16), and **live read domains beyond weather + nutrition (e.g., the brief's flight-data/Expedia example) are excluded at launch** (Q10). Intents implying an unlaunched live domain must not fake live values: the module is generated for manual entry with no live badge (with R-403).

## 9. Memory & profile — `R-800`

Grill Q12: **explicit evolving profile** — the strongest reading.

- **R-801 (MUST, P1).** Trus maintains an **explicit profile per user**: goals, preferences, recurring patterns, and interview-learned facts. The profile is **inspectable and editable** — a real surface where the user can see, correct, and delete what Trus believes about them.
- **R-802 (MUST, P1).** The profile **accretes from use**: interview answers, prompts, and workspace activity enrich it over time without the user having to fill in forms. Nothing enters the profile that the user cannot see.
  **AC:** After an interview in which the user states a goal, the profile surface shows a corresponding entry without any form-filling; every field the generation pipeline reads from the profile is rendered on the profile surface.
- **R-803 (MUST, P1).** Generation, the interview, and suggestions **draw on the profile**: a returning user's proposals are shaped by who they are, per the §0 traceability test.
  **AC:** The same prompt from a fresh account vs. an established one yields proposals that differ in ways traceable (per §0) to specific profile entries.
- **R-804 (MUST, P0).** Profile deletion is real deletion (ties to R-1003).

## 10. Identity, access, devices & hosting — `R-900`

Grill Q4: invite-model reference decision lives in Appendix A; the *requirements* are:

- **R-901 (MUST, P0).** Access is **gated**: only provisioned alpha users can read or write any user data, shared store, or model-spending capability. Unauthenticated or forged sessions get nothing — no spend, no reads, no writes.
  **AC:** An unauthenticated request (and a session signed with a default/known secret) cannot trigger generation, read any workspace, or mutate any shared store (audit: today's layout library and seed pool are anonymous-writable).
- **R-902 (MUST, P0).** **Cross-device continuity with near-zero friction**: a user reaches their own workspace from any device/browser with nothing to memorize or install. *(Mechanism is the builder's choice; Appendix A records the invite-link default.)*
  **AC:** From a new device, a provisioned user reaches their own workspace via at most one link-follow or one short code entry — no password creation, no email-verification round-trip during the alpha session.
- **R-903 (MUST, P0).** **Hard per-user isolation**: no user's content, prompts, profile, or cached generations may ever surface to another user (audit: the global generation cache violates this today).
  **AC:** User A generates from a distinctive personal prompt; user B's near-identical prompt never receives A's content.
- **R-904 (MUST, P0).** The operator can provision and revoke each of the 50 individually.
- **R-905 (MUST, P1).** Usage and cost are attributable **per user** (feeds §13).
- **R-906 (MUST, P0).** **The MVP is hosted**: every provisioned alpha user can reach their own workspace at a stable public HTTPS URL from their own devices and networks, with no local install, repo checkout, or developer tooling on their side. Operation confined to a developer machine or local network does not satisfy MVP-done; all P0/P1 "done" claims are asserted against the hosted deployment.
  **AC:** A provisioned user on a phone over cellular completes entry → interview → proposal → confirm → reload against the hosted instance (retiring the audit's localhost-only CORS/cookie posture).

## 11. Privacy & data ownership — `R-1000`

Grill Q16: disclosure + export + erasure; silent on where processing happens.

- **R-1001 (MUST, P0).** Before first use, a **plain-language disclosure**: what data is stored, what leaves the device, and to whom it goes.
  **AC:** The disclosure is ≤300 words, at or below a US grade-10 reading level (any standard readability measure), and enumerates: (1) what is stored, (2) what leaves the device, (3) which third parties receive it.
- **R-1002 (MUST, P1).** **Full export**: a user can download their entire workspace + profile in a portable, machine-readable form, self-served.
- **R-1003 (MUST, P1).** **True erasure**: account deletion removes workspaces, profile, memory, uploaded documents, prompts/transcripts in logs, and cached derivatives of the user's content. Aggregate operational telemetry (counts, latencies, costs) MAY be retained only if stripped of user content and no longer attributable to the deleted identity.
  **AC:** After deletion, a full-store search for a distinctive string the user had entered returns nothing.
- **R-1004 (MUST, P0).** **No cross-user reuse of personal content without opt-in** — the default posture is isolation (R-903); any future sharing/data-flywheel feature is opt-in by design (brief's settled privacy model; the library itself is excluded, §16).

## 12. Reliability & data safety — `R-1100`

The brief's non-negotiable, made testable. "Never lose work, never freeze."

- **R-1101 (MUST, P0).** **Save state is always visible and truthful**: the user can always tell whether their work is saved; failures surface with retry; leaving with unsaved work warns. Silent save-swallowing (audit defect) is retired.
  **AC:** Kill the network mid-edit: the UI shows unsaved/retrying within seconds and warns before close; on reconnect the edit persists without user action.
- **R-1102 (MUST, P0).** **Destructive actions are confirmed or undoable**: page deletion (which currently silently destroys all its modules), module deletion, and restore operations. **Restores are atomic** (all-or-nothing: a failed restore leaves the workspace exactly as it was) and preserve referential identity — restoring a snapshot must not silently break bindings (audit defects).
- **R-1103 (MUST, P0).** **One user's work never degrades another's**: long generations must not freeze saves, loads, or anyone else's session (audit: event-loop defect named here as the failure mode to retire).
  **AC:** With 3 long generations in flight, an unrelated user's module save, workspace load, and health check each complete in under 1s at P95 — no request queues behind a generation's completion.
- **R-1104 (MUST, P0).** **Model outage degrades honestly**: provider down → clear status, queued/blocked actions visible, no fake successes, no poisoned caches (with R-403).
  **AC:** With the model provider unreachable, generate/refine yield a clear user-visible status; recovery requires no restart; nothing fake was persisted.
- **R-1105 (MUST, P0).** **Stored data survives product evolution**: a schema change must never brick existing workspaces, and one bad record must never take down a whole workspace load (audit critic's top structural risk). How (versioning, migrations, tolerant reads) is the builder's choice.
  **AC:** In a test copy: add a new component field and remove one component type — previously stored workspaces still load; a deliberately corrupted row degrades only itself, not the workspace.
- **R-1106 (MUST, P1).** **Data survives infrastructure failure**: hosted user data is backed up such that a total host loss costs at most ~24h of changes (RPO ≤ 24h), and restore has been exercised at least once before the alpha.

## 13. Observability & the alpha gate — `R-1200`

The alpha gate is "50 users daily." A gate you can't measure is a wish. (Folded default from grill; audit critic finding.)

- **R-1201 (MUST, P0).** **Daily activity is measurable per user** — DAU/retention for the cohort answerable from data, not vibes.
  **AC:** The operator can answer "which of the 50 used the product yesterday, and which haven't in a week?" from recorded data alone.
- **R-1202 (MUST, P0).** **Every generation is accounted**: success/failure/refusal/question outcome, latency, and token cost recorded per call, attributable per user (with R-905). Cost per active user per month is computable.
- **R-1203 (MUST, P0).** **Errors are visible to the operator**: backend and frontend failures reach an operator surface (not just user consoles) with enough context to debug.
- **R-1204 (SHOULD, P1).** The silent-degradation events of R-403/R-1104 (fallbacks, stale live-data, save retries) are themselves counted, so product honesty is auditable.

## 14. Performance, mobile & design bar — `R-1300`

- **R-1301 (MUST, P0).** **Canvas interaction stays smooth at 50+ modules** on the reference environments (§1) — pan/zoom/drag without jank (audit: O(N²)-per-pointer-event defect named as the failure mode).
  **AC:** On a 50-module page, a 10-second scripted pan+zoom+drag sequence sustains ≥30fps average with no single frame >100ms, measured on (a) the throttled laptop browser and (b) both named phones.
- **R-1302 (MUST, P0).** **Feedback is immediate even when generation isn't**: any generation shows progress within 500ms (skeleton/beam); the user is never left staring at a dead button.
- **R-1303 (SHOULD, P1).** Perceived latency targets, verified by the telemetry of R-1202: interview turns feel conversational (P50 ≤ 3s); proposals P50 ≤ 15s, P95 ≤ 60s. *(SHOULD because model choice is out of scope; the telemetry MUST exist either way.)*
- **R-1304 (MUST, P0).** **Touch-viable mobile** (grill Q5): not a redesign — "opened it on my phone and it wasn't broken" is the bar, made testable:
  **AC:** At a 375px-wide viewport on iOS Safari and Android Chrome: pinch-zoom and one-finger pan work on the canvas; a module can be drag-repositioned by touch; the R-201 ramble test passes; no module renders with overlapping/clipped text or forces horizontal page scroll; all tap targets are reachable.
- **R-1305 (MUST, P1).** New surfaces (entry screen, interview, sketch overlay, profile, live-data badges) conform to the **Trus design ethos** (repo `DESIGN-ETHOS.md`).
  **AC:** Each new surface receives a logged design review against the ethos doc's named principles before its stage exits; every violation is fixed or explicitly waived in the log.
- **R-1306 (SHOULD, P2).** Keyboard access and dialog semantics for the major overlays (command palette, detail view, inspector) — the current zero-keyboard canvas is a known debt; full a11y is not an MVP gate but new surfaces shouldn't deepen the hole.

## 15. Engineering quality gates — `R-1400`

Quality-gated cadence (grill Q2) needs defined gates. These are requirements on the *codebase*, not the product.

- **R-1401 (MUST, P0).** **All gates green at every stage exit**: backend tests pass (the committed-red archetype test is fixed or removed), the coverage gate passes — *reconciled to a single authoritative gate first; today the backend-local (78% line, passing) and repo-root (80% branch, failing at 74.67%) configs disagree, and the repo-root gate is authoritative until explicitly re-decided* — type checks clean, lint either enforced or explicitly retired from the gate (no zombie gates that fail and block nothing). Dead scaffolding flagged by the audit (the unused intent-decoder module, orphaned components) is either wired into a requirement or removed.
- **R-1402 (MUST, P1).** **Generation quality is regression-protected**: a golden-prompt suite (including the founders' real dogfood docs — the SOCS model and the Trus dev plan, per the brief's demo strategy — pinned in a format R-211 supports, converting to PDF/Markdown if needed) scored for structural validity and intent coverage; prompt/pipeline changes run it before merging.
  **AC:** Structural validity is 100% on the suite (every golden prompt yields schema-valid, reference-intact config); intent coverage has a recorded baseline with a documented scoring rubric, and no merge reduces either score below its recorded baseline.
- **R-1403 (MUST, P1).** **The frontend has tests** for the core loop (propose → confirm → render → edit → persist) and CI runs them; today it has zero.
- **R-1404 (MUST, P1).** Licensing is deliberate: a LICENSE decision for the repo, and dependency licenses (notably GSAP) verified compatible with a commercial product.
- **R-1405 (SHOULD, P1).** New defects found by this spec's ACs land as failing tests first (the audit's file:line findings are the seed list).

## 16. Deliberate exclusions (decided, with reasons — do not silently re-add)

| Excluded | Why (decision ref) |
|---|---|
| **Community/template library, commissions, credits** | Brief's own MVP philosophy ("nothing beyond reliable core"); blank-canvas duty carried by interview + suggestions; no monetization substrate needed at alpha. Revisit at public beta with GTM play #1. (Q15) |
| **Cross-user suggestion seeding** | The brief's settled blank-canvas element (3) seeds from *similar users*; amended to own-usage seeding at alpha — cross-user seeding conflicts with the isolation default (R-903/R-1004) and depends on the excluded data flywheel. Revisit with the opt-in data program. (Q8) |
| **Collaboration / shared workspaces / presence** | Post-MVP per brief and STATUS; drives real-time infra prematurely. R-603's "fresh on open" is the alpha bar. |
| **Write-side external actions** (booking, sending, calendar writes) | Read-only live values prove "the engine" honestly; OAuth consent + write-risk out of proportion at alpha. (Q10) |
| **Live-data domains beyond weather + nutrition** (flights/Expedia, stocks, …) | Launch scope is exactly two domains; breadth resumes post-alpha. Unlaunched domains must not fake live values (R-705). (Q10) |
| **LLM/SLM routing as a requirement** | Explicitly not a requirement (Q11); builder free to use any model architecture that meets the product bar. Telemetry (R-1202) keeps the story measurable regardless. |
| **Continuous-zoom universe** | Visible nesting (R-502) delivers spatial memory at a fraction of the cost; purest reading deferred. (Q13) |
| **Persistent ink / canvas annotation** | Sketch is ephemeral scaffolding that becomes modules (R-222/R-223); an ink subsystem is not MVP scope. (Q9) |
| **Native mobile apps** | Touch-viable web is the bar (R-1304). (Q5) |
| **Public signup / production auth** | Alpha is 50 provisioned users (R-901–904); real auth at public beta. (Q4) |
| **Data-sharing opt-in credit program** | Depends on the excluded library + credits; privacy default is isolation (R-1004). |
| **Computational hygiene / credit budgets** | Cost is *measured* (R-1202) not *rationed* at alpha. |

## 17. Open questions (tracked, not blocking spec v1.0)

1. **Alpha rollout staging** — all 50 at once vs. waves of 10–15? (Recommend waves; decide when hosting is live.)
2. **Document persistence** — R-214 is SHOULD; decide whether uploaded docs become durable workspace objects post-MVP.
3. **Cost ceiling** — R-1202 makes cost/user knowable; what number triggers intervention? (Set after first telemetry.)
4. **GTM-informed scope check** — `_BRAIN` open thread says research GTM before MVP scope locks; this spec locks *product* scope. If GTM research (template play, ICP validation) contradicts a pillar's priority, amend via decisions-log, not silently.
5. **Canonical repo** — the 2026-06-24 consolidation decision (one repo, off iCloud) is still unconfirmed; this spec assumes `Generative-Workspace` is canonical. Confirm before the plan executes.
6. **Design-ethos conformance pass** — R-1305 references `DESIGN-ETHOS.md`; the entry/interview surface may warrant a design review of that doc's application to conversational UI (it was written for canvas/marketing surfaces).

## Appendix A — Non-binding reference decisions (from the grill, pre-pivot)

> The grill initially resolved several *mechanism* questions before the requirements-only pivot. They are recorded here as **defaults the builder may adopt or overturn** — the requirements above, not these, are the contract.

- **Hosting:** containerized FastAPI + SQLite (WAL) on Fly/Railway/Render with persistent volume; frontend on Vercel. "Vercel + Supabase" in the brief's architecture section is amended (Supabase doesn't host FastAPI; Postgres rewrite deferred to scale). (Q3)
- **Identity mechanism:** 50 signed, re-claimable invite links bound to pre-provisioned users — gating + identity + cross-device in one, no email/OAuth infra. (Q4)
- **Voice mechanism:** recorded audio → server-side transcription through the existing pluggable-provider seam (local Whisper-class model or hosted equivalent); browser live-transcription kept only as progressive enhancement. (Q6)
- **Live-data providers:** weather via a keyless source (e.g. Open-Meteo); nutrition via a free source (e.g. Open Food Facts / USDA FDC); proxied and cached server-side. (Q10)
- **Live-value extensibility:** implement live values as a generic source binding so a future third domain is additive (no schema/library rework) — encouraged, not required (see R-704).
- **Sketch mechanism:** transparent stroke overlay → bitmap of stroke bounds → existing vision→config pipeline with a prompt retuned for hand-drawn wireframes. (Q9)

## Appendix B — Traceability

| Spec section | Brief pillar | Audit pillar (status at audit) |
|---|---|---|
| §3 R-100 | Blank-canvas solution (settled, non-negotiable) | blank-canvas-entry (partial) · idea-generation (partial) |
| §4 R-200 | Multimodal inputs; MVP must-have #1 | voice (partial) · document-upload (partial) · sketch (partial) |
| §5 R-300/400 | MVP must-haves #2, #3 | idea-generation (partial) · module-generation (done) |
| §6 R-500 | Digital Clay / spatial memory | spatial-canvas (partial) |
| §7 R-600 | Largest open technical risk | cross-module-sync (partial) |
| §8 R-700 | Last-mile actionability (key differentiator) | last-mile-actionability (missing) |
| §9 R-800 | Vector-DB memory ("remembers the user") | memory-user-context (partial) |
| §10 R-900 | Alpha 50 gate; hosted product | auth-and-accounts (partial) · deployment-alpha-readiness (missing → R-906) |
| §11 R-1000 | Privacy as selling point | (audit critic: privacy posture) |
| §12 R-1100 | Reliability non-negotiable | reliability-daily-use (partial) |
| §13 R-1200 | 50-DAU gate measurability | (audit critic: zero observability) |
| §14 R-1300 | Design ethos; ICP daily use | (audit critic: mobile, a11y; perf dimension) |
| §15 R-1400 | "Works very well" | testing-quality dimension |
| §16 exclusions | Brief's MVP philosophy | (scope control) |

## Related
- [[mvp-gap-audit-2026-07-02]] · [[trus-brief]] · [[../product]] · [[../architecture]] · [[../decisions-log]] · [[_README]]
