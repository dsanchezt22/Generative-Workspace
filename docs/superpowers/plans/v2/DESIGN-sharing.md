# V2 committed design — sharing

> Produced by a 3-take + adversarial-judge council on 2026-07-06.
> This is the spec the implementation follows verbatim.

# FORK 4 — COMMITTED DESIGN: Per-surface read-only sharing

Skeleton: Take 1. Grafts: Take 2's `adopt_session_data` migration + revoked-owner join; Take 3's server-side `data_source` strip, no-referrer metadata, and page-id-free payload.

---

## 1. Backend — `backend/src/db.py`

### 1a. Imports
Add `import secrets` to the import block at the top.

### 1b. DDL — append to `_SCHEMA` (new table → `CREATE TABLE IF NOT EXISTS` alone covers old DBs; no `_migrate` entry)

```sql
-- Per-surface read-only share links (SHARE-1..3). ONE ACTIVE link per page,
-- enforced by the partial unique index (DB guarantee) and by share_create's
-- revoke-then-insert transaction. Revoked rows are kept as audit history.
-- owner is the same _owner_id key as everywhere else (claimed uid, or dev-only
-- anon sid). token is secrets.token_urlsafe(32) — 256 bits, unguessable;
-- UNIQUE gives the indexed lookup for the public path.
CREATE TABLE IF NOT EXISTS share_links (
    id          TEXT PRIMARY KEY,
    token       TEXT NOT NULL UNIQUE,
    owner       TEXT NOT NULL,
    page_id     TEXT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL,
    revoked_at  TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_share_links_active
    ON share_links(page_id) WHERE revoked_at IS NULL;
```

### 1c. `adopt_session_data` — REQUIRED addition (bug found in review)
Append to the UPDATE list inside the existing `with _conn() as c:` block:
```python
        c.execute("UPDATE share_links SET owner = ? WHERE owner = ?", (user_id, old_owner))
```
Without this, a pre-claim share link dies on claim AND the still-active orphan row makes the next `share_create` violate the partial unique index → 500.

### 1d. New db functions (append after the snapshots section; all via per-call `_conn()`, owner-scoped WHERE, `_now()` timestamps, uuid4 ids)

```python
# ---------------------------------------------------------------------------
# Share links (SHARE-1..3)
# ---------------------------------------------------------------------------


def share_create(owner: str, page_id: str) -> dict | None:
    """Create-or-rotate: revokes any active link for this page, mints a new one,
    all in ONE transaction (the partial unique index never trips mid-rotate).
    Returns None when the page isn't this owner's — indistinguishable from
    nonexistent, matching the _require_own_parent stance."""
    with _conn() as c:
        if not c.execute(
            "SELECT 1 FROM pages WHERE id = ? AND session_id = ?", (page_id, owner)
        ).fetchone():
            return None
        now = _now()
        c.execute(
            "UPDATE share_links SET revoked_at = ? WHERE page_id = ? AND owner = ? AND revoked_at IS NULL",
            (now, page_id, owner),
        )
        token = secrets.token_urlsafe(32)
        c.execute(
            "INSERT INTO share_links (id, token, owner, page_id, created_at) VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), token, owner, page_id, now),
        )
    return {"token": token, "created_at": now}


def share_status(owner: str, page_id: str) -> dict | None:
    with _conn() as c:
        r = c.execute(
            "SELECT token, created_at FROM share_links"
            " WHERE page_id = ? AND owner = ? AND revoked_at IS NULL",
            (page_id, owner),
        ).fetchone()
    return dict(r) if r else None


def share_revoke(owner: str, page_id: str) -> bool:
    with _conn() as c:
        cur = c.execute(
            "UPDATE share_links SET revoked_at = ? WHERE page_id = ? AND owner = ? AND revoked_at IS NULL",
            (_now(), page_id, owner),
        )
        return cur.rowcount > 0


def share_resolve(token: str) -> dict | None:
    """Public-path lookup — the ONLY function that reads a token; its ONLY
    caller is GET /api/share/{token}. Joins pages (name/icon in one query) and
    LEFT JOINs users so a REVOKED owner's shares die with them (R-905 — the
    public path bypasses _owner_id's per-request revocation check, so it must
    re-check here). Anon (dev) owners have no users row → LEFT JOIN passes.
    None for unknown token, revoked link, cascade-deleted page, or revoked
    owner — one indistinguishable outcome."""
    with _conn() as c:
        r = c.execute(
            "SELECT s.owner, s.page_id, p.name, p.icon, u.revoked_at AS user_revoked"
            " FROM share_links s JOIN pages p ON p.id = s.page_id"
            " LEFT JOIN users u ON u.id = s.owner"
            " WHERE s.token = ? AND s.revoked_at IS NULL",
            (token,),
        ).fetchone()
    if r is None or r["user_revoked"]:
        return None
    return {"owner": r["owner"], "page_id": r["page_id"], "name": r["name"], "icon": r["icon"]}
```

