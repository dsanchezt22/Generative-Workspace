# V2 committed design — surfaces

> Produced by a 3-take + adversarial-judge council on 2026-07-06.
> This is the spec the implementation follows verbatim.

# FORK 3 — COMMITTED DESIGN: App-grade zoomable surfaces

Skeleton: TAKE 1 (surface = existing Page; one prompt, one preview endpoint; camera tween ends in the existing hard swap). Grafts: Take 3's fail-closed tier, page-index references, single-transaction insert, and invariant-test matrix; Take 2's scrim beat, PortalTile extraction, overview endpoint, and explicit proposal card.

Core model: **a "surface/app" IS a child Page.** No new entity. A structure generation composes Pages + ModuleConfigs + proposed (seam-honest, non-executing) automations. Everything is additive-optional to the existing contract.

---

## 1. Backend schema — backend/src/schema.py (all additive)

```python
class StructureAutomation(BaseModel):
    """A PROPOSED always-on runtime automation wired to one page of a structure
    proposal (the V2 runtime concept — NOT ModuleConfig.automations, which stays
    the client-side intra-module increment/flag rules). The server mints row ids;
    the model never emits one."""
    name: str = Field(max_length=80)
    description: str = Field(max_length=300)   # ONB-2: plain-language "exactly what it will do"
    schedule: Literal["hourly", "daily", "weekly"] = "daily"
    tier: Literal["autonomous", "consequential"] = "consequential"  # FAIL-CLOSED default
    page: int = Field(ge=0)                    # index into StructureProposal.pages — never a DB id
    target_component_id: str | None = None     # component on that page runs write into (usually a feed)

class StructurePage(BaseModel):
    name: str = Field(max_length=60)
    icon: str | None = None      # same open-string + frontend-fallback contract as ModuleConfig.icon
    accent: str | None = None    # same trusted-palette-token contract as ModuleConfig.accent
    purpose: str | None = Field(default=None, max_length=200)  # ONB-2: what this surface is for
    modules: list[ModuleConfig] = Field(min_length=1, max_length=6)

class StructureProposal(BaseModel):
    plan: str | None = None
    pages: list[StructurePage] = Field(min_length=1, max_length=4)
    automations: list[StructureAutomation] = Field(default_factory=list, max_length=6)

class InsertStructureRequest(BaseModel):
    structure: StructureProposal
    prompt: str | None = None
    exchange: list[ExchangeTurn] | None = Field(default=None, max_length=6)

class InsertStructureResponse(BaseModel):
    pages: list[Page]
    modules: list[StoredModule]
    automation_ids: list[str]
```

`GenerateResponse` gains ONE field: `structure: StructureProposal | None = None`.
`Page`, `CreatePageRequest`, `RenamePageRequest` gain `accent: str | None = None`.

**One new trusted component** (the only one — kpi/metric/chart/table/tracker already cover stat rows):

```python
class Feed(ComponentBase):
    """Newest-first entries an automation run appends to (SURF-3/RUN-6).
    state[id] = list[{"ts": ISO str, "title": str, "body": str|None,
    "badge": "draft"|"simulated"|"failed"|None}]. Entries are PLAIN TEXT —
    the renderer never interprets markup."""
    type: Literal["feed"] = "feed"
    max_items: int = Field(default=20, ge=1, le=100)
```

Added to the `Component` discriminated union. No other new types.

## 2. DB — backend/src/db.py

`_SCHEMA` executescript gains (shared ground with the RUN fork; `IF NOT EXISTS` makes double-declaration safe — RUN fork adds run-state columns via `_migrate`):

```sql
CREATE TABLE IF NOT EXISTS automations (
  id TEXT PRIMARY KEY,
  owner TEXT NOT NULL,
  page_id TEXT REFERENCES pages(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT NOT NULL,
  target_component_id TEXT,
  schedule TEXT NOT NULL,
  tier TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'proposed',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_automations_owner ON automations(owner, page_id);
```

