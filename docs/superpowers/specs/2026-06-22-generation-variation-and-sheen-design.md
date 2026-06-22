# Generation Variation + Website Sheen — Design

**Date:** 2026-06-22
**Status:** Approved (design); implementation pending

## Goal

Two related improvements to module generation:

1. **Sheen** — make the workspace generation animation carry the same "matte sheen"
   the marketing site uses (`Trus Website (New)`), across three mechanics.
2. **Visual variation** — make generation deliberately pick the *format* that best
   models the user's intent (e.g. a workout log → a calendar, not a plain form),
   then render it in a coherent theme. The end state is more visual variety.

Both must work in **stub mode** (no Gemini key — the current default) *and* live mode.

## Background (current state)

- **Animation.** `frontend/src/lib/assembly.ts` runs the signature six-beat "module
  build" per tile. Beat 4 is a light scan band whose comment says it "echoes the
  wordmark sheen," but its gradient (`white-matte 28%`, single peak, 50% width) and
  easing (`power1.inOut`) do **not** match the site's canonical band. The site's
  `.module-scan` is a triple-stop band (`rgba(240,239,237, .1/.16/.1)`) at **36%**
  width; `wordmark-sheen` is a `background-clip:text` gradient sweep; `clay-scan-beam`
  is a 64px beam that sweeps the app grid "as Trus reads it." `DESIGN-ETHOS.md` §5.2/§5.4
  confirm the matte sheen (off-white→white→off-white) is brand DNA and the six-beat
  build is "the template for a thing being generated."
- **Generation.** `backend/src/services/orchestrator.py` → `generate_modules()` is the
  path the UI uses (PromptBar → `previewModules`). Live: semantic-cache lookup, else a
  seed from `stub_templates.pick_system()` (keyword routing), then the `DECOMPOSE`
  prompt → Gemini → array. Stub: `pick_system()` only. Intent→format matching already
  exists implicitly via two keyword tables (`_ROUTES_V2`, `_ROUTES`) and prompt text,
  but it is ad hoc and some intents map to plain forms.

## Decisions (from brainstorming)

- Variation pipeline: **Approach 3 (hybrid)** now, on-ramp to Approach 2 later.
- Sheen: **all three** site mechanics (build band, title sheen, canvas beam).
- Gating: when a Gemini key is present, the LLM `decode_intent` step runs **always**
  (option a); the deterministic selector is the stub path and the universal fallback.

---

## Workstream A — Sheen (frontend)

