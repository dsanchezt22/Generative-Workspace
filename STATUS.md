# Trus — Project Status

_An AI-orchestrated personal operating system: describe what you want to organize, and the system generates the exact tool for it._

**Last updated:** 2026-06-14
**Repo:** https://github.com/dsanchezt22/Generative-Workspace
**North star:** the exact tool you need, in the shape of your life, for the cost of a sentence — and you stay in the driver's seat the entire time.

---

## Architecture (the one decision everything rests on)

The AI **never generates UI code**. The orchestrator turns a prompt into a typed
`ModuleConfig` (JSON: which components, how they bind, what's prefilled), and the
frontend renders that config with a fixed, trusted component library. This keeps
output instant, consistent, and impossible to break into "malformed HTML."

```
prompt ──▶ Gemini (orchestrator) ──▶ ModuleConfig (JSON) ──▶ trusted components ──▶ canvas
```

- **Backend:** Python 3.12 · FastAPI · SQLite (stdlib) · `google-genai`
- **Frontend:** Next.js 16 · React 19 · TypeScript · Tailwind v4
- **Model:** `gemini-flash-latest` (key in `backend/.env`, gitignored)
- **Quality:** 82 backend tests passing, 2 live tests opt-in (`GEMINI_LIVE=1`)

---

## 1. Modules built (the building blocks)

### Backend (`backend/src/`)
| Module | Responsibility |
|---|---|
| `schema.py` | `ModuleConfig`, the 6 component types (discriminated union), `ModuleVersion`, `RefusalError`, `LLMError` |
| `db.py` | SQLite layer: sessions, modules, version history; connection-time schema (self-healing) |
| `llm.py` | Gemini call (JSON mode + system instruction); offline stub fallback when no key |
| `services/orchestrator.py` | Prompt → ModuleConfig; template-as-seed + adapt-to-content; honest refusal |
| `stub_templates.py` | Intent-routed offline templates (workout/calorie/budget/todo/reading/habit/mood + generic) |
| `routes/modules.py` | The 7 HTTP endpoints (below) |
| `main.py` | App wiring, session cookie middleware, CORS, lifespan DB init |

**API surface:**
`POST /api/modules/generate` · `GET /api/modules` · `PATCH /api/modules/{id}` ·
`DELETE /api/modules/{id}` · `POST /api/modules/{id}/refine` ·
`POST /api/modules/{id}/undo` · `GET /api/modules/{id}/history`

### Frontend (`frontend/src/`)
| Module | Responsibility |
|---|---|
| `app/page.tsx` | Workspace shell, module state, refine wiring |
| `components/Canvas.tsx` | Infinite pan/zoom canvas; module drag, resize |
| `components/Module.tsx` | Renders a ModuleConfig; collapse, edit, undo, refine, delete |
| `components/PromptBar.tsx` | Generate + refine prompt input; refusal/error surfacing |
| `components/primitives/` | The 6 component renderers |
| `lib/api.ts` | Typed API client (credentials-included) |
| `lib/summary.ts` | One-line collapsed-module summary deriver |
| `lib/componentFactory.ts` | Default component builders for the edit palette |
| `lib/types.ts` | Shared TS types mirroring the backend schema |

### Component library (6 primitives)
`text_input` · `number_input` · `checkbox` · `slider` · `progress_bar` (with reactive `bound_to`) · `list`

---

## 2. Feature set — status vs. the design doc (Part II)

| # | Feature | Status | Notes |
|---|---|---|---|
| 1 | **The Canvas** | ✅ Done | Infinite pan/zoom, dotted grid, modules as first-class objects, drag + resize, reset-view |
| 2 | **Modules (atomic unit)** | ✅ Done | Card anatomy, collapse-to-summary, skeleton-first creation |
| 3 | **Multi-modal input** | 🟡 Partial | Text ✅. Voice / document+image upload / drawing / ramble-to-modules ❌ |
| 4 | **Orchestrator + component library** | ✅ Done | Config-not-code; 6 primitives (library is intentionally extensible) |
| 5 | **Module intelligence** (cross-module rules, AI extrapolation, external data binding) | ✅ Done (core) | `metric` component aggregates values across modules; cross-module `progress_bar` binding; AI receives full module context on generate/refine; "Workspace insights" synthesizes a dashboard module. External data binding ❌ |
| 6 | **Pages & infinite depth** | ✅ Done (core) | Named pages (Main + user-created), per-page canvases, module scoping by page_id. Nesting/embedding ❌ |
| 7 | **Collaboration** | ❌ Not started | Single anonymous session; no sharing/real-time |
| 8 | **History, versioning & undo** | ✅ Done (core) | Version snapshots, per-module undo, history endpoint. No snapshot-viewer UI / global undo yet |
| 9 | **External integrations** | ❌ Not started | No calendar/API/device hooks |
| 10 | **Manual control & escape hatches** | ✅ Done | Rename, add/remove/relabel fields, manual data entry, drag, resize |
| 11 | **Computational hygiene & credits** | ❌ Not started | No credit model, no archive/simplify suggestions |
| 12 | **Guardrails & boundaries** | ✅ Done (core) | Honest refusal (`{"refusal":…}` → 422); graceful LLM-failure (503). No cost pre-warning |

**Part II.2.3 — module lifecycle:** Create ✅ · Populate ✅ · Iterate ✅ (refine-by-chat + manual edit + undo) · Connect ❌ · Archive ❌

**Part III — the output:** config-not-code ✅ · aesthetic (calm dark theme, warm neutrals, amber accent, motion) ✅ · texture of creation (fast, visual) ✅. Missing: inline clarifying questions during creation.

**Ethos (Part I):** generation-over-configuration ✅ · user-in-driver's-seat ✅ · reliability-is-the-product ✅ (tests, graceful failure, persistence) · minimal-intrusion 🟡 (no clarifying-question step yet) · consolidation — not yet exercised (depends on integrations/pages).

---

## 3. What's left (roughly prioritized)

**High value, unblocked now**
1. ~~**Module intelligence (II.5)**~~ ✅ Done
2. **Pages & infinite depth (II.6)** — multiple canvases (Work, Health, Finances) and embedding; the primary defense against canvas clutter.
3. **External data binding (II.5.3)** — e.g. a calorie tracker that fetches an item's calories on the spot. The "generative UI + real functionality" moat.
4. **Richer creation (II.3 + minimal-intrusion)** — the inline clarifying-question step; ramble-to-modules; voice and document/image upload.

**Depends on the above / larger lifts**
5. **Collaboration (II.7)** — shared pages, real-time sync, presence (needs real auth).
6. **External integrations (II.9)** — Google Calendar, devices, generic APIs.
7. **Computational hygiene & credits (II.11)** — cost model, archive/simplify nudges.
8. **History UX (II.8 polish)** — snapshot viewer, global undo, change-log panel.

**Platform / hardening**
- Real authentication (currently anonymous session cookie) — prerequisite for collaboration.
- Expand the component library beyond 6 primitives (date picker, calendar/heatmap, table, chart variants).
- Module archive + restore.
- Viewport spatial memory (persist pan/zoom per workspace).
- Deployment (frontend + backend hosting, managed Postgres in place of SQLite at scale).

---

## Known limitations / notes
- **Persistence:** SQLite single-file DB; fine for one machine, not yet multi-instance.
- **Auth:** anonymous per-browser session — no accounts, no cross-device sync.
- **Offline mode:** with no/placeholder key the app falls back to fixed stub templates (intent-routed) so the pipeline still runs without spending credits.
- **Billing:** live generation requires a funded Gemini key; failures degrade to a clean in-app message, not a crash.