`status='proposed'` rows NEVER execute — the honest seam until the RUN fork lands its scheduler.

`_migrate` gains (the established additive pattern):
```python
if "accent" not in pcols:
    conn.execute("ALTER TABLE pages ADD COLUMN accent TEXT")
```
Thread `accent` through `create_page` (new keyword param, default None), `update_page` (`_UNSET` pattern), and every `Page(...)` row constructor.

New function — **one transaction, one `_conn()`** (does NOT call `create_page`/`insert_module`, which each open/commit their own connection; replicates their INSERT SQL inline):

```python
def insert_structure(owner: str, proposal: StructureProposal,
                     parent_page_id: str | None) -> tuple[list[Page], list[StoredModule], list[str]]:
    with _conn() as c:
        # 1. pages: uuid4 ids, _now() timestamps, position = max+1..., parent_id=parent,
        #    portal_x/y NULL (frontend auto-shelf), icon/accent from the spec.
        # 2. modules: per page, insert_module SQL + _record_version, page_id = the new page.
        # 3. automations: per StructureAutomation — page index resolved against the
        #    JUST-CREATED pages list (out of range → raise ValueError → route 422);
        #    target_component_id checked against that page's module component ids,
        #    no match → stored NULL (degrades to journal-only, never dangling);
        #    id = uuid4, status='proposed', tier/schedule from the (Pydantic-validated) spec.
    # a mid-insert exception rolls the whole transaction back — no partial structures.
```

New read: `page_overview(owner) -> dict[str, dict]` — one owner-scoped query set (never N+1):
```sql
SELECT p.id, COUNT(m.id) AS module_count
  FROM pages p LEFT JOIN modules m ON m.page_id = p.id AND m.archived = 0
 WHERE p.session_id = ? GROUP BY p.id;
SELECT page_id, COUNT(*) FROM automations WHERE owner = ? AND status != 'rejected' GROUP BY page_id;
```
Wire shape: `{page_id: {"modules": int, "automations": int, "last_run_at": null}}` — `last_run_at` is reserved and always null in this fork; the RUN fork fills it from its runs table. The frontend renders activity lines ONLY when non-null (never fabricated).

## 3. Orchestrator — backend/src/services/orchestrator.py

**No second prompt, no second generation route.** The existing `DECOMPOSE_SYSTEM_PROMPT` gains a STRUCTURES block (ONB-1: the same entry the interview/voice/sketch paths feed; there is no client-side signal that could route to a separate endpoint). Appended after the HOW MANY TOOLS section:

```
STRUCTURES (multi-surface systems): when the request is a whole life-area or an ongoing
operation that needs DISTINCT surfaces ("organize my whole life", "run my freelance
business", "manage the family"), output this OBJECT instead of "modules":
{
  "plan": "<one short paragraph: the system you will build and why>",
  "pages": [ 2-4 objects, each an APP SURFACE:
    { "name": "<short app name>", "icon": "<one icon name from the list above>",
      "accent": "<one accent token from the list above>",
      "purpose": "<one sentence: what this surface is for>",
      "modules": [ 1-6 ModuleConfig objects, exactly the shape above ] } ],
  "automations": [ 0-6 objects:
    { "name": "...", "description": "<plain language: exactly what it will do each run>",
      "schedule": "hourly|daily|weekly", "tier": "autonomous|consequential",
      "page": <index into pages>,
      "target_component_id": "<a component id on that page, usually a feed>" } ]
}
- A focused request still gets the flat {"plan","modules"} shape — never force pages.
- Give a page a "feed" component when an automation will report into it, and point
  target_component_id at it.
- tier: watch/sort/track/summarize/draft → "autonomous"; anything that would send, pay,
  message a human, or delete → "consequential". When unsure → "consequential".
```

`_COMPONENT_DOCS` gains:
```
- feed         — newest-first entries an automation writes into. Fields: id, label, type, max_items?.
                 Use as the landing surface for a digest/watcher automation product.
```

