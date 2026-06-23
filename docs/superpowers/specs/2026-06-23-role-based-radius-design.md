# Role-based corner radius — design

**Date:** 2026-06-23
**Branch:** feat/generation-variation-and-sheen
**Status:** approved, executing

## Problem

The UI reads as "AI-generated" largely because corner radius is applied with no
intent. Every surface lands in the same soft-rounded family: containers span
`rounded-lg`→`xl`→`2xl` (8/12/16px) arbitrarily, interactive controls are a
4–6px mix, and `rounded-full` is sprinkled on things that are not actually round
(choice chips, suggestion chips). Radius is also not centralized — the
`--radius-sm/md/lg` tokens in `globals.css` are declared but never referenced
(dead), so the real system is ~40 files of scattered Tailwind `rounded-*`
utilities.

## Decision

Adopt a **role-based radius system applied as one house style across the whole
app** (chrome + generated module cards + the primitive library). Corner radius
is decided by a component's *job*, not applied uniformly. This is Notion's logic:
soft container, crisp controls, square data.

### The scale (4 tiers, down from 7)

| Semantic token | Value | Tailwind utility | Role |
|---|---|---|---|
| `--radius-data` | `0px` | `rounded-none` | Dense/structural data surfaces |
| `--radius-control` | `4px` | `rounded-sm` | Anything you click or type into |
| `--radius-surface` | `8px` | `rounded-lg` | Elevated containers floating over the canvas |
| `--radius-pill` | `9999px` | `rounded-full` | Genuinely round things |

`rounded-md` (6px), `rounded-xl` (12px), `rounded-2xl` (16px) are **retired** —
those middle-soft values are the biggest "AI bubble" tell. Nesting then reads
with intent: **8px panel → 4px controls → 0px data tables**.

Stock Tailwind utilities already equal these values (`rounded-sm`=4, `rounded-lg`
=8, `rounded-none`=0, `rounded-full`=9999), so the sweep needs no Tailwind theme
changes — pure class edits. The `--radius-*` tokens are revived as the canonical
reference (with a role-legend comment) for the few inline/SVG cases.

### Role → radius mapping

- **0px / `rounded-none` — data & structure:** `TableField` wrapper,
  `KanbanField` columns, `TrackerField` grid. (`HeatmapField` cells keep their
  existing 2–3px micro-radius — square cells read as a defect at that size.)
- **4px / `rounded-sm` — controls:** every input/textarea/select & select
  trigger, every button **including the magenta CTA**, icon buttons, menu/list
  rows currently at 6px, kanban *cards*, calendar day cells, checkboxes, gallery
  tiles.
- **8px / `rounded-lg` — surfaces:** module card shell, side panels
  (Conversation/Archived/Snapshots/Inspector), CommandPalette, ShortcutsModal,
  PromptBar, AppearanceMenu, Select dropdown, popovers, toasts, EmptyState badge.
  Containers already at `rounded-lg` (8px) stay.
- **Pill / `rounded-full` — genuinely round (kept):** `TagsField`, avatars &
  color swatches, status/timeline/tracker dots, circular toggle/habit dots,
  progress-bar & ring tracks, count badges, circular icon-only buttons.

### Opinionated calls (the real de-AI moves)

1. **Magenta CTA: `rounded-md` → 4px control.** Pill/soft primary buttons are a
   generic-SaaS/AI tell; Notion primary buttons are small-radius rectangles.
2. **Module card: `rounded-2xl` (16px) → 8px.** Halves the most prominent corner.
3. **`ChoiceChipsField` & `EmptyState` suggestions: pill → 4px.** Pill-shaped
   *action* chips are an AI tell; pill *tags* are not, so `TagsField` stays round.
4. **Retire `rounded-md/xl/2xl`.**

## Implementation plan

### Decision table (applied to every `rounded-*` occurrence)

1. `rounded-2xl` → `rounded-lg`
2. `rounded-xl` → `rounded-lg`
3. `rounded-md` → `rounded-sm`
4. `rounded-lg` → keep (surface) — *except* the named data wrappers below
5. `rounded` (bare) / `rounded-sm` / `rounded-[2px]` / `rounded-[3px]` → keep
6. **Data-surface exceptions → `rounded-none`:** `TableField` wrapper,
   `KanbanField` columns, `TrackerField` grid.
7. **Pill-demotion exceptions → `rounded-sm`:** `ChoiceChipsField` chips,
   `EmptyState` suggestion buttons.
8. All other `rounded-full` → keep.

### Phases

1. **Foundation** — `globals.css`: replace the dead `--radius-sm/md/lg` with the
   4 semantic tokens + role-legend comment.
2. **Module.tsx sync points (must match):** shell `rounded-2xl`→`rounded-lg`
   (`:280`), sheen overlay `rounded-2xl`→`rounded-lg` (`:315`), border-trace SVG
   `rx="16"`/`ry="16"`→`8` (`:311`), icon tile `rounded-md`→`rounded-sm` (`:365`).
   The screenshot-import `RADIUS` override map (`:258`, `sharp/rounded/pill` =
   8/16/28px) is **left untouched** — it is an explicit import-fidelity feature
   outside the role system (closed-enum design layer from a screenshot capture),
   and the default uniform look is already fixed by the shell change above.
3. **Data-surface + pill-demotion exceptions** (rules 6–7): `TableField`,
   `KanbanField`, `TrackerField`, `ChoiceChipsField`, `EmptyState`.
4. **Mechanical sweep** (rules 1–3) across all remaining chrome + primitive
   files.
5. **Adversarial verification** — independent pass over the diff: completeness
   (no forbidden `rounded-md/xl/2xl` remain), no over-reach (genuinely-round
   things still `rounded-full`, data wrappers `rounded-none`), Module sync points
   aligned, build green.

## Scope

Radius only. **Out of scope:** colors, spacing, shadows, accent system, motion.

## Verification

- `cd frontend && npm run build` stays green.
- `grep -rE "rounded-(md|xl|2xl)" frontend/src` returns nothing.
- Visual: canvas + a generated module + a side panel + the prompt bar eyeballed
  against the role mapping.
