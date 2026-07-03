# Trus MVP — Stage 2a: Reliability Completions & Triaged Backlog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the reliability requirements (R-1101/R-1102), land the two security decisions from the Stage 1 final review (multipart CSRF, image_url SSRF), make document upload genuinely ground content on non-multimodal providers (R-211), and burn down the triaged Stage-2 backlog — so Stage 2b (entry/interview/voice/sketch) builds on a finished reliability story.

**Architecture:** All changes extend existing seams: the Origin gate joins `_owner_id` in `routes/deps.py`; SSRF guarding hardens the existing `_load_image`; snapshot restore becomes one transaction that preserves module ids; document grounding is a text-extraction preprocessor in front of the existing honest-refusal path; frontend work extends the moduleSaver/commit path and existing overlay patterns.

**Tech Stack:** unchanged (FastAPI/stdlib-SQLite/pytest · Next 16/React 19/vitest — read `frontend/AGENTS.md` before Next-specific APIs). One new runtime dep: `pypdf`.

## Global Constraints

- **Requirements contract:** `docs/MVP-SPEC.md`; cite R-IDs in commit bodies. Invariant I-1 (AI never emits UI code) untouched.
- **Stage map:** Stage 2a = this plan. Stage 2b = entry-as-interview + voice + sketch (R-100, R-200 input surfaces, R-301–305) — planned at this stage's exit. Stage 3 = differentiators (R-500 portals, R-700 live data, R-800 profile). Stage 4 = hosted-alpha polish. Do not build ahead.
- **Quality-gated (spec §0):** every task exits with `python -m pytest -q` (80% branch gate ON) 0 failed, `mypy backend/src` clean, `ruff check backend/src` clean; frontend tasks also `cd frontend && npm test && npx tsc --noEmit && npm run build` clean.
- **Run backend commands from the repo root**; venv at repo root (`source .venv/bin/activate`). The repo path contains SPACES — double-quote it.
- **Branch: `stage2a/reliability`** off `main` (main = 5821b06). No worktree (repo on iCloud). `git add` specific files — never `git add -A`. Commit format: `type(scope): summary` + R-ID body + `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- **Honesty seam invariants to preserve:** `llm.generate()`/`generate_from_file()` reset `last_call` to None at entry and set a `GenResult` on success; degraded output is never cached/persisted-as-success; `_llm_error_detail` (in `routes/deps.py`) is the only LLMError → HTTP detail path.
- **`.next/types/* 2.ts` tsc errors** = iCloud conflicted-copy artifacts → delete `.next/`, rebuild.
- Env flags introduced this stage: `TRUS_ALLOW_URL_IMPORT` (`1` default in dev; URL image import disabled in prod unless set).

---

### Task 1: Origin gate on state-changing multipart endpoints (CSRF — Stage-1 final-review security decision A)

**Files:**
- Modify: `backend/src/routes/deps.py` (add `_require_trusted_origin`), `backend/src/routes/modules.py` (generate_from_file), `backend/src/routes/studio.py` (import_layout, capture_layout), `backend/src/main.py` (export the parsed origins list for reuse — check how `_parse_cors_origins` is structured and import from there or re-parse in deps)
- Test: `backend/tests/test_origin_gate.py` (new)

**Interfaces:**
- Consumes: `_parse_cors_origins` behavior from Task 7 of Stage 1 (main.py) — reuse, don't duplicate parsing rules.
- Produces: `deps._require_trusted_origin(request: Request) -> None` (raises 403) applied to the three multipart handlers. JSON endpoints stay preflight-protected (no change).

Why: with `SameSite=None` cookies in the hosted posture, multipart POSTs are CORS-"simple" — a malicious page can fire credentialed FormData requests with no preflight, spending the victim's tokens and inserting modules. The gate: if an `Origin` header is present and not in the allowed set, 403; absent Origin (curl, same-origin form posts in some browsers) passes — this targets the browser cross-site vector specifically.

- [ ] **Step 1: Write the failing tests**

```python
"""Stage-1 final review security decision A: cross-site multipart CSRF gate."""
from fastapi.testclient import TestClient

from src.main import app


def _post_file(client, origin=None):
    headers = {"Origin": origin} if origin else {}
    return client.post(
        "/api/modules/generate_from_file",
        files={"file": ("note.txt", b"hello", "text/plain")},
        data={"prompt": "track this"},
        headers=headers,
    )


def test_foreign_origin_multipart_is_403(tmp_path, monkeypatch):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    with TestClient(app) as client:
        r = _post_file(client, origin="https://evil.example")
        assert r.status_code == 403


def test_allowed_origin_and_no_origin_pass_the_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    with TestClient(app) as client:
        # Allowed origin (default list): not 403 (may be 4xx/2xx further down — stub mode refuses honestly)
        r = _post_file(client, origin="http://localhost:3000")
        assert r.status_code != 403
        r2 = _post_file(client)  # no Origin header (curl / same-origin)
        assert r2.status_code != 403


def test_studio_import_and_capture_are_gated(tmp_path, monkeypatch):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    with TestClient(app) as client:
        for path in ("/api/studio/use-cases/calorie/import", "/api/studio/use-cases/calorie/capture"):
            r = client.post(path, files={"file": ("s.png", b"png", "image/png")},
                            headers={"Origin": "https://evil.example"})
            assert r.status_code == 403, path
```

Run: `python -m pytest backend/tests/test_origin_gate.py -v --no-cov` → FAIL (no gate; statuses are 4xx-from-content or 2xx, not 403).

- [ ] **Step 2: Implement `_require_trusted_origin` in `backend/src/routes/deps.py`**

```python
def _require_trusted_origin(request: Request) -> None:
    """CSRF gate for state-changing multipart endpoints (Stage-1 review decision A).

    Multipart POSTs are CORS-'simple': with SameSite=None cookies a malicious
    page can send credentialed FormData cross-site without a preflight. If the
    browser declares a cross-site Origin that isn't ours, refuse. Requests
    without an Origin header (curl, same-origin) pass — the browser vector is
    the one being closed.
    """
    origin = request.headers.get("origin")
    if not origin:
        return
    allowed = [o.strip() for o in os.environ.get(
        "TRUS_CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
    if origin not in allowed:
        raise HTTPException(status_code=403, detail="Cross-site upload refused")
```

(If `main._parse_cors_origins` is importable without a circular import, use it instead of re-parsing; otherwise keep this local parse IDENTICAL to main's rules and add a comment pointing at main.py.)

- [ ] **Step 3: Apply to the three handlers**

In `routes/modules.py` `generate_from_file` and `routes/studio.py` `import_layout` + `capture_layout`: first line of the handler body (before reading the file): `_require_trusted_origin(request)` (import from `.deps`; add `request: Request` param where missing).

- [ ] **Step 4: Run tests, full suite, commit**

`python -m pytest backend/tests/test_origin_gate.py -v --no-cov` → 3 PASS; `python -m pytest -q` → 0 failed.

```bash
git checkout -b stage2a/reliability
git add backend/src/routes/deps.py backend/src/routes/modules.py backend/src/routes/studio.py backend/tests/test_origin_gate.py
git commit -m "feat(security): Origin gate on state-changing multipart endpoints

Stage-1 final-review decision A: closes the SameSite=None multipart CSRF
vector on generate_from_file + studio import/capture. R-901 posture.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: SSRF guard on studio `image_url` (security decision B)

**Files:**
- Modify: `backend/src/routes/studio.py` (`_load_image` URL branch)
- Test: `backend/tests/test_ssrf_guard.py` (new)

**Interfaces:**
- Consumes: nothing new.
- Produces: URL imports resolve the host and refuse private/loopback/link-local/metadata ranges; in `TRUS_ENV=prod` URL import is off entirely unless `TRUS_ALLOW_URL_IMPORT=1`.

- [ ] **Step 1: Failing tests**

```python
"""Stage-1 final review security decision B: image_url SSRF guard."""
import pytest
from fastapi.testclient import TestClient

from src.main import app


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8000/api/health",
    "http://localhost:11434/",
    "http://169.254.169.254/latest/meta-data/",
    "http://10.0.0.5/internal",
    "http://192.168.1.1/router",
])
def test_private_and_metadata_urls_are_refused(tmp_path, monkeypatch, url):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    with TestClient(app) as client:
        r = client.post("/api/studio/use-cases/calorie/import", data={"image_url": url})
        assert r.status_code == 422
        assert "url" in str(r.json().get("detail", "")).lower()


def test_url_import_disabled_in_prod_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TRUS_ENV", "prod")
    monkeypatch.setenv("SESSION_SECRET", "x" * 32)
    monkeypatch.delenv("TRUS_ALLOW_URL_IMPORT", raising=False)
    # NOTE: main.py's prod boot-guard runs at import; the app is already imported
    # in dev shape. Test the guard FUNCTION directly instead of re-importing app:
    from src.routes import studio as studio_routes
    with pytest.raises(Exception):
        studio_routes._check_url_allowed("https://example.com/img.png")
```

Run → FAIL (no `_check_url_allowed`; private URLs currently fetched).

- [ ] **Step 2: Implement in `backend/src/routes/studio.py`**

Add above `_load_image` (adapt names to the file's style):

```python
import ipaddress
import socket
from urllib.parse import urlparse


def _check_url_allowed(url: str) -> None:
    """SSRF guard (Stage-1 review decision B): refuse non-http(s) schemes,
    private/loopback/link-local/metadata targets, and all URL imports in prod
    unless TRUS_ALLOW_URL_IMPORT=1. Raises HTTPException(422)."""
    if os.environ.get("TRUS_ENV", "dev") == "prod" and os.environ.get(
            "TRUS_ALLOW_URL_IMPORT", "0") != "1":
        raise HTTPException(status_code=422, detail="URL import is disabled; upload the image file instead")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HTTPException(status_code=422, detail="Only http(s) image URLs are supported")
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as e:
        raise HTTPException(status_code=422, detail="Image URL host could not be resolved") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise HTTPException(status_code=422, detail="Image URL points at a private address; refused")
```

Call `_check_url_allowed(image_url)` as the FIRST thing in `_load_image`'s URL branch (before `urlopen`). Note: redirects can still bounce to private IPs after the check (TOCTOU) — add a comment acknowledging it and disable redirects on the urlopen if the current code allows (build an opener with no HTTPRedirectHandler, or check `resp.url`'s host again post-fetch). Implement the redirect re-check — it's ~4 lines and closes the classic bypass.

- [ ] **Step 3: Tests green, suite green, commit** (message: `feat(security): SSRF guard on studio image_url — private ranges refused, prod-off by default`, body cites decision B.)

---

### Task 3: R-1102 — destructive actions confirmed or undoable (frontend)

**Files:**
- Modify: `frontend/src/app/page.tsx` (page-delete + module-delete flows), `frontend/src/components/Sidebar.tsx` (delete button flow), `frontend/src/components/Module.tsx` (✕ becomes archive), `frontend/src/components/ArchivedPanel.tsx` (hard delete gets confirm)
- Create: `frontend/src/components/ConfirmDialog.tsx`
- Test: manual traces + `npx tsc --noEmit`/build (no DOM test infra; document traces in report)

**Interfaces:**
- Consumes: existing `api.deletePage`, `api.archiveModule`, `api.deleteModule`, saver `forget()`.
- Produces: `<ConfirmDialog open title body confirmLabel onConfirm onCancel />` reused by both flows.

Behavior contract (spec R-1102): deleting a PAGE (cascades all its modules) requires a typed-out confirm dialog stating the module count ("Delete 'Work' and its 6 modules? This cannot be undone."). The module card ✕ becomes **Archive** (undoable via the Archived panel — tooltip says so); hard delete lives only in the Archived panel behind a confirm. Every removal calls `saver.forget(id)` (already true for delete — verify for archive).

- [ ] **Step 1: Read the current flows** — `grep -n "deletePage\|deleteModule\|archiveModule\|forget" frontend/src/app/page.tsx frontend/src/components/Sidebar.tsx frontend/src/components/Module.tsx frontend/src/components/ArchivedPanel.tsx`. Map who calls what; note in the report.
- [ ] **Step 2: Build `ConfirmDialog.tsx`** — overlay + panel styled like the existing modal patterns (read `ShortcutsModal.tsx` for the overlay/blur/rise classes; reuse them). Danger-styled confirm button (`--danger` token), Escape/backdrop = cancel, focus the cancel button on open (`role="dialog" aria-modal`).
- [ ] **Step 3: Wire page delete** — Sidebar delete → `onRequestDeletePage(page)` → page.tsx sets dialog state (fetch module count from current state: `modules.filter(m => m.page_id === page.id).length`) → confirm calls the existing delete path (which must also `forget()` every module on that page — add it).
- [ ] **Step 4: Module ✕ → archive** — Module.tsx delete affordance calls `onArchive` (existing archive wiring) instead of delete; tooltip "Archive (restore from Archived)". ArchivedPanel's permanent-delete gets the ConfirmDialog ("Permanently delete 'X'? This cannot be undone.").
- [ ] **Step 5: Verify + commit** — `npx tsc --noEmit && npm test && npm run build` clean; manual trace: delete page shows count + cancels safely; archived module restores intact; hard delete confirmed. Commit `feat(frontend): destructive actions confirmed or undoable (R-1102)`.

---

### Task 4: R-1102 — atomic, id-preserving snapshot restore (backend)

**Files:**
- Modify: `backend/src/db.py` (`create_snapshot` data format + `restore_snapshot` rewrite), `backend/src/routes/modules.py` (restore route: distinguish 404/409), `backend/src/schema.py` if the snapshot response model needs it
- Test: extend `backend/tests/test_snapshots.py`

**Interfaces:**
- Consumes: `_conn`, `_stored_from_row`, `_record_version`, rev semantics from Stage 1 Task 10.
- Produces: snapshot `data_json` v2 format `[{"id": module_id, "config": {...}}]` (v1 = bare config list, still restorable); `restore_snapshot` returns `"ok" | "missing" | "corrupt"` (route maps to 204/404/409).

Contract: restore happens in ONE `_conn()` transaction — a crash mid-restore leaves the page exactly as it was; module ids from the snapshot are PRESERVED (cross-module `source_module_id` bindings survive), with `rev` bumped (`rev = rev + 1` where the row exists, else insert with rev 0) so open tabs conflict-detect after a restore. Modules on the page absent from the snapshot are deleted in the same transaction; version history rows are recorded for changed modules.

- [ ] **Step 1: Failing tests** (add to test_snapshots.py; follow its fixture style):
  - `test_restore_preserves_module_ids_and_bindings`: page with modules A + B where B's config contains `source_module_id: A.id`; snapshot; mutate A's title; restore; assert A keeps its ORIGINAL id and title from the snapshot, binding still resolves, `get_module(A).rev` increased.
  - `test_restore_is_single_transaction`: monkeypatch `db._record_version` (or another late step inside the loop) to raise on the SECOND module; restore → returns `"corrupt"`-class failure AND the page still contains ALL pre-restore modules unchanged (nothing deleted).
  - `test_v1_snapshot_still_restores`: hand-insert a snapshot row with the old bare-config-list `data_json`; restore succeeds (new ids acceptable for v1) — tolerance, not equivalence.
  - `test_restore_route_distinguishes_missing_and_corrupt`: unknown id → 404; hand-corrupted `data_json` → 409 with a plain-language detail.
- [ ] **Step 2: Implement.** `create_snapshot` stores v2 (id + config). `restore_snapshot` rewrite sketch:

```python
def restore_snapshot(session_id: str, snapshot_id: str) -> str:
    """Returns 'ok' | 'missing' | 'corrupt'. One transaction; ids preserved (v2)."""
    with _conn() as c:
        row = c.execute(
            "SELECT page_id, data_json FROM snapshots WHERE id = ? AND session_id = ?",
            (snapshot_id, session_id),
        ).fetchone()
        if row is None:
            return "missing"
        try:
            raw = json.loads(row["data_json"])
            # v2: [{"id":..., "config":{...}}]; v1: [ {...config...} ]
            entries = [(e.get("id"), ModuleConfig.model_validate(e.get("config", e)))
                       for e in raw] if isinstance(raw, list) else None
            if entries is None:
                return "corrupt"
        except Exception:
            _log.warning("Unreadable snapshot %s; restore aborted (R-1105/R-1102)", snapshot_id)
            return "corrupt"
        now = _now()
        page_id = row["page_id"]
        keep_ids = {e[0] for e in entries if e[0]}
        # everything below shares THIS connection: one commit, or none on raise
        for m_row in c.execute(
            "SELECT id FROM modules WHERE session_id = ? AND page_id = ?",
            (session_id, page_id),
        ).fetchall():
            if m_row["id"] not in keep_ids:
                c.execute("DELETE FROM modules WHERE id = ? AND session_id = ?",
                          (m_row["id"], session_id))
        for mod_id, config in entries:
            cfg_json = config.model_dump_json()
            if mod_id and c.execute(
                "SELECT 1 FROM modules WHERE id = ? AND session_id = ?",
                (mod_id, session_id),
            ).fetchone():
                c.execute(
                    "UPDATE modules SET config_json = ?, updated_at = ?, rev = rev + 1,"
                    " page_id = ?, archived = 0 WHERE id = ? AND session_id = ?",
                    (cfg_json, now, page_id, mod_id, session_id))
            else:
                c.execute(
                    "INSERT INTO modules (id, session_id, page_id, config_json,"
                    " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (mod_id or str(uuid.uuid4()), session_id, page_id, cfg_json, now, now))
            _record_version(c, mod_id, session_id, cfg_json, now)
```

(Adapt to actual column lists/defaults — e.g. `rev` on INSERT relies on the column default; check `_record_version`'s signature for a None id and pass the resolved id. Do NOT call `list_modules`/`delete_module`/`insert_module` helpers — they open their own connections and break atomicity; note this in a comment.)
- [ ] **Step 3: Route mapping** — restore route: `"missing"` → 404, `"corrupt"` → 409 (`"This snapshot is unreadable and was not restored."`), `"ok"` → 204. Update `SnapshotsPanel.tsx` error surface if it special-cases statuses (read it; likely generic).
- [ ] **Step 4: Suite + frontend checks green; commit** `fix(backend): atomic id-preserving snapshot restore (R-1102) — bindings survive, crash-safe`.

---

### Task 5: R-211 — documents ground on non-multimodal providers (text extraction)

**Files:**
- Modify: `backend/requirements.txt` (+`pypdf>=4.0.0` under runtime), `backend/src/services/orchestrator.py` (`generate_modules_from_file`), new helper `backend/src/services/extract.py`
- Test: `backend/tests/test_extract.py` (new) + extend `backend/tests/test_generate_from_file.py`

**Interfaces:**
- Produces: `extract.text_from_file(data: bytes, mime: str, filename: str | None = None) -> str | None` — plain text for `text/*`/CSV/MD (utf-8, errors="replace"), PDF via pypdf (first ~30 pages, capped ~20_000 chars), `None` for unsupported/empty.
- Orchestrator behavior: BEFORE the multimodal call, if the provider path would return the `"{}"` sentinel for this mime (non-image on openai-compat; any file in stub — read `llm.generate_from_file` to enumerate exactly), try extraction: on success, route through the normal `generate_modules(...)`-style prompt with `"\n\nDOCUMENT CONTENT (extracted from {filename}):\n{text}"` appended, so grounding works on EVERY provider; extraction failure falls through to the existing honest RefusalError. Gemini native path unchanged (only used when extraction is skipped/unsupported — images).

- [ ] **Step 1: Failing tests.** `test_extract.py`: txt/csv/md decode; a minimal in-repo PDF fixture (create `backend/tests/fixtures/tiny.pdf` in the test setup via pypdf's writer with one page of text — if pypdf's writer can't embed text simply, check `reportlab` is NOT available and instead craft the canonical minimal text PDF bytes inline as a bytes literal in the fixture; verify `text_from_file` returns the string "Trus fixture"); oversized text capped; unsupported mime → None. `test_generate_from_file.py` additions: stub/openai provider + a .txt upload → monkeypatch `llm.generate` and assert the DOCUMENT CONTENT text reached the prompt (grounded path), no RefusalError; a .bin upload still refuses honestly.
- [ ] **Step 2: Implement `extract.py` + orchestrator wiring.** Extraction runs server-side, synchronously (small files; the 15MB route cap bounds it). `last_call`/telemetry flow through `llm.generate` normally on the grounded path (provider/model recorded — closes half of the file-telemetry gap).
- [ ] **Step 3: Suite green (note: the grounded path must NOT enter the semantic cache with the document text as the cache key's prompt — check `generate_modules`' `owner`/store path; simplest: call `_generate_validated` directly with the doc-augmented prompt, skipping cache lookup/store entirely; document why in a comment: document content is per-upload, caching it as a reusable template leaks doc content into suggestions).**
- [ ] **Step 4: Commit** `feat(backend): document grounding via server-side text extraction (R-211) — every provider, honest fallback`.

---

### Task 6: Telemetry + observability completions (R-1201/R-1202 gaps)

**Files:**
- Modify: `backend/src/llm.py` (`generate_from_file` sets a GenResult), `backend/src/main.py` (`/api/llm/status` prod-gating; `/api/ops/summary` per-user last-seen), `backend/src/db.py` (`last_seen_by_user()`)
- Test: extend `backend/tests/test_telemetry.py`, `test_providers.py`

**Interfaces:**
- Produces: `db.last_seen_by_user(days: int = 30) -> list[dict]` — `{"name", "user_id", "last_seen", "generations_7d"}` via `gen_events JOIN users ON gen_events.owner = users.id`; ops summary gains `"users": [...]`. `llm.generate_from_file` sets `last_call` to a real GenResult on success (provider, model, tokens where the payload offers them — gemini `usage_metadata`, openai image-path `usage`).

- [ ] **Step 1: Failing tests:** (a) after a (mocked) successful gemini file generation, `llm.last_call.get()` carries provider="gemini" + model; (b) `/api/ops/summary?token=…` includes a `users` array and, after a claimed user generates, shows their name with a fresh `last_seen`; (c) with `TRUS_ENV=prod`, `/api/llm/status` omits `base_url` and `cache` (test the handler function directly if app-reimport is awkward — same pattern as Task 2's prod test).
- [ ] **Step 2: Implement.** Keep `/api/llm/status` fully available in dev (it's the local-setup verification tool README documents).
- [ ] **Step 3: Suite green; commit** `feat(backend): file-path provenance, per-user last-seen in ops, prod-gated llm/status (R-1201/R-1202)`.

---

### Task 7: Saver & interaction backlog (frontend batch)

**Files:**
- Modify: `frontend/src/lib/moduleSaver.ts` (+404 handling), `frontend/src/lib/moduleSaver.test.ts`, `frontend/src/app/page.tsx` (onMissing wiring, keepalive flush, functional commit, degraded notice styling), `frontend/src/components/PromptBar.tsx` (degraded notice channel), `frontend/src/components/Inspector.tsx` (hoist persist out of the setDraft updater), `frontend/src/components/Module.tsx` (setField via functional parent update), `frontend/src/app/claim/page.tsx` (rebind cancel link)
- Test: vitest for every moduleSaver change; tsc/build + manual traces for the rest

Sub-items (each its own commit-able step, TDD where the saver changes):
- [ ] **7a — 404 = forget, visibly:** saver: `ApiError` 409 handled; add 404: drop pending/timers/retry/knownRevs, call new `deps.onMissing?.(id)`; NO retry loop. Vitest: a 404 rejection → onMissing once, no second patch call, status returns "idle". page.tsx `onMissing`: remove the module from state + toast "That module no longer exists — it was removed elsewhere." (reuse the conflict toast surface with different copy).
- [ ] **7b — degraded notice ≠ error styling:** PromptBar's degraded notice moves off the red error channel to a neutral/warning presentation (reuse the save-pill's warning token treatment; copy unchanged). One-line design check vs DESIGN-ETHOS.md in the report (R-1305).
- [ ] **7c — beforeunload real flush:** page.tsx unload handler: keep the warn (`preventDefault` + `returnValue = ""`), and fire best-effort persistence with `fetch(..., {keepalive: true})` — add a `flushAllKeepalive()` on the saver (Deps gains optional `patchKeepalive`; page.tsx wires it to a fetch clone of `api.patchModule` with `keepalive: true`). Vitest: flushAllKeepalive sends pending configs through patchKeepalive.
- [ ] **7d — Inspector updater hygiene:** move the `persist(...)` call out of the `setDraft` functional updater (compute `next` first, `setDraft(next)`, then persist) — no behavior change; confirms no StrictMode double-commit noise (coalescing absorbs it regardless).
- [ ] **7e — same-tick commit hardening:** `commitModule` in page.tsx accepts `(id, configOrUpdater)` where an updater form `(prev: ModuleConfig) => ModuleConfig` is applied INSIDE the `setModules` functional update, and the saver commit uses the computed result; migrate `Module.setField` to the updater form (kills the latent props-snapshot stale-closure class from the Stage-1 review).
- [ ] **7f — rebind cancel affordance:** claim page's switch screen gains a quiet secondary "Stay as {currentName}" link → `router.replace("/")`.
- [ ] **7g — verify + commit:** `npm test && npx tsc --noEmit && npm run build` clean; single commit `fix(frontend): saver 404 handling, keepalive flush, functional commits, notice styling (R-602/R-1101 backlog)`.

---

### Task 8: Small-backlog batch (backend)

**Files:**
- Modify: `backend/src/routes/studio.py` (`_row_to_layout` tolerant), `backend/requirements.txt` + `backend/requirements-dev.txt` (new) + `backend/Dockerfile` + `.github/workflows/code-quality.yml` (install both), `backend/tests/test_event_loop.py` (Event rendezvous)
- Test: extend `backend/tests/test_studio.py`

- [ ] **8a — studio layout quarantine (R-1105 parity):** `_row_to_layout` returns None on parse failure (log warning + row id); `GET /api/studio/layouts` filters. TDD: corrupt row test.
- [ ] **8b — requirements split:** `backend/requirements.txt` = runtime ONLY (fastapi, uvicorn[standard], google-genai, python-dotenv, pydantic, Pillow, itsdangerous, python-multipart, pypdf — the last three moved/added with a comment noting itsdangerous=SessionMiddleware, python-multipart=uploads); `backend/requirements-dev.txt` = `-r requirements.txt` + pytest/pytest-cov/pytest-asyncio/httpx. Update CI + docs (README testing section) to install dev file; Dockerfile keeps runtime file (image slims + the mislabeling trap dies). Verify: `docker build` if available; `pip install -r backend/requirements-dev.txt` resolves in the venv.
- [ ] **8c — test rendezvous:** replace the `time.sleep(0.2)` head-start in `test_event_loop.py` with a `threading.Event` set inside the mocked slow generation just before its sleep; assert unchanged.
- [ ] **8d — suite green; commit** `chore(backend): layout quarantine, runtime/dev requirements split, deterministic event-loop test`.

---

### Task 9: STATUS.md refresh + stage exit

**Files:**
- Modify: `STATUS.md` (rewrite to current truth), ledger
- Test: full gates

- [ ] **Step 1: Rewrite STATUS.md** — short and true: architecture unchanged; Stage 1 + 2a shipped (blockers list, one line each); current gates (test count, coverage); pointers to `docs/MVP-SPEC.md`, `docs/MVP-GAP-AUDIT.md`, `docs/superpowers/plans/`; "next: Stage 2b (entry/interview/voice/sketch)". Delete the stale 2026-06-14 feature matrix (git history keeps it).
- [ ] **Step 2: Full gate run** — `python -m pytest -q` (gate on) / `mypy backend/src` / `ruff check` + `format --check` / `cd frontend && npm test && npx tsc --noEmit && npm run build`; record outputs.
- [ ] **Step 3: Browser smoke** (servers per README): generate→confirm, edit-then-drag, page-delete confirm dialog, archive→restore, snapshot→restore (bindings intact), file upload (.txt grounds; .bin refuses honestly). Document.
- [ ] **Step 4: Commit** `chore: stage-2a exit — STATUS refresh, gate evidence` + hand off to the final whole-branch review (superpowers:requesting-code-review), then write the Stage 2b plan.

---

## Stage-Exit Checklist (spec ACs)

- [ ] **R-1102 AC:** page delete confirmed with module count; module removal undoable (archive); permanent delete confirmed; snapshot restore atomic + id-preserving (bindings survive — test-pinned).
- [ ] **R-211 AC (grounding half):** a .txt/.csv/.md/.pdf upload grounds proposals on EVERY provider path (extraction), honest refusal only for genuinely unreadable files.
- [ ] **Security decisions A + B implemented and logged** (vault decisions-log entry at exit — controller's job).
- [ ] **R-1201/R-1202 completions:** ops shows per-user last-seen; file generations carry provenance; llm/status safe in prod.
- [ ] **R-602/R-1101 backlog:** 404-forget visible; keepalive flush; degraded notice styled honestly; no saver regressions (vitest suite grows).
- [ ] **R-1401:** all gates green at exit; requirements split leaves CI + Docker + venv all working.
- [ ] Final whole-branch review (most capable model) → fixes → merge decision to the user.
- [ ] Write the Stage 2b plan (entry-as-interview + voice + sketch) against the post-2a codebase.