**Parsing** — extend `_parse_modules` in place (keep the name; three call sites stay untouched). `_Decomposition` gains `structure: StructureProposal | None = None`. Branch: `isinstance(data.get("pages"), list)` → structure path; else the existing flat path byte-for-byte. Structure sanitization (strip-don't-reject, a mistake costs one item):

1. Truncate pages to 4, each page's raw modules to 6 (clip BEFORE Pydantic — a 40-page answer is clipped, never raised on).
2. Per page: per raw module dict run `_sanitize_module_data_sources` then `ModuleConfig.model_validate`, dropping invalid modules individually; drop pages left with 0 modules.
3. Per automation: `StructureAutomation.model_validate` individually — missing tier → fail-closed default `"consequential"`; a garbage tier value fails the Literal and drops the automation (the parser can never sanitize an automation INTO autonomy). Then remap `page` through an original-index → surviving-index map; dropped/out-of-range page → drop the automation. `target_component_id` not found among that page's component ids → set to None (survives unwired). Clip to 6.
4. Zero surviving pages → if any valid modules existed anywhere in the payload, degrade to the flat-modules result (plan preserved, automations dropped); else `_InvalidOutput` (existing retry-once loop).

**Surfacing** — mirror the `last_plan` side-channel exactly so `generate_modules`' return type and every caller stay untouched:
```python
last_structure: contextvars.ContextVar[StructureProposal | None] = contextvars.ContextVar(
    "orchestrator_last_structure", default=None)
```
`generate_modules` resets it to None at entry; when `parsed.structure` is set it sets the var and returns `[]`. **Semantic cache: structure results are never stored** (the store guard adds `and parsed.structure is None`) — the cache value shape stays a flat config list; lookup is unchanged (a flat hit for a broad prompt is still a valid answer).

**File paths never produce structures** (v1): in `_generate_modules_grounded` and `generate_modules_from_file`, if the parse carries `structure`, degrade — `modules = [m for p in structure.pages for m in p.modules][:6]` — tools land flat, no pages. Documented limitation.

**Stub mode**: `stub_templates.pick_structure(prompt) -> dict | None` — ONE deterministic 2-page structure template (e.g. a "run my business" shape with a feed + one proposed daily-digest automation) returned for clearly-broad keyword matches, else None → existing `pick_system` flat path. This makes the ONB-1 A-flow drivable offline. `generate_modules`' stub branch checks it first and sets `last_structure`.

No new env vars → nothing added to conftest `_isolate_llm_env`.

## 4. Routes — backend/src/routes/modules.py

- `POST /api/modules/preview` and `POST /api/modules/generate` (existing, sync def → threadpool, already inside `_check_gen_budget`): after the orchestrator call, `structure = orchestrator.last_structure.get()`; if set, return `GenerateResponse(structure=structure, plan=plan, degraded=...)` **without persisting anything** (both routes — a structure only ever lands via confirm; ONB-1). Otherwise unchanged.
- `POST /api/structure` (new, `async def` — pure ms-scale DB work, mirrors `insert_modules`): body `InsertStructureRequest`, query `page_id` (the canvas the user is on; None → `ensure_default_page`). Zero LLM calls → no gen budget. Calls `db.insert_structure(sid, body.structure, page_id)`; a page-index ValueError → 422. Then `_accrete_profile_facts(sid, body.exchange, prompt=body.prompt, configs=all_configs)` (accretion fires HERE, on confirm — never on preview) and `_log(sid, "assistant", f"Created {page.name} — {n} tools", page_id=page_id)` per created page. Returns `InsertStructureResponse`. No client-supplied ids ever land: the DB layer mints every uuid4.
- `GET /api/pages/overview` (new, `async def`): `db.page_overview(sid)` — owner-scoped by construction.

Double-submit protection is client-side only (confirm button disabled while in flight) — parity with `insert_modules`; no idempotency table.

## 5. Frontend — portal → app tile

- `lib/portalLayout.ts`: `PORTAL_W = 240`, `PORTAL_H = 140` (constants only; shelf math, contentBounds, minimap follow; update the layout tests).
- New `components/PortalTile.tsx` — extract the inline tile from Canvas.tsx L806-856 verbatim first (same `role="button"`, tabIndex, aria-label, `startPortalDrag`/keyboard props — R-1305/R-1306 inherited), then restyle:
  - **Solid matte app card**: `bg-[var(--surface-elevated)]/80`, 1px solid `border-[var(--border)]` (hover → accent border, unchanged). **Dashed border is retained ONLY when `overview.modules === 0`** — an honest "under construction" state.
  - Icon chip tinted by `page.accent` via the `ACCENTS` map in `lib/theme.ts` (deterministic fallback from name when null — existing contract; never a model-authored color value).
  - Name (font-medium) + meta line in **Geist Mono 11px**: `{n} modules`, plus `· agent ran 7:02` ONLY when `overview.last_run_at` is non-null (null in this fork → line absent, never fabricated). `· {k} proposed` when automations exist with status proposed.
  - Small GridIcon stamp bottom-right at 40% opacity, `aria-hidden` (SURF-4 identity).
  - Footer: `APP` label (was "Page") + `Open ›`. `aria-label = "Open {name}, {n} modules"`.
  - NO mini-preview strip of child module accents (cut — requires loading child configs the parent deliberately doesn't).
- `Canvas.tsx`: prop `childCounts` replaced by `childOverviews?: Record<string, PageOverview>`; `page.tsx` fetches `GET /api/pages/overview` at the same refresh points `refreshChildCounts` uses today (replace that call). Fetch failure → tiles render name+icon only, no spinner, no fake data.

## 6. Frontend — zoom-in-is-launching (Canvas.tsx + page.tsx)

Pure math in `lib/portalLayout.ts` (it owns PORTAL_W/H; unit-testable DOM-free):
```ts
export const LAUNCH_ZOOM = 2; // == ZOOM_MAX — never overshoot the interactive clamp
export function launchTargetView(pos: PortalPoint, rect: { width: number; height: number },
                                 zoom = LAUNCH_ZOOM): { x: number; y: number; zoom: number } {
  const cx = pos.x + PORTAL_W / 2, cy = pos.y + PORTAL_H / 2;
  return { zoom, x: rect.width / 2 - cx * zoom, y: rect.height / 2 - cy * zoom };
}
```

Canvas.tsx additions (gsap already a dependency via assembly.ts):
```tsx
const launchingRef = useRef(false);
const launchTweenRef = useRef<gsap.core.Tween | null>(null);
const reducedMotion = () =>
  typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const [scrim, setScrim] = useState(false); // a bg-[var(--bg-overlay)] div, CSS opacity transition 150ms

const launchPortal = useCallback((pageId: string, pos: PortalPoint) => {
  if (launchingRef.current) return;                       // re-entrancy: double-click can't double-enter
  const rect = containerRef.current?.getBoundingClientRect();
  if (!rect || reducedMotion()) { onEnterPortalRef.current?.(pageId); return; }  // static fallback: instant swap
  launchingRef.current = true;
  const target = launchTargetView(pos, rect);
  const v = { ...latestViewRef.current };
  launchTweenRef.current = gsap.to(v, {
    ...target, duration: 0.4, ease: "power2.inOut",       // §8.2's zoom easing
    onUpdate: () => setView({ x: v.x, y: v.y, zoom: v.zoom }),
    onStart: () => setTimeout(() => setScrim(true), 280), // scrim fades in over the last beat
    onComplete: () => { launchingRef.current = false; onEnterPortalRef.current?.(pageId); },
  });
}, []);
```
- Wire points: `portalWinUp`'s click branch calls `launchPortal(ref.pageId, ref.startPos)` — **`startPos` from the gesture ref, never a recomputed index** (index-drift fix); the tile keyboard Enter/Space handler calls `launchPortal(page.id, portalPosition(page, i))`.
- **Interrupt**: in `onPointerDown` and `onWheel`, `if (launchingRef.current) { launchTweenRef.current?.kill(); launchingRef.current = false; onEnterPortalRef.current?.(pendingPageId); return; }` — never strand a half-zoomed parent.
- **View-save guard**: the debounced persist effect (L292-306) adds `if (launchingRef.current) return;` as its first line — mid-tween frames never write localStorage or PATCH the parent's saved viewport.
- **Arrival**: after the swap, the existing `[activePageId]` load effect resolves the child's view; `setScrim(false)` in that effect. No arrival zoom-settle tween (cut — highest race risk, lowest payoff; the forward zoom + scrim already satisfies SURF-1's "not a hard cut"). Fresh modules keep their existing assembly construction (§5.2).

**Reverse (breadcrumb / AppFrame back)** — counter idiom, matching fitReq/focusReq:
```tsx
// page.tsx
const [portalReturnReq, setPortalReturnReq] = useState<{ childId: string; n: number }>();
const handleBack = useCallback((childId: string, parentId: string) => {
  setActivePageId(parentId);
  setPortalReturnReq((p) => ({ childId, n: (p?.n ?? 0) + 1 }));
}, []);
```
```tsx
// Canvas.tsx — declared AFTER the [activePageId] load effect, so on the same commit
// the load effect first sets view = the parent's saved view and latches lastSavedViewRef.
useEffect(() => {
  if (!portalReturnReq) return;
  const rect = containerRef.current?.getBoundingClientRect();
  const i = (childPages ?? []).findIndex((p) => p.id === portalReturnReq.childId);
  if (!rect || i < 0) return;
  const saved = latestViewRef.current;                        // parent's just-loaded view
  if (reducedMotion()) return;                                // static: saved view already applied
  const start = launchTargetView(portalPosition(childPages![i], i), rect);
  lastSavedViewRef.current = { pid: activePageId!, v: saved }; // latch FINAL target — no echo PATCH
  launchingRef.current = true;
  setView(start);                                             // seed "inside" the tile
  const v = { ...start };
  gsap.to(v, { ...saved, duration: 0.4, ease: "power2.inOut",
    onUpdate: () => setView({ x: v.x, y: v.y, zoom: v.zoom }),
    onComplete: () => { launchingRef.current = false; } });
// eslint-disable-next-line react-hooks/exhaustive-deps
}, [portalReturnReq?.n]);
```
Back restores the exact saved parent viewport (§8.2); the tween only choreographs getting there. Reduced motion: both directions collapse to today's instant swap — a complete static end state (ETHOS-3).

## 7. Frontend — in-app frame + proposal flow

- New `components/AppFrame.tsx`, mounted by page.tsx **only when `activePage?.parent_id`** (root canvas untouched): a slim strip below the header — `←` back button (`aria-label="Back to {parent.name}"`, onClick → `handleBack(activePage.id, activePage.parent_id)`), accent-tinted icon + page name as `<h2>`, GridIcon stamp `aria-hidden`, right-aligned Geist Mono status line from the same overview data (`{n} modules` + `· agent ran …` only when last_run_at non-null; `· {k} proposed` for parked automations). Charcoal, 1px bottom border, zero new accent (magenta stays the PromptBar's primary action). Keyboard: Backspace/Alt+ArrowLeft trigger back, guarded by the existing not-while-typing check pattern.
- `components/PromptBar.tsx`: when a preview response carries `structure`, render the **structure proposal card** instead of the flat preview stack: plan paragraph; explicit line `Creates {n} app pages on your canvas`; per-page rows (icon, name, purpose, module count); per-automation rows (name, plain-language description, schedule, tier chip — `AUTONOMOUS` muted / `NEEDS YOUR TAP` outlined) with a `Proposed — not running yet` mono note (honesty seam). Confirm → `api.insertStructure(structure, prompt, activePageId, exchange)`; Dismiss discards (nothing lands, nothing accretes). On success page.tsx merges returned pages into `pages` state, refreshes overview, bumps `fitReq` (the new portal shelf frames in; tiles construct per the assembly pattern).
- `components/primitives/Feed.tsx` + a `case "feed"` in the component renderer (componentFactory/Module): newest-first rows, Geist Mono timestamps, plain-text title/body as React text nodes only (no `dangerouslySetInnerHTML` — SURF-2 grep stays clean), badge pills using the muted `--status-*-dim` tokens, `max_items` display cap, empty state "Nothing yet — the agent hasn't run." Plus a `lib/summary.ts` case (`"{n} updates"`).
- `lib/types.ts`: `FeedComponent`, `StructurePage`, `StructureAutomation`, `StructureProposal`, `PageOverview`; `GenerateResponse.structure?`; `Page.accent?`.
- `lib/api.ts` (in the existing `api` object literal): `insertStructure(structure, prompt, pageId?, exchange?)` → `POST /api/structure?page_id=`, `pagesOverview()` → `GET /api/pages/overview`.

## 8. File-level change list

Backend: `src/schema.py` (Feed + union; StructureAutomation/StructurePage/StructureProposal; GenerateResponse.structure; InsertStructureRequest/Response; Page.accent trio) · `src/services/orchestrator.py` (prompt block; feed doc line; `_Decomposition.structure`; `_parse_modules` structure branch + sanitizers; `last_structure` contextvar; cache-store guard; file-path degrade) · `src/routes/modules.py` (structure passthrough on preview/generate; `POST /api/structure`; `GET /api/pages/overview`) · `src/db.py` (automations table + index in `_SCHEMA`; pages.accent in `_migrate`; accent threading; `insert_structure`; `page_overview`) · `src/stub_templates.py` (`pick_structure`).

Frontend: `lib/portalLayout.ts` (PORTAL_W/H; `launchTargetView`; LAUNCH_ZOOM) · `components/PortalTile.tsx` (new, extracted) · `components/Canvas.tsx` (PortalTile swap; `launchPortal`; return effect; launchingRef save guard; scrim; interrupt; `childOverviews` prop) · `components/AppFrame.tsx` (new) · `app/page.tsx` (`handleBack` + `portalReturnReq`; AppFrame mount; overview fetch replacing `refreshChildCounts`; structure confirm handler) · `components/PromptBar.tsx` (structure proposal card) · `components/primitives/Feed.tsx` (new) + renderer case + `lib/summary.ts` case · `lib/types.ts`, `lib/api.ts`.

## 9. Test contract (the gate for this fork)

Backend (pytest): (1) structure parse happy path; (2) size ceiling — 40 pages × 30 modules clips to 4×6, never raises; (3) sanitize-not-reject — one bad module drops only itself, an emptied page drops, its automation drops; (4) tier fail-closed — missing tier → consequential, garbage tier → automation dropped, parser can never emit autonomous the raw JSON didn't state; (5) automation page-index remap after a page drop; unknown target_component_id → NULL; (6) zero-pages degrade to flat modules; (7) preview returns structure and persists nothing; (8) confirm transactionality — injected failure on automation #2 → zero pages/modules/automations persisted (monkeypatched conn); (9) cross-owner isolation — A's structure invisible to B via pages/overview (Stage-1 pattern); (10) cache — structure results never stored; a stale flat entry still falls through; (11) budget — preview 429s past `_check_gen_budget` (fake-time `_RateLimiter.allow(now=...)`), confirm consumes no budget; (12) Feed validation bounds; (13) file path degrades structure to flat; (14) restart — confirmed structure fully present after reopen; (15) stub `pick_structure` drives the full ONB-1 A-flow offline.

Frontend (vitest): portalLayout constants + `launchTargetView` symmetry (forward target == reverse seed for the same tile); view-save guard logic (launchingRef true → no save); reduced-motion branch returns instant swap. `C:` grep — no `dangerouslySetInnerHTML` on Feed/PortalTile/AppFrame paths (SURF-2).

Cross-fork seam note: the `automations` table columns and the tier vocabulary here are the shared contract with the RUN/AUT fork — that fork adds run-state columns via `_migrate`, flips status from `proposed`, and populates `last_run_at` in `page_overview`. Until then every activity line in tile/AppFrame renders nothing (never a stub that looks live).

## Key decisions (contested points, ruled)

- Single entry point (Take 1 skeleton): the structure shape is emitted by the extended DECOMPOSE_SYSTEM_PROMPT through the existing /api/modules/preview — Takes 2/3's separate /api/structure/preview has no caller-side routing signal, and ONB-1 explicitly requires 'the same entry the interview/voice/sketch paths feed'.
- Surface = existing child Page; no new entity — portal tiles, page rows, and view persistence are all reused, only upgraded.
- Tier is fail-closed (Take 3 over Take 1): default 'consequential', garbage values drop the automation; the parser can never sanitize an automation into autonomy; Take 2's action-derived tier recompute cut to avoid vocabulary drift with the RUN fork.
- Automations reference pages by index into the proposal (Take 3), not by name (Take 1) or DB id — no duplicate-name ambiguity and no model-authored ids ever touch the DB; the server mints every uuid4.
- Structure insert is ONE _conn() transaction (Take 3) — a mid-insert crash leaves nothing partial; Take 3's proposal_id idempotency table cut as gold-plating (client disables confirm in flight, parity with insert_modules).
- Launch zoom target = ZOOM_MAX (2.0) + a scrim beat, rejecting Take 3's viewport-filling ~4.6x overshoot — nothing ever exceeds the clamp wheel/pinch enforce, so a mid-tween gesture can't fight the tween; interrupt kills the tween and enters immediately.
- The hard page swap is kept, hidden at the end of the forward tween and the start of the reverse tween; reverse uses the fitReq/focusReq counter idiom with the return effect declared after the [activePageId] load effect and lastSavedViewRef latched to the final target (no echo PATCH); launchingRef suppresses the debounced view save both directions.
- No arrival zoom-settle choreography (Take 2's entryMotion cut) — highest race risk for the least payoff; the scrim masks the swap and module assembly keeps construction-not-fade; reduced-motion collapses both directions to today's instant swap.
- Exactly one new trusted component: Feed (plain-text entries, closed badge set, bounded max_items) — 'rich stat rows' rejected as speculative since kpi/metric/chart/table already cover it.
- icon/accent stay plain optional strings with the existing frontend deterministic-fallback contract — Take 3's Literal enums + sanitize-to-None cut; rendering already goes through resolveIconName/ACCENTS, never raw values.
- Semantic cache: structure results are never stored in v1 (Take 1) — the cache value shape stays a flat config list; Takes 2/3's 'structure' cache kind cut (stale-replay and duplicate-automation risks for marginal savings on rare broad prompts).
- File-upload/grounded paths degrade a structure to flat modules (no structure-from-file v1) — prevents an IndexError-class break in generate_from_file now that the shared prompt can emit pages.
- Portal tile: 240x140 solid matte app card (dashed retained only for 0-module pages as an honest under-construction state); live status lines render ONLY when the overview supplies real data (last_run_at is reserved-null until the RUN fork lands); Take 2's mini accent-strip preview cut.
- GET /api/pages/overview replaces the childCounts fetch client-side with one grouped owner-scoped query (counts + automation counts + reserved last_run_at); the old module_counts endpoint is left untouched.
- The automations table ships here in _SCHEMA with status='proposed' rows that never execute — the honest seam and the shared-ground contract the RUN/AUT fork extends via additive _migrate columns.