---

## 2. Backend — `backend/src/schema.py` (additive models, near Page/StoredModule)

Never reuse `Page` (serializes `session_id`, `parent_id`, `position`, `portal_*`, `view_*`) or `StoredModule` (serializes `page_id`, `rev`, `archived`). Whitelist by construction:

```python
class ShareStatus(BaseModel):
    active: bool
    token: str | None = None
    created_at: str | None = None


class SharedPage(BaseModel):
    name: str
    icon: str | None = None


class SharedModule(BaseModel):
    id: str                # needed: React keys + same-page cross-module bindings
    config: ModuleConfig   # data_source stripped by the route before construction
    updated_at: str        # the "as of" honesty stamp


class SharedPageResponse(BaseModel):
    page: SharedPage
    modules: list[SharedModule]
```

Exposed, exhaustively: page `name`+`icon`; per non-archived module `id`, `config` (with every component's `data_source` nulled), `updated_at`. Never: owner/session ids, page id, parent_id/position/portal_*/view_*, rev, archived rows, other pages, child pages, messages, snapshots, versions, profile, gen telemetry, users/invites.

---

## 3. Backend — NEW file `backend/src/routes/share.py`

```python
"""Per-surface read-only sharing (SHARE-1..3)."""

import os

from fastapi import APIRouter, HTTPException, Request

from src import db
from src.routes.deps import _RateLimiter, _owner_id
from src.schema import SharedModule, SharedPage, SharedPageResponse, ShareStatus

router = APIRouter()


# Fresh-per-call env knobs (the _gen_rate_max pattern) — never import-time constants.
def _share_rate_max() -> int:
    return int(os.environ.get("TRUS_SHARE_RATE_MAX", "60"))


def _share_rate_window() -> float:
    return float(os.environ.get("TRUS_SHARE_RATE_WINDOW", "60"))


# Its own limiter instance — anonymous readers must never eat an owner's
# generation/live/transcribe budget. No LLM call happens on this path, so
# _check_gen_budget is deliberately not involved.
_share_limiter = _RateLimiter(max_calls=60, window_secs=60)


# ── Owner-gated management (session cookie via _owner_id; foreign page ≡ 404) ──


@router.post("/pages/{page_id}/share", response_model=ShareStatus, status_code=201)
async def create_share(page_id: str, request: Request) -> ShareStatus:
    """Create-or-rotate: calling again mints a new token and kills the old."""
    sid = _owner_id(request)
    created = db.share_create(sid, page_id)
    if created is None:
        raise HTTPException(status_code=404, detail="Page not found")
    return ShareStatus(active=True, token=created["token"], created_at=created["created_at"])


@router.get("/pages/{page_id}/share", response_model=ShareStatus)
async def get_share(page_id: str, request: Request) -> ShareStatus:
    sid = _owner_id(request)
    if db.get_page(sid, page_id) is None:
        raise HTTPException(status_code=404, detail="Page not found")
    status = db.share_status(sid, page_id)
    if status is None:
        return ShareStatus(active=False)
    return ShareStatus(active=True, token=status["token"], created_at=status["created_at"])


@router.delete("/pages/{page_id}/share", status_code=204)
async def revoke_share(page_id: str, request: Request) -> None:
    sid = _owner_id(request)
    if db.get_page(sid, page_id) is None:
        raise HTTPException(status_code=404, detail="Page not found")
    db.share_revoke(sid, page_id)  # idempotent: 204 even when already inactive


# ── The public read path — the ONLY route that accepts a token; reads only ──


@router.get("/share/{token}", response_model=SharedPageResponse)
async def read_shared(token: str, request: Request) -> SharedPageResponse:
    """NO session: never reads request.session, never calls _owner_id — no
    Set-Cookie is emitted, no sessions row is minted, and it works under
    TRUS_ALLOW_ANON=0. Unknown, revoked, rotated-away, cascade-deleted, and
    revoked-owner tokens all return the identical 404."""
    key = request.client.host if request.client else "unknown"
    if not _share_limiter.allow(key, max_calls=_share_rate_max(), window_secs=_share_rate_window()):
        raise HTTPException(status_code=429, detail="Too many requests.")
    link = db.share_resolve(token)
    if link is None:
        raise HTTPException(status_code=404, detail="Not found")
    mods = db.list_modules(link["owner"], link["page_id"])  # non-archived only (default)
    out = []
    for m in mods:
        cfg = m.config.model_copy(deep=True)
        # Strip live bindings server-side (defense in depth): DataSource.query
        # can carry location-like data, and the public view never fetches live
        # values anyway (/api/live is session-gated). Typed strip — every
        # component class that can carry one has the field by name.
        for comp in cfg.components:
            if getattr(comp, "data_source", None) is not None:
                comp.data_source = None
        out.append(SharedModule(id=m.id, config=cfg, updated_at=m.updated_at))
    return SharedPageResponse(page=SharedPage(name=link["name"], icon=link["icon"]), modules=out)
```

`async def` matches the house pattern for fast DB-only handlers (`pages.py`); the event-loop constraint targets LLM/blocking work, none of which runs here.

### 3a. `backend/src/main.py`
Add `share` to the routes import and `app.include_router(share.router, prefix="/api")` alongside the existing nine.

### 3b. `backend/tests/conftest.py`
Add `"TRUS_SHARE_RATE_MAX", "TRUS_SHARE_RATE_WINDOW"` to `_isolate_llm_env`'s delenv tuple.

### Security invariants (each has a test in §5)
1. The token is accepted by exactly one route, `GET /api/share/{token}`, which performs only SELECTs and constructs only whitelisted models. No mutation route reads a token — a token in a query/body/header of any PATCH/POST/DELETE is ignored bytes.
2. All management routes resolve `_owner_id` first; foreign page id ≡ nonexistent (uniform 404).
3. The public payload can only contain the one page's name/icon + its own non-archived modules (`share_resolve` joins on page; `list_modules` carries owner + page_id).
4. Enumeration resistance: byte-identical 404s; 256-bit token; per-IP sliding-window limit.
5. No session on the public path (no cookie read, no Set-Cookie, works with `TRUS_ALLOW_ANON=0`).
6. Revocation (link OR owner) is checked on every resolve — instant, no caching. Deploy docs (`deploy/README.md`): add one line forbidding response caching of `/api/share/*`.
7. Child pages are structurally absent: no page tree in the payload, no portal layer in the renderer, no endpoint resolves a child by token. Cross-page `source_module_id`/Metric bindings cannot leak: resolution is client-side over the delivered module list (Canvas.tsx:111-125 pattern), which contains only the shared page's modules — an off-page binding resolves to undefined and falls back to saved state.

---

## 4. Frontend

### 4a. `lib/types.ts` (additive)
```ts
export interface ShareStatus { active: boolean; token: string | null; created_at: string | null; }
export interface SharedModule { id: string; config: ModuleConfig; updated_at: string; }
export interface SharedPageResponse { page: { name: string; icon: string | null }; modules: SharedModule[]; }
```

### 4b. `lib/api.ts` (additive entries on the `api` object literal; reuse `request` — the public handler ignores any cookie sent)
```ts
shareStatus: (pageId: string) => request<ShareStatus>(`/api/pages/${pageId}/share`),
shareCreate: (pageId: string) => request<ShareStatus>(`/api/pages/${pageId}/share`, { method: "POST" }),
shareRevoke: (pageId: string) => request<void>(`/api/pages/${pageId}/share`, { method: "DELETE" }),
fetchShared: (token: string) => request<SharedPageResponse>(`/api/share/${encodeURIComponent(token)}`),
```

### 4c. NEW `lib/crossModule.ts`
Move `computeMetric` and `crossModuleValues` verbatim out of `Canvas.tsx` (lines 93-125) into this file; export both; `Canvas.tsx` imports them (its call site at line 865 is unchanged). The shared surface imports the same helper — one implementation, page-scoped by whatever module array it is handed.

### 4d. `components/Module.tsx` — new `"shared"` variant (decision: `"preview"` does NOT suffice — it bubbles edits in-memory via `onChange` at line 133, so inputs accept edits that silently vanish)
```ts
variant?: "canvas" | "detail" | "preview" | "shared";
const shared = variant === "shared";
```
- In `setField` (line 113): first line `if (shared) return;` — structurally inert, covering every primitive AND the button-action dispatcher at lines 196-199, present and future.
- Wrap the rendered component fields in `<fieldset disabled={shared} className="contents">` so every native control is truly disabled and out of tab order (a11y-honest, not pointer-events theater).
- Gate the header action cluster (the `!preview && (...)` block at line 397) to `!preview && !shared`; the share page passes no drag/resize/archive/undo/refine/expand handlers.
- `canvas`/`detail`/`preview` behavior untouched.

### 4e. NEW `components/SharePanel.tsx` — the share affordance
Modeled on `SnapshotsPanel.tsx`: right-side `role="dialog"` aside via `useDialog`. Props: `{ pageId: string; onClose: () => void; onStateChange: (active: boolean) => void }`. On open, fetches `api.shareStatus(pageId)` (re-displays the existing token — never re-POSTs just to show the link). Contents, Geist Mono for state:
- Inactive: status line `PRIVATE`; copy "Anyone with the link can view this surface, read-only. Nothing else — no other pages, no profile."; **Create link** button — the screen's ONE magenta accent while the panel is open.
- Active: status line `LINK ACTIVE · <created_at>`; the full URL `${location.origin}/share/${token}` in a mono read-only field + Copy button; **Rotate link** (neutral, via existing `ConfirmDialog`: "The old link stops working immediately.") calling `shareCreate`; **Revoke** (destructive register, via `ConfirmDialog`) calling `shareRevoke`. One honesty line: "This link shares the page's current and future contents, not a snapshot."

### 4f. `app/page.tsx` (Home owns state)
- `const [shareOpen, setShareOpen] = useState(false);` plus `const [shareActive, setShareActive] = useState(false);`.
- On `activePageId` change, fire `api.shareStatus(activePageId).then(s => setShareActive(s.active)).catch(() => setShareActive(false))`.
- Page header (next to the page title cluster): a share icon button opening the panel, and — when `shareActive` — a small muted Geist Mono pip `SHARED` (SHARE-2's always-visible state; NOT magenta).
- Panel exclusivity: opening SharePanel closes convo/archived/snapshots/profile panels and vice versa (same setter groups); add `setShareOpen(false)` to the Escape handler at line 798.
- Render `{shareOpen && <SharePanel pageId={activePageId} onClose={...} onStateChange={setShareActive} />}` alongside the other panels.

### 4g. NEW public route — `app/share/[token]/page.tsx` (server component) + `components/SharedSurface.tsx` (client)
`page.tsx` (server): `export const metadata = { referrer: "no-referrer" }` (the token is a credential in the URL — never leak it via Referer); Next 16: `const { token } = await params;` then render `<SharedSurface token={token} />`.

`SharedSurface.tsx` (`"use client"`): calls `api.fetchShared(token)` on mount. States:
- Loading: mono `RESOLVING LINK…`.
- Error/404: full-page honest dead end, GridIcon stamp + `THIS LINK IS NO LONGER ACTIVE` — identical for never-existed vs revoked.
- Success:
  - **Chrome**: slim top bar — page icon + name; persistent Geist Mono badge `SHARED VIEW · READ-ONLY · as of <latest module updated_at, relative>`; "Made with Trus" wordmark right. NO Sidebar, PromptBar, CommandPalette, panels, portal layer, pan/zoom, or selection — the interaction surface is absent, not disabled.
  - **Layout**: static absolutely-positioned wrappers from each `config.layout` (normalize by subtracting min x/y across modules; container sized to the bounding box, inside an `overflow-auto` charcoal dotted-grid area) — the surface renders as the owner arranged it, without dragging in Canvas.tsx's drag/resize/saver machinery.
  - **Modules**: `<Module variant="shared" module={m} crossModuleValues={crossModuleValues(payload.modules-as-StoredModule-shape, m)} ... />` using `lib/crossModule.ts` (SharedModule is structurally assignable to the fields crossModuleValues reads: id + config.state/components).
  - **Motion**: run `lib/assembly.ts`'s module-entrance sequence on mount (construction-not-fade — the surface builds itself for the recipient); `prefers-reduced-motion` → static final state.
  - Never calls `/api/live` (session-gated; data_source is stripped server-side anyway) — components render last-persisted state.

---

## 5. Tests

### `backend/tests/test_share.py` (house style: TestClient, per-test `TRUS_DB_PATH`, monkeypatch env, `allow(now=...)` — never sleep)
1. `test_create_returns_urlsafe_token` — POST on own page → 201, `active=True`, token ≥ 43 urlsafe chars, unique across creates.
2. `test_status_lifecycle` — GET before create → `{active: false, token: null}`; after create → matches; after DELETE → inactive; DELETE again → 204 (idempotent).
3. `test_rotate_kills_old_token` — POST twice: old token → 404 on public GET, new → 200; status shows only the new token.
4. `test_one_active_link_per_page` — after N rotations, exactly one `revoked_at IS NULL` row (direct db assert); a direct second active INSERT raises `sqlite3.IntegrityError` (partial index holds).
5. `test_unknown_revoked_deleted_indistinguishable` — random token vs revoked token vs token whose page was deleted (FK cascade) → identical status + body.
6. `test_owner_isolation_management` — client B POST/GET/DELETE on A's page → 404, identical to nonexistent-page 404.
7. `test_share_routes_require_auth` — `TRUS_ALLOW_ANON=0`, no session: POST/GET/DELETE management → 401.
8. `test_public_payload_field_allowlist` — walk the serialized JSON recursively: page keys exactly `{name, icon}`; module keys exactly `{id, config, updated_at}`; no `session_id`/`owner`/`rev`/`archived`/`parent_id`/`portal_x`/`view_x` keys anywhere; A's owner id absent from the raw body.
9. `test_other_pages_never_leak` — owner has pages X (shared) and Y; share(X) body contains only X's module ids, Y's absent.
10. `test_child_pages_invisible` — child of X with modules → zero references to child page name/id or its modules' ids in the payload; the child's own page/module routes still 401/404 without auth.
11. `test_cross_page_binding_no_leak` — module on X with `source_module_id` → module on Y: payload module set == X's only.
12. `test_archived_excluded` — archive a module on X → gone from the payload.
13. `test_data_source_stripped` — module with a weather DataSource → every component's `data_source` is null in the payload; owner's stored config unchanged.
14. `test_mutation_routes_never_accept_token` — `TRUS_ALLOW_ANON=0`, no cookie: PATCH /api/modules/{id}, DELETE /api/modules/{id}, PATCH /api/pages/{id}, POST /api/modules/generate — each with the valid token as query param, `Authorization` header, and `X-Share-Token` header → all 401; DB unchanged (direct assert). (SHARE-3)
15. `test_public_path_no_session_cookie` — public GET response has no `set-cookie` header; sessions row count unchanged.
16. `test_public_path_works_anon_disabled` — `TRUS_ALLOW_ANON=0`: claimed owner shares; cookie-less GET → 200.
17. `test_revoked_owner_kills_shares` — `db.revoke_user(owner)` → owner's active token → 404 (R-905).
18. `test_adopt_migrates_share_links` — anon sid creates a share; `adopt_session_data(sid, uid)`; token still resolves; `share_status(uid, page)` active; a subsequent `share_create(uid, page)` rotates cleanly (no IntegrityError).
19. `test_rate_limit_429` — monkeypatch `TRUS_SHARE_RATE_MAX=2`: two GETs 200, third 429 (proves fresh-per-call env read); separate `_RateLimiter.allow(now=...)` unit assert for window expiry — no sleeping.
20. `test_share_nonexistent_page_404` — POST share on a random uuid → 404.
21. `test_public_path_writes_nothing` — modules/messages/gen_events/sessions row counts identical before/after a public GET.
22. (db unit) `test_share_create_foreign_page_returns_none`.

### Frontend (vitest, existing `*.test.ts` convention)
23. `lib/crossModule.test.ts` — moved logic: metric sum/count/avg/max/min; `source_module_id` pointing at an absent module → key absent (fallback path); excludeId respected.
24. `Module` variant="shared": text/number/checkbox render inside a disabled fieldset; `setField` fires neither `onChange` nor `onCommit`; header action cluster absent.
25. `SharedSurface`: renders read-only chrome from a fixture; 404 → inactive-link state; no PromptBar/Sidebar in the tree.
26. `a11y.test.ts` extension: SharePanel dialog semantics (role, focus, Escape).

Gates: pytest 80% branch, mypy, ruff, vitest, tsc, next build stay green.

---

## 6. Deliberately cut (do not build)
Multiple concurrent links / per-recipient revoke; expiry timestamps; view counters; password links; token hashing (status must return the link for re-copy; accepted risk documented); live-data proxying or polling on the shared view; snapshot-pinned shares; SSR/OG cards; pan/zoom on the shared surface; the IntegrityError retry loop and concurrent-rotate thread test (Python sqlite3 begins the write transaction at the first DML, after busy_timeout serialization — the race is not reachable; the partial unique index remains as the backstop); any write-access tier. All additive later via `_migrate`'s ALTER TABLE pattern if ever needed.

## 7. Documented accepted risks
- Token-bearing URLs land in browser history, chat logs, and access logs — mitigated by visible share state, one-tap rotate/revoke, read-only single-page scope, and no-referrer; not eliminated. Access logs and DB backups (backup.py) are credential-bearing.
- `config.state` ships verbatim — that IS the shared content, and a shared page shares its future contents, not a snapshot (SharePanel copy says so).
- A same-page `source_module_id` string may reference an off-page module uuid — an existence hint, unusable without owner auth.
- Behind a reverse proxy, per-IP keying needs `uvicorn --proxy-headers` confirmed in deploy docs, else all viewers share one bucket.
- Future ModuleConfig fields are auto-exposed on shared pages — add "is this shareable?" to the schema-change checklist; test 8's recursive walk guards known keys.

## Key decisions (contested points, ruled)

- One active link per page (POST = create-or-rotate) — a single legible noun the owner can rotate/revoke; enforced by a partial unique index (DB guarantee, Take 1/3) not app discipline (Take 2's code-only stance loses: the adopt bug shows why the index matters).
- adopt_session_data MUST migrate share_links.owner (Take 2's find) — otherwise pre-claim links die silently and the orphaned active row makes post-claim share_create violate the unique index and 500.
- share_resolve LEFT JOINs users so a revoked owner's tokens 404 (Take 2) — the public path bypasses _owner_id's per-request revocation check, so R-905 must be re-enforced here.
- Cross-module metric bindings: scoped to the shared page by construction, not filtered — resolution is client-side over the delivered module list (Canvas.tsx:111-125), and the payload contains only that page's modules; off-page bindings fall back to saved state. Zero special-case code.
- data_source is stripped server-side from the public payload (Take 3 over Take 1) — DataSource.query realistically carries home location for weather, and the shared view never fetches live values anyway; typed strip via the pydantic field.
- Child pages are structurally absent (all three takes converge despite different labels): no page tree in the payload, no portal layer in the renderer, no endpoint resolves a child by token — sharing X never exposes children; share the child separately if wanted.
- variant="preview" does NOT suffice — it bubbles edits in-memory (Module.tsx:133), a dishonest editable-looking surface; new variant="shared" = setField early-return (belt, covers all primitives and button actions) + <fieldset disabled> wrapper (braces, a11y-honest) + header action cluster gated off.
- Public path is sessionless (never touches request.session → no Set-Cookie, no session-row pollution, works under TRUS_ALLOW_ANON=0) and rate-limited by its own _RateLimiter instance keyed per-IP with fresh-per-call TRUS_SHARE_RATE_MAX/WINDOW env knobs (default 60/60s — Take 3's 120 too loose for unauthenticated traffic, Take 2's 30 too tight for a dashboard with assets-free reloads).
- Public payload drops the page id (Take 3/2 over Take 1) — module ids suffice for keys and bindings; page {name, icon} only; dedicated SharedPage/SharedModule models, never Page/StoredModule which serialize session_id/rev/parent/portal/view fields.
- 404s are byte-identical for unknown/revoked/rotated/cascade-deleted/revoked-owner tokens, and foreign page ids on management routes 404 like nonexistent ones (the _require_own_parent stance) — enumeration resistance plus 256-bit token_urlsafe(32), stored plaintext (status must return the link for re-copy; accepted, documented).
- Shared surface renders the owner's actual spatial arrangement (static absolute positioning from config.layout, normalized to a bounding box) rather than Take 1's reflowed CSS grid — surface fidelity per the design ethos, without dragging in Canvas.tsx's drag/resize/saver machinery; assembly construction motion on mount, reduced-motion static.
- crossModuleValues/computeMetric extracted verbatim from Canvas.tsx into lib/crossModule.ts — the one shared helper this feature justifies; Canvas and SharedSurface both import it.
- async def handlers throughout (house pattern for fast DB-only reads, pages.py precedent) — Take 2's sync-def-threadpool reading of the event-loop constraint rejected; that constraint targets LLM/blocking work.
- Cut as gold-plating: Take 3's IntegrityError retry loop and concurrent-rotate thread test (python sqlite3 begins the write txn at first DML after busy_timeout serialization — race unreachable; the index is the backstop), multi-link support, expiry, view counts, token hashing, pan/zoom on the shared view, live polling.
- Grafted small wins: no-referrer metadata on /share/[token] (token is a credential in the URL), ConfirmDialog on rotate/revoke, SHARED pip in the page header for always-visible state (SHARE-2), deploy-docs note forbidding caching of /api/share/*.