### A1 · Canonical scan band
Define the brand matte-sheen gradient once and use it for the per-tile build band.
- In `Module.tsx`, the beat-4 scan element: width `50% → 36%`; background → triple-stop
  `color-mix(in srgb, var(--white-matte) 10%/16%/10%, transparent)` matching the site's
  `.module-scan` (note `--white-matte` is `#f0efed` = `rgb(240,239,237)`, so the
  `color-mix` percentages reproduce the site's exact rgba alphas).
- In `assembly.ts`, align beat-4 easing to `power2.inOut` (per DESIGN-ETHOS §5.2).
- The `xPercent: -130 → 330` travel is already correct; keep it.

### A2 · Title sheen
After the label wipe (beat 5), run a **one-shot** matte sheen across the title via
`background-clip:text` + a `wordmark-sheen`-style `background-position` pass, then
restore solid text on finalize.
- Implemented as a CSS class (e.g. `.title-sheen`) toggled by `assembly.ts` on the
  `[data-assembly="label"]` element, added just after the wipe and removed in
  `finalize()`. `background-clip:text` (a paint property) and the wipe's `clip-path`
  (a layout/clip property) are independent, so they compose; the sheen runs *after*
  the wipe so the text is fully present.
- Additive only — the existing wipe is unchanged.
- Reduced motion: never added (the existing guard already skips `runAssembly`).

### A3 · Canvas reading beam
A `GenerationBeam` overlay on the Canvas, visible only while a generate/preview
request is in flight, sweeping a ~64px matte beam horizontally (loop ~1.4s) — signals
"Trus is reading your intent," echoing `clay-scan-beam`.
- New component `frontend/src/components/GenerationBeam.tsx` (a `pointer-events:none`,
  full-canvas overlay with a looping CSS animation using the shared matte gradient).
- New CSS keyframe in `globals.css` (e.g. `trus-readbeam`) and a `.read-beam` class.
- **State plumbing:** `PromptBar` already holds a `loading` flag for the
  generate/preview submit. Add an `onGeneratingChange?(busy: boolean)` prop; PromptBar
  fires it true at the start and false at the end of the generate/preview branch only
  (not refine/file unless trivial). `page.tsx` holds the boolean and passes it to
  `Canvas`, which renders `<GenerationBeam active={generating} />`.
- Reduced motion: render nothing (respect `data-motion` / `prefers-reduced-motion`).

### A — Testing
No frontend test runner exists (project testing is backend pytest). Verify visually:
run the app, generate, capture screenshots of (1) the build band, (2) the title sheen,
(3) the canvas beam during generation, and (4) a reduced-motion run showing the final
state with no beam/animation.

---

## Workstream B — Variation (backend, hybrid)

### B1 · Archetype registry — `backend/src/archetypes.py` (new)
A single source of truth for "what formats exist and when they fit." An `Archetype`
record holds: `key`, `label`, `signals` (keywords/intent cues), `builder()` (returns a
seed ModuleConfig dict built from the right primitives + layout), and a default
`theme` (`accent`, `icon`). ~35–45 archetypes spanning the non-form formats: calendar
logs, kanban pipelines, dashboards (columns:2 + kpi/chart/gauge), journals (note +
heatmap), tables/ledgers, heatmap streaks, gauge panels, gallery boards, checklists,
timelines, trackers, etc. Existing `stub_templates` builders are reused/migrated rather
than rewritten.

### B2 · Deterministic selector — `select_archetypes(prompt) -> list[Archetype]`
Scores the registry against the decoded intent (the current `_matches` whole-word /
suffix logic, generalized + weighted). Returns the best 1–N matches plus a confidence
derived from the top score. This is the always-available "search for best models that
model the intent" step: the stub/no-key path **and** the universal fallback.

### B3 · LLM intent decode — `decode_intent(prompt) -> Decoded | None` (live only)
A cheap `llm.generate()` call given the archetype **menu** (keys + when-to-use). Returns
structured `{summary, archetypes: [registry keys], theme: {accent, icon}}`. Selecting
and combining *known* formats keeps output valid while giving more variety than keyword
matching. **Must degrade gracefully:** any `LLMError`, empty, non-JSON, or
unknown/empty-archetypes result → return `None` (caller falls back to `select_archetypes`).
This is the property that makes the orchestrator's mocked-LLM tests keep passing when an
extra `generate` call is introduced.

### B4 · Orchestration wiring — `generate_modules()`
```
if stub:            return finalize(select_archetypes(prompt) -> seeds)   # no LLM
mode, cached = semantic_cache.lookup("system", prompt)
if hit:             return cached
decoded = decode_intent(prompt)                 # gating (a): always, when live
chosen  = resolve(decoded) or select_archetypes(prompt)
seed    = seeds_from(chosen)                     # labeled archetype seed(s) + theme
result  = _generate_validated(seeded_system(prompt, existing, seed_override=seed,
                                            archetype_menu=MENU, theme=chosen.theme), ...)
semantic_cache.store("system", prompt, result)
return result
```
- The `DECOMPOSE` system prompt gains an **Archetype menu** section and a line:
  "the request best matches «X»; build in that format unless a clearly better archetype
  fits; keep one coherent theme across the set."
- `decode_intent` runs **before** generation, so the *last* `llm.generate` call is still
  the generation call — context-injection assertions (`call_args[0][0]` contains the
  existing module titles/ids) remain valid. `decode_intent` is scoped to
  `generate_modules` only; `generate_module` (singular), `refine_module`, and
  `synthesize_workspace` are unchanged.

### B5 · Library expansion + intent remaps
Grow registry coverage so the generic fallback fires less, and **refit** intents to
better formats — e.g. workout-log → a calendar/heatmap-centric archetype rather than a
plain field stack. Preserve the routing the existing tests assert (workout→"Workout",
calorie→"Calorie", budget→"Budget", todo→"To-Do", reading→"Reading", habit→"Habit",
mood→"Mood"; "a kanban task board"→"Task Board"; "a finance dashboard"→contains
"Dashboard"; "weekly retro"→"Weekly Retro"; "expense categories"→not Pet).

### B6 · Coherent theming — `theme_for(domain) -> {accent, icon}`
Upgrade `stub_templates._visual_for` (currently a hash) to be domain-aware (fitness→
emerald, finance→amber/gold, travel→sky, wellness→rose, creative→violet, food→coral…)
and consistent across a generated set, so a multi-module system reads as a color-coded
family ("generate in same theme").

### B — Testing
- New `backend/tests/test_archetypes.py`:
  - `select_archetypes` maps the canonical intents to the expected archetype/format
    (workout-log→calendar, pipeline→kanban, habit→heatmap, guest-list→table); broad
    intents return multiple; focused intents return one.
  - every archetype's `builder()` produces a valid `ModuleConfig`.
  - `decode_intent` returns `None` on non-JSON / unknown keys / `LLMError` (graceful).
- Keep green (update intentionally where consolidation changes output, never weaken):
  `test_stub_templates.py`, `test_decomposition.py`, `test_orchestrator.py`.
- Guard: `cd backend && python -m pytest -q` passes.

---

## Risks / notes

- Consolidating the two keyword tables onto one registry will change some stub outputs;
  update the affected assertions deliberately, keeping the tests in
  `test_stub_templates.py` (incl. the `_ROUTES_V2` ≥50 + varied-format checks) satisfied.
- The extra `decode_intent` `generate` call must be the *non-final* call and must
  degrade to `None` so existing orchestrator tests (which mock `generate` to a single
  fixed payload) still pass.
- Title `background-clip:text` requires the existing text color handling; keep the sheen
  one-shot to avoid a persistent repaint cost.
- The beam must never capture pointer events and must honor reduced motion.

## Out of scope

- Replacing the keyword decode with a pure-LLM decode (Approach 2) — deferred.
- Frontend test harness.
- Changes to refine/synthesize/file-import generation paths beyond what theming touches.
