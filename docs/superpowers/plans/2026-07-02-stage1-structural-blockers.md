# Trus MVP — Stage 1: Structural Blockers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retire the seven structural blockers from `docs/MVP-GAP-AUDIT.md` so every later feature stage builds on a hardened, honest, observable, identity-capable, deployable core — stage exit maps to `docs/MVP-SPEC.md` acceptance criteria (R-1401, R-1103, R-403/R-1104, R-1105, R-1201–1203, R-901–905, R-906-buildout, R-601/R-602).

**Architecture:** Backend stays FastAPI + stdlib SQLite (WAL) with a provenance-carrying LLM seam (`GenResult`), per-owner data scoping via invite-claimed users, and a `gen_events` telemetry table. Frontend gains a single-writer module save store (kills the three racing debounced writers), optimistic in-view updates, and rev-based conflict detection. Deployability = Dockerfile + env-driven CORS/cookies/secret; actual deploy is an operator checkpoint.

**Tech Stack:** Python 3.12/FastAPI/pytest, Next.js 16/React 19/TypeScript 5 (see `frontend/AGENTS.md` — check `node_modules/next/dist/docs/` before using Next APIs), vitest (new, for pure-TS lib tests).

## Global Constraints

- **Requirements contract:** `docs/MVP-SPEC.md`. Cite R-IDs in every commit message body. The invariant I-1 (AI never emits UI code) must never be weakened.
- **Stage map:** Stage 1 = this plan (structural blockers). Stage 2 = reliability pass + must-have inputs (R-1101/1102, R-201–231, R-301–304 interview). Stage 3 = differentiators (R-500 portals, R-700 live data, R-800 profile). Stage 4 = hosted-alpha polish (R-1301–1306, deploy, backups). Stages 2–4 get their own plan docs at each boundary — do not build ahead.
- **Quality-gated (spec §0):** the stage exits only when the Stage-Exit Checklist at the bottom passes. All tests green at every commit.
- **Run backend commands from the repo root** (single authoritative pytest config after Task 1): `python -m pytest` (coverage gate 80% branch included via pyproject). The venv is at repo root: `source .venv/bin/activate`.
- **The repo path contains spaces** — always double-quote paths in shell commands.
- **Work on branch `stage1/structural-blockers`** (in place; do NOT create a worktree — the repo lives on iCloud Drive and duplicate trees sync badly). A cloud-session PR may land on `main` mid-stage; do not merge it into this branch — reconciliation happens at stage exit.
- Commit format: `type(scope): summary` + body citing R-IDs, ending with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- **Env flags introduced in this stage** (all read at import/startup): `TRUS_ENV` (`dev`|`prod`, default `dev`), `TRUS_ALLOW_ANON` (`1` default in dev; `0` in prod), `TRUS_CORS_ORIGINS` (comma list, default `http://localhost:3000`), `TRUS_COOKIE_SECURE` (`1` → `https_only=True, same_site="none"`), `TRUS_PUBLIC_URL` (invite-link base, default `http://localhost:3000`).

---

### Task 1: Green gates baseline — remove dead scaffolding, fix mypy, reconcile the coverage gate (R-1401)

**Files:**
- Delete: `backend/src/archetypes.py`, `backend/tests/test_archetypes.py`, `frontend/src/components/GenerationBeam.tsx`
- Modify: `backend/src/services/capture/capture.py:33-35`, `backend/pytest.ini` (delete), `CLAUDE.md` (commands section)
- Test: existing suite

**Interfaces:**
- Consumes: nothing (first task).
- Produces: a green `python -m pytest` from repo root minus the coverage gate (coverage rises through the stage; the gate is checked at stage exit), green `mypy backend/src`, no production-dead modules.

- [ ] **Step 1: Confirm the current red state (evidence before deletion)**

Run from repo root: `source .venv/bin/activate && python -m pytest -q 2>&1 | tail -3`
Expected: `1 failed, 151 passed, 2 skipped` — the failure is `backend/tests/test_archetypes.py` (drifted test committed red at HEAD; audit R-1401 evidence).

- [ ] **Step 2: Verify archetypes.py is production-dead, then delete it and its test**

Run: `grep -rn "archetypes" backend/src --include="*.py" | grep -v "archetypes.py:"`
Expected: no output (nothing in src imports it).
Then: `git rm backend/src/archetypes.py backend/tests/test_archetypes.py`
(Spec R-1401: dead scaffolding "wired into a requirement or removed" — Stage 2's interview may rebuild intent-decoding, but from the spec, not this drifted module. Git history preserves it.)

- [ ] **Step 3: Verify GenerationBeam.tsx is unreferenced, then delete**

Run: `grep -rn "GenerationBeam" frontend/src --include="*.tsx" --include="*.ts" | grep -v "GenerationBeam.tsx"`
Expected: no output. Then: `git rm frontend/src/components/GenerationBeam.tsx`
If grep DOES return references, stop and remove the references instead (they are orphaned imports per the audit).

- [ ] **Step 4: Fix the two mypy errors in capture preprocess**

Run first: `mypy backend/src 2>&1 | grep capture.py`
Expected: 2 errors at `capture.py:33` and `:35` (untyped `img.resize` tuple / `img.size` unpacking — see actual message).
Fix in `backend/src/services/capture/capture.py` by annotating the tuple explicitly (adjust to the actual reported error):

```python
        new_size: tuple[int, int] = (max(1, int(w * scale)), max(1, int(h * scale)))
        if scale < 1.0:
            img = img.resize(new_size)
```

Run: `mypy backend/src` → Expected: `Success: no issues found`.

- [ ] **Step 5: Reconcile the two pytest configs — repo-root pyproject is authoritative (spec R-1401)**

`git rm backend/pytest.ini` (it shadows the root config with a gate-free 78%-line view; the audit flagged the disagreement).
Edit `CLAUDE.md` (repo root): in **Common Commands** and **AutoResearch Configuration**, replace every `cd backend && pytest`/`cd backend && python -m pytest --cov=src ...` invocation with the repo-root equivalent:

```bash
# Tests (backend) — run from repo root; coverage gate (80% branch) included
python -m pytest -q

# Coverage number only (used by AutoResearch Verify)
python -m pytest -q 2>/dev/null | grep TOTAL | awk '{print $4}' | tr -d '%'
```

- [ ] **Step 6: Run the suite; record the coverage number**

Run: `python -m pytest -q 2>&1 | tail -3`
Expected: **0 failed**, 2 skipped (the env-gated live tests). Coverage will report FAIL under 80 — expected; the gate is a stage-exit criterion and rises as this stage adds tests. Note the % in the commit body.

- [ ] **Step 7: Commit**

```bash
git checkout -b stage1/structural-blockers
git add -A && git commit -m "chore: green-gates baseline — remove dead scaffolding, fix mypy, single pytest config

R-1401: archetypes.py (production-dead, red test) and GenerationBeam.tsx removed;
mypy clean; repo-root pyproject is the one authoritative pytest/coverage config.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: SQLite hardening + unblock the event loop (R-1103)

**Files:**
- Modify: `backend/src/db.py:161-171` (`_conn`), `backend/src/routes/modules.py` (handlers at lines 48, 77, 119, 256, 333), `backend/src/routes/studio.py` (the two `async def` import/capture handlers)
- Test: `backend/tests/test_event_loop.py` (new)

**Interfaces:**
- Consumes: Task 1 (green baseline).
- Produces: all LLM-calling handlers are plain `def` (Starlette threadpool); `db._conn()` yields WAL-mode connections with `busy_timeout=5000`. Later tasks may rely on concurrent request handling.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_event_loop.py`:

```python
"""R-1103: one user's generation must never freeze the API for others."""
import threading
import time

from fastapi.testclient import TestClient

from src import db
from src.main import app


def test_health_responds_while_generation_in_flight(monkeypatch, tmp_path):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))

    from src.services import orchestrator

    def slow_generate(prompt, existing_modules=None):
        time.sleep(1.5)
        from src.stub_templates import pick_system
        from src.schema import ModuleConfig
        return [ModuleConfig.model_validate(c) for c in pick_system(prompt)]

    monkeypatch.setattr(orchestrator, "generate_modules", slow_generate)

    with TestClient(app) as client:
        started = threading.Event()

        def fire_generation():
            started.set()
            client.post("/api/modules/preview", json={"prompt": "track my workouts"})

        t = threading.Thread(target=fire_generation)
        t.start()
        started.wait()
        time.sleep(0.2)  # let the generation enter the handler
        t0 = time.monotonic()
        r = client.get("/api/health")
        elapsed = time.monotonic() - t0
        t.join()
        assert r.status_code == 200
        assert elapsed < 1.0, f"health blocked {elapsed:.2f}s behind a generation (R-1103 AC)"


def test_sqlite_runs_wal_with_busy_timeout(tmp_path, monkeypatch):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    with db._conn() as c:
        assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert c.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
```

- [ ] **Step 2: Run to verify both fail**

Run: `python -m pytest backend/tests/test_event_loop.py -v --no-cov`
Expected: `test_health_responds_while_generation_in_flight` FAILS (health blocked ~1.3s+ — the `async def` handler runs `slow_generate` on the event loop); `test_sqlite_runs_wal...` FAILS (`delete` != `wal`).

- [ ] **Step 3: Implement — WAL in `_conn`, sync handlers**

`backend/src/db.py` — replace `_conn`:

```python
@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    _ensure_schema(conn)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
```

`backend/src/routes/modules.py` — change the five LLM-calling handlers from `async def` to `def` (FastAPI runs sync handlers on the threadpool): `generate_module` (line 48), `preview_modules` (77), `generate_from_file` (119), `refine_module` (256), `workspace_insights` (333). In `generate_from_file`, replace `data = await file.read()` with `data = file.file.read()` (keep any size-limit check around it intact).
`backend/src/routes/studio.py` — same conversion for the two `async def` upload handlers (import at ~line 138, capture at ~165): drop `async`, replace `await file.read()` with `file.file.read()`.
Leave non-LLM `async def` CRUD handlers as they are (they only touch fast SQLite; converting them is optional and out of scope).

- [ ] **Step 4: Run the new tests, then the whole suite**

Run: `python -m pytest backend/tests/test_event_loop.py -v --no-cov` → Expected: 2 PASS.
Run: `python -m pytest -q` → Expected: 0 failed (WAL leaves existing db tests untouched; if any test asserted `journal_mode=delete`, fix that test — WAL is the required mode per audit/perf finding).

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "fix(backend): run LLM handlers on the threadpool; SQLite WAL + busy_timeout

R-1103 AC: health stays <1s with a generation in flight. Retires the audit's
event-loop blocking defect and pre-hardens SQLite for concurrent writers.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Honest generation — provenance-carrying LLM seam, no cache poisoning, no fake refines, no question-crashes (R-403, R-1104, R-304)

**Files:**
- Modify: `backend/src/llm.py` (`generate`, `generate_from_file`, `_openai_chat` usage capture), `backend/src/services/orchestrator.py` (`generate_modules:351-377`, `generate_modules_from_file:380-409`, `refine_module:412-419`, `_generate_validated`), `backend/src/services/studio.py` + `backend/src/services/capture/transform.py` (callers of `llm.generate` → `.text`), `backend/src/routes/modules.py` (refine 265-275, insights 342-350), `backend/src/schema.py` (`GenerateResponse`), `frontend/src/lib/api.ts:46-51`, `frontend/src/components/PromptBar.tsx` (degraded surfacing)
- Test: `backend/tests/test_honesty.py` (new), updates in `backend/tests/test_orchestrator.py` / `test_providers.py` where they monkeypatch `llm.generate`

**Interfaces:**
- Consumes: Task 2 (sync handlers — contextvar provenance survives the request thread).
- Produces: `llm.GenResult` dataclass (`text: str`, `provider: str`, `model: str`, `degraded: bool`, `tokens_in: int | None`, `tokens_out: int | None`); `llm.generate(...) -> GenResult`; contextvar `llm.last_call: ContextVar[GenResult | None]`; `GenerateResponse.degraded: bool`. Task 5's telemetry reads `llm.last_call`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_honesty.py`:

```python
"""R-403/R-1104: degradation is visible, never cached, never a fake success."""
import pytest

from src import llm
from src.schema import LLMError


def test_cascade_fallback_is_flagged_degraded(monkeypatch):
    monkeypatch.setenv("TRUS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("TRUS_LLM_BASE_URL", "http://localhost:1")  # unreachable
    monkeypatch.setenv("GEMINI_API_KEY", "")  # no gemini → stub fallback
    monkeypatch.setattr(llm, "_openai_chat", lambda *a, **k: (_ for _ in ()).throw(LLMError("down")))
    result = llm.generate("track my calories", expect_array=True)
    assert result.degraded is True
    assert result.provider == "stub"
    assert result.text  # still returns usable fallback content


def test_degraded_results_never_enter_the_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TRUS_CACHE", "on")
    from src import db, semantic_cache
    from src.services import orchestrator

    monkeypatch.setattr(
        llm, "generate",
        lambda *a, **k: llm.GenResult(text='[{"refusal": "x"}]', provider="stub",
                                      model="stub", degraded=True),
    )
    monkeypatch.setattr(llm, "is_stub_mode", lambda: False)
    with pytest.raises(Exception):
        orchestrator.generate_modules("plan my week")  # refusal parse → raises
    assert db.cache_stats()["entries"] == 0  # nothing degraded was stored


def test_stub_mode_refine_is_honest_not_silent(monkeypatch):
    from src.services import orchestrator
    from src.stub_templates import pick_template
    from src.schema import ModuleConfig

    monkeypatch.setattr(llm, "is_stub_mode", lambda: True)
    config = ModuleConfig.model_validate(pick_template("track water"))
    with pytest.raises(LLMError):
        orchestrator.refine_module(config, "add a notes field")


def test_refine_route_returns_422_not_500_on_clarifying_question(client, monkeypatch):
    """R-304 AC: build/ask/refuse each surfaced distinctly — no crash paths."""
    from src.schema import ClarifyingQuestion
    from src.services import orchestrator

    created = client.post("/api/modules", json={"configs": [
        {"title": "T", "icon": "activity", "components": [
            {"id": "n", "type": "number_input", "label": "N"}]}]})
    module_id = created.json()[0]["id"]
    def ask(*a, **k):
        raise ClarifyingQuestion("Which units?")
    monkeypatch.setattr(orchestrator, "refine_module", ask)
    r = client.post(f"/api/modules/{module_id}/refine", json={"prompt": "make it better"})
    assert r.status_code == 422
    assert r.json()["detail"]["question"] == "Which units?"
```

(`client` is the existing fixture in `backend/tests/conftest.py`; check its exact name/shape before writing and match it.)

- [ ] **Step 2: Run to verify failures**

Run: `python -m pytest backend/tests/test_honesty.py -v --no-cov`
Expected: FAIL — `GenResult` doesn't exist / `generate` returns `str` / refine returns unchanged config / refine route 500s.

- [ ] **Step 3: Implement the `GenResult` seam in `backend/src/llm.py`**

Add near the top:

```python
import contextvars
from dataclasses import dataclass


@dataclass
class GenResult:
    text: str
    provider: str
    model: str
    degraded: bool = False
    tokens_in: int | None = None
    tokens_out: int | None = None


last_call: contextvars.ContextVar[GenResult | None] = contextvars.ContextVar(
    "llm_last_call", default=None
)
```

Rewrite `generate` (llm.py:239-263) to return `GenResult`, setting `last_call` before returning; the cascade paths mark `degraded=True` and, on the `expect_array` decompose path, fall back to the multi-module system templates (not a single template):

```python
def generate(
    prompt: str,
    system: str | None = None,
    *,
    schema: dict | None = None,
    expect_array: bool = False,
) -> GenResult:
    provider = _resolve_provider()
    model = os.environ.get("TRUS_LLM_MODEL") or os.environ.get("GEMINI_MODEL") or "stub"

    def _done(r: GenResult) -> GenResult:
        last_call.set(r)
        return r

    def _stub_text() -> str:
        if expect_array:
            import json

            from src.stub_templates import pick_system

            return json.dumps(pick_system(prompt))
        return _stub_module_for(prompt)

    if provider == "stub":
        return _done(GenResult(_stub_text(), "stub", "stub"))
    if provider == "openai":
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        try:
            text, usage = _openai_chat(messages, schema=schema, expect_array=expect_array)
            return _done(GenResult(text, "openai", model,
                                   tokens_in=usage.get("prompt_tokens"),
                                   tokens_out=usage.get("completion_tokens")))
        except LLMError:
            if not _cascade_enabled():
                raise
            if not _is_stub_key(os.environ.get("GEMINI_API_KEY")):
                return _done(GenResult(_gemini_generate(prompt, system),
                                       "gemini", model, degraded=True))
            return _done(GenResult(_stub_text(), "stub", "stub", degraded=True))
    return _done(GenResult(_gemini_generate(prompt, system), "gemini", model))
```

Change `_openai_chat` to also return the `usage` dict from the payload (`payload.get("usage", {})`) — update its return statement (llm.py:227-233) to `return text, payload.get("usage", {})` and its type hint to `tuple[str, dict]`. Fix its two existing call sites (`generate` above; check for others with `grep -n "_openai_chat(" backend/src`).

- [ ] **Step 4: Update every `llm.generate` caller to use `.text`**

Run: `grep -rn "llm.generate(" backend/src` — expected callers: `services/orchestrator.py` (`_generate_validated`), `services/studio.py`, `services/capture/transform.py`. In each, `raw = llm.generate(...)` becomes `raw = llm.generate(...).text` (in `_generate_validated`, keep the `GenResult` in a local so orchestrator can check degradation — see next step). Update tests that monkeypatch `llm.generate` to return a `GenResult` (grep `backend/tests` for `llm, "generate"` and `llm.generate`).

- [ ] **Step 5: Orchestrator honesty**

In `backend/src/services/orchestrator.py`:

(a) `generate_modules` (351-377): skip the cache store when the call was degraded —

```python
    result = _generate_validated(
        _seeded_system(prompt, existing_modules, seed_override=cached if mode == "seed" else None),
        DECOMPOSE_SYSTEM_PROMPT,
        _parse_modules,
        expect_array=True,
    )
    last = llm.last_call.get()
    if last is None or not last.degraded:
        semantic_cache.store("system", prompt, [m.model_dump(mode="json") for m in result])
    return result
```

(b) `refine_module` (412-419): stub mode raises instead of faking success —

```python
    if llm.is_stub_mode():
        raise LLMError(
            "Refine needs a live model; the app is in offline template mode."
        )
```

(import `LLMError` from `src.schema` if not already imported in this module).

(c) `generate_modules_from_file` (396-404): the `"{}"` sentinel becomes an honest refusal instead of silent templates —

```python
        if not raw or raw.strip() in ("{}", ""):
            raise RefusalError(
                "This file type can't be read with the current model configuration — "
                "try an image, or paste the document's text into the prompt."
            )
```

- [ ] **Step 6: Route + response surfacing**

`backend/src/schema.py` — add to `GenerateResponse`: `degraded: bool = False`.
`backend/src/routes/modules.py`:
- In `generate_module` and `preview_modules`, after a successful orchestrator call: `deg = llm.last_call.get(); ...degraded=bool(deg and deg.degraded)` passed into the `GenerateResponse` constructor (import `llm` at top).
- `refine_module` (265-275) and `workspace_insights` (342-350): add `except ClarifyingQuestion as e: raise HTTPException(status_code=422, detail={"question": e.question}) from e` above the `RefusalError` handler, and change both `LLMError` handlers to `except LLMError as e: raise HTTPException(status_code=503, detail=str(e) or "AI generation is temporarily unavailable.") from None`.

`frontend/src/lib/api.ts` — add `degraded?: boolean | null;` to `GenerateResponse` (line 46-51).
`frontend/src/components/PromptBar.tsx` — where preview/generate responses are handled, if `res.degraded` show the existing toast/notice mechanism with: `"Offline fallback: built from a local template, not the AI model."` (find the component's existing error/notice state — reuse it, don't invent a new system).

- [ ] **Step 7: Run tests**

Run: `python -m pytest backend/tests/test_honesty.py -v --no-cov` → 4 PASS.
Run: `python -m pytest -q` → 0 failed (fix any monkeypatch-shape breaks found).
Run: `cd frontend && npx tsc --noEmit` → 0 errors.

- [ ] **Step 8: Commit**

```bash
git add -A && git commit -m "feat(backend): provenance-carrying LLM seam — degradation visible, never cached

R-403 AC: cascade fallbacks flagged degraded and excluded from the semantic cache;
stub-mode refine raises honestly; file-path '{}' sentinel is an honest refusal.
R-304/R-1104: ClarifyingQuestion no longer 500s refine/insights; LLMError detail surfaced.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Tolerant reads — one bad row never breaks a workspace (R-1105)

**Files:**
- Modify: `backend/src/db.py` (`_stored_from_row:375-383`, `list_modules`, `list_archived`, `get_module`, plus the version/snapshot read paths near lines 489 and 615)
- Test: `backend/tests/test_tolerant_reads.py` (new)

**Interfaces:**
- Consumes: Task 2 (WAL `_conn`).
- Produces: `_stored_from_row(r) -> StoredModule | None` (None = quarantined row, logged); all list/get paths skip quarantined rows.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_tolerant_reads.py`:

```python
"""R-1105 AC: a corrupted row degrades only itself, never the workspace load."""
import sqlite3

from src import db


def _corrupt_row(db_path: str, session_id: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO modules (id, session_id, page_id, config_json, created_at, updated_at)"
        " VALUES ('bad-row', ?, NULL, '{\"not\": \"a module config\"}', '2026-01-01', '2026-01-01')",
        (session_id,),
    )
    conn.commit()
    conn.close()


def test_list_modules_survives_corrupt_row(tmp_path, monkeypatch):
    db_path = str(tmp_path / "t.db")
    monkeypatch.setenv("TRUS_DB_PATH", db_path)
    db.init_db()
    sid = db.ensure_session(None)
    from src.stub_templates import pick_template
    from src.schema import ModuleConfig

    good = db.insert_module(sid, ModuleConfig.model_validate(pick_template("track water")))
    _corrupt_row(db_path, sid)
    listed = db.list_modules(sid)
    assert [m.id for m in listed] == [good.id]  # workspace loads; bad row quarantined
    assert db.get_module(sid, "bad-row") is None  # unreadable → treated as absent
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest backend/tests/test_tolerant_reads.py -v --no-cov`
Expected: FAIL with `pydantic_core.ValidationError` raised from `list_modules`.

- [ ] **Step 3: Implement tolerant reads in `backend/src/db.py`**

```python
import logging

_log = logging.getLogger(__name__)


def _stored_from_row(r) -> StoredModule | None:
    try:
        return StoredModule(
            id=r["id"],
            config=ModuleConfig.model_validate_json(r["config_json"]),
            created_at=r["created_at"],
            updated_at=r["updated_at"],
            page_id=r["page_id"],
            archived=bool(r["archived"]),
        )
    except Exception:
        _log.warning("Quarantined unreadable module row %s (R-1105)", r["id"])
        return None
```

Then filter every consumer:
- `get_module`: `return _stored_from_row(row) if row else None` already handles it (None flows through).
- `list_modules` / `list_archived`: `return [m for m in (_stored_from_row(r) for r in rows) if m is not None]`.
- Apply the same try/except-skip pattern to the two other strict read paths the audit cites: the module-version parse used by undo/history (db.py near line 489) and the snapshot-restore parse (near line 615) — a bad version row is skipped (undo falls through to the next older version), a bad snapshot row aborts the restore cleanly BEFORE any deletion happens (return False).

- [ ] **Step 4: Run tests**

Run: `python -m pytest backend/tests/test_tolerant_reads.py -v --no-cov` → PASS.
Run: `python -m pytest -q` → 0 failed.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "fix(db): tolerant reads — quarantine unreadable rows instead of 500ing the workspace

R-1105 AC: corrupted row degrades only itself; list/get/undo/restore all survive.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Observability — logging, per-generation telemetry, operator surface (R-1201–1203, R-905 groundwork)

**Files:**
- Modify: `backend/src/db.py` (DDL + `add_gen_event` + `gen_stats` + `daily_active`), `backend/src/main.py` (logging config, global exception logging, `/api/ops/summary`), `backend/src/routes/modules.py` (instrument the five LLM handlers)
- Test: `backend/tests/test_telemetry.py` (new)

**Interfaces:**
- Consumes: Task 3 (`llm.last_call` GenResult with provider/model/tokens).
- Produces: `db.add_gen_event(owner: str, kind: str, outcome: str, provider: str | None, model: str | None, latency_ms: int, tokens_in: int | None, tokens_out: int | None) -> None`; `db.gen_stats(days: int = 7) -> dict`; `db.daily_active(days: int = 14) -> list[dict]` (rows: `{"day": "...", "owners": N}`); `GET /api/ops/summary?token=` gated by `TRUS_OPS_TOKEN`. Task 6 swaps `owner` semantics from sid to user id transparently.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_telemetry.py`:

```python
"""R-1201/R-1202/R-1203: activity measurable, generations accounted, ops surface gated."""
from fastapi.testclient import TestClient

from src import db
from src.main import app


def test_generation_records_event(tmp_path, monkeypatch):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    with TestClient(app) as client:
        r = client.post("/api/modules/preview", json={"prompt": "track my reading"})
        assert r.status_code == 200
    stats = db.gen_stats(days=1)
    assert stats["total"] == 1
    assert stats["by_outcome"].get("ok") == 1
    assert db.daily_active(days=1)[0]["owners"] >= 1


def test_failed_generation_records_error_outcome(tmp_path, monkeypatch):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    from src.schema import LLMError
    from src.services import orchestrator
    def boom(*a, **k):
        raise LLMError("down")
    monkeypatch.setattr(orchestrator, "generate_modules", boom)
    with TestClient(app) as client:
        r = client.post("/api/modules/preview", json={"prompt": "x y z"})
        assert r.status_code == 503
    assert db.gen_stats(days=1)["by_outcome"].get("error") == 1


def test_ops_summary_is_token_gated(tmp_path, monkeypatch):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TRUS_OPS_TOKEN", "sekrit")
    with TestClient(app) as client:
        assert client.get("/api/ops/summary").status_code == 401
        assert client.get("/api/ops/summary?token=wrong").status_code == 401
        ok = client.get("/api/ops/summary?token=sekrit")
        assert ok.status_code == 200
        assert {"generations", "daily_active"} <= set(ok.json().keys())
```

- [ ] **Step 2: Run to verify failures**

Run: `python -m pytest backend/tests/test_telemetry.py -v --no-cov` → FAIL (`gen_stats` missing, route missing).

- [ ] **Step 3: Implement the telemetry table + helpers in `backend/src/db.py`**

Add to the DDL block (same style as existing tables):

```sql
CREATE TABLE IF NOT EXISTS gen_events (
    id          TEXT PRIMARY KEY,
    owner       TEXT NOT NULL,
    kind        TEXT NOT NULL,      -- generate | preview | file | refine | insights
    outcome     TEXT NOT NULL,      -- ok | degraded | question | refusal | error
    provider    TEXT,
    model       TEXT,
    latency_ms  INTEGER,
    tokens_in   INTEGER,
    tokens_out  INTEGER,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gen_events_owner_day ON gen_events (owner, created_at);
```

And the functions:

```python
def add_gen_event(owner: str, kind: str, outcome: str, provider: str | None,
                  model: str | None, latency_ms: int,
                  tokens_in: int | None, tokens_out: int | None) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO gen_events (id, owner, kind, outcome, provider, model,"
            " latency_ms, tokens_in, tokens_out, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), owner, kind, outcome, provider, model,
             latency_ms, tokens_in, tokens_out, _now()),
        )


def gen_stats(days: int = 7) -> dict:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _conn() as c:
        rows = c.execute(
            "SELECT outcome, COUNT(*) n, SUM(COALESCE(tokens_in,0)) tin,"
            " SUM(COALESCE(tokens_out,0)) tout, AVG(latency_ms) lat"
            " FROM gen_events WHERE created_at >= ? GROUP BY outcome", (cutoff,)
        ).fetchall()
    return {
        "total": sum(r["n"] for r in rows),
        "by_outcome": {r["outcome"]: r["n"] for r in rows},
        "tokens_in": sum(r["tin"] or 0 for r in rows),
        "tokens_out": sum(r["tout"] or 0 for r in rows),
        "avg_latency_ms": round(sum((r["lat"] or 0) * r["n"] for r in rows) / max(1, sum(r["n"] for r in rows))),
    }


def daily_active(days: int = 14) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _conn() as c:
        rows = c.execute(
            "SELECT substr(created_at, 1, 10) day, COUNT(DISTINCT owner) owners"
            " FROM gen_events WHERE created_at >= ? GROUP BY day ORDER BY day DESC",
            (cutoff,),
        ).fetchall()
    return [{"day": r["day"], "owners": r["owners"]} for r in rows]
```

(`from datetime import timedelta` — extend the existing datetime import.)

- [ ] **Step 4: Instrument the five LLM handlers in `backend/src/routes/modules.py`**

Add one helper at module level (it must observe the raw orchestrator exceptions, so it wraps only the orchestrator call and re-raises untouched):

```python
import contextlib as _contextlib
import time as _time


@_contextlib.contextmanager
def _track(sid: str, kind: str):
    """Times the wrapped orchestrator call and records a gen_event (R-1202).
    Re-raises everything; recording itself is best-effort and never fails a request."""
    t0 = _time.monotonic()
    outcome = "ok"
    try:
        yield
    except ClarifyingQuestion:
        outcome = "question"
        raise
    except RefusalError:
        outcome = "refusal"
        raise
    except LLMError:
        outcome = "error"
        raise
    finally:
        last = llm.last_call.get()
        if outcome == "ok" and last is not None and last.degraded:
            outcome = "degraded"
        with _contextlib.suppress(Exception):
            db.add_gen_event(
                sid, kind, outcome,
                last.provider if last else None,
                last.model if last else None,
                int((_time.monotonic() - t0) * 1000),
                last.tokens_in if last else None,
                last.tokens_out if last else None,
            )
```

Usage in each handler — `with _track(...)` goes INSIDE the `try`, wrapping only the orchestrator call, so the existing `except` clauses still convert the exceptions afterwards. Example for `preview_modules`; same shape in `generate_module` [kind="generate"], `generate_from_file` ["file"], `refine_module` ["refine"], `workspace_insights` ["insights"]:

```python
    try:
        with _track(sid, "preview"):
            configs = orchestrator.generate_modules(prompt, existing_modules=existing)
    except ClarifyingQuestion as e:
        return GenerateResponse(question=e.question)
    except RefusalError as e:
        raise HTTPException(status_code=422, detail={"refusal": e.reason}) from e
    except LLMError as e:
        raise HTTPException(status_code=503, detail=str(e) or "AI generation is temporarily unavailable.") from None
```

- [ ] **Step 5: Logging config + ops endpoint in `backend/src/main.py`**

```python
import logging

logging.basicConfig(
    level=os.environ.get("TRUS_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
```

And the gated operator summary (R-1201/R-1203):

```python
from fastapi import HTTPException, Query


@app.get("/api/ops/summary")
def ops_summary(token: str = Query(default="")) -> dict:
    expected = os.environ.get("TRUS_OPS_TOKEN", "")
    if not expected or token != expected:
        raise HTTPException(status_code=401, detail="ops token required")
    return {"generations": db.gen_stats(days=7), "daily_active": db.daily_active(days=14)}
```

Also add a global unhandled-exception logger so backend errors always reach the operator log (R-1203):

```python
@app.middleware("http")
async def log_unhandled(request, call_next):
    try:
        return await call_next(request)
    except Exception:
        logging.getLogger("trus.unhandled").exception("%s %s", request.method, request.url.path)
        raise
```

- [ ] **Step 6: Run tests**

Run: `python -m pytest backend/tests/test_telemetry.py -v --no-cov` → 3 PASS.
Run: `python -m pytest -q` → 0 failed.

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat(backend): generation telemetry, DAU query, gated ops summary, logging

R-1202 AC: every generation records outcome/latency/tokens per owner.
R-1201 AC: 'who used it yesterday' answerable from gen_events.
R-1203: unhandled exceptions logged; /api/ops/summary token-gated.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Identity — users, invite claims, gating, per-owner scoping of the shared stores (R-901–905, R-903, R-1004)

**Files:**
- Create: `backend/src/routes/auth.py`, `backend/src/invites.py`
- Modify: `backend/src/db.py` (users DDL + sessions.user_id migration + user fns + gen_cache/layout_library owner columns), `backend/src/routes/modules.py:28-32` (`_session_id` → `_owner_id`), `backend/src/routes/pages.py` + `conversations.py` + `studio.py` (same owner resolution + gating), `backend/src/semantic_cache.py` (owner-scoped lookup/store), `backend/src/main.py` (mount auth router)
- Test: `backend/tests/test_identity.py` (new)

**Interfaces:**
- Consumes: Tasks 2–5.
- Produces: `db.create_user(name: str) -> dict` (returns `{"id", "name", "invite_token"}`); `db.user_by_token(token: str) -> dict | None`; `db.revoke_user(user_id: str) -> bool`; `db.adopt_session_data(old_owner: str, user_id: str) -> None`; route dependency `_owner_id(request) -> str` (401 when unclaimed and `TRUS_ALLOW_ANON != "1"`); `GET /api/auth/claim?token=` and `GET /api/auth/me`; `semantic_cache.lookup(kind, prompt, owner)` / `.store(kind, prompt, configs, owner)`; CLI `python -m src.invites create|list|revoke`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_identity.py`:

```python
"""R-901-903: gated access, cross-device continuity, per-owner isolation."""
from fastapi.testclient import TestClient

from src import db
from src.main import app


def _client(tmp_path, monkeypatch, allow_anon="0"):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TRUS_ALLOW_ANON", allow_anon)
    return TestClient(app)


def test_unclaimed_session_is_401_when_anon_disabled(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        assert client.get("/api/modules").status_code == 401
        assert client.post("/api/modules/preview", json={"prompt": "x"}).status_code == 401


def test_claim_grants_access_and_two_devices_share_a_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TRUS_ALLOW_ANON", "0")
    user = db.create_user("Janus")
    with TestClient(app) as device_a, TestClient(app) as device_b:
        assert device_a.get(f"/api/auth/claim?token={user['invite_token']}").status_code == 200
        created = device_a.post("/api/modules", json={"configs": [
            {"title": "Shared", "icon": "activity", "components": [
                {"id": "n", "type": "number_input", "label": "N"}]}]})
        assert created.status_code == 201
        assert device_b.get(f"/api/auth/claim?token={user['invite_token']}").status_code == 200
        titles = [m["config"]["title"] for m in device_b.get("/api/modules").json()]
        assert "Shared" in titles  # R-902 AC: same workspace from a second device


def test_revoked_invite_cannot_claim(tmp_path, monkeypatch):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    user = db.create_user("Gone")
    db.revoke_user(user["id"])
    with TestClient(app) as client:
        assert client.get(f"/api/auth/claim?token={user['invite_token']}").status_code == 403


def test_semantic_cache_is_owner_scoped(tmp_path, monkeypatch):
    """R-903 AC: user B's similar prompt never receives user A's cached content."""
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TRUS_CACHE", "on")
    from src import semantic_cache
    db.init_db()
    semantic_cache.store("system", "track my secret project", [{"title": "A's tool"}], owner="user-a")
    mode, cached = semantic_cache.lookup("system", "track my secret project", owner="user-b")
    assert mode != "hit"  # exact same prompt, different owner → no leak
    mode_a, cached_a = semantic_cache.lookup("system", "track my secret project", owner="user-a")
    assert mode_a == "hit" and cached_a == [{"title": "A's tool"}]
```

- [ ] **Step 2: Run to verify failures**

Run: `python -m pytest backend/tests/test_identity.py -v --no-cov` → FAIL (`create_user` missing, no 401s, cache not owner-scoped).

- [ ] **Step 3: DB layer — users, migration, owner columns**

`backend/src/db.py` DDL additions:

```sql
CREATE TABLE IF NOT EXISTS users (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    invite_token TEXT NOT NULL UNIQUE,
    created_at   TEXT NOT NULL,
    revoked_at   TEXT
);
```

In `_migrate` (follow the existing additive-column pattern at db.py:150-158): add `user_id TEXT` to `sessions`, and `owner TEXT` to both `gen_cache` and `layout_library`.

New functions (uuid4-hex double token for invites — unguessable, URL-safe):

```python
def create_user(name: str) -> dict:
    token = uuid.uuid4().hex + uuid.uuid4().hex
    uid = str(uuid.uuid4())
    with _conn() as c:
        c.execute(
            "INSERT INTO users (id, name, invite_token, created_at) VALUES (?, ?, ?, ?)",
            (uid, name, token, _now()),
        )
    return {"id": uid, "name": name, "invite_token": token}


def user_by_token(token: str) -> dict | None:
    with _conn() as c:
        r = c.execute(
            "SELECT id, name, revoked_at FROM users WHERE invite_token = ?", (token,)
        ).fetchone()
    return dict(r) if r else None


def user_by_id(user_id: str) -> dict | None:
    with _conn() as c:
        r = c.execute(
            "SELECT id, name, revoked_at FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    return dict(r) if r else None


def list_users() -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT id, name, invite_token, created_at, revoked_at FROM users").fetchall()
    return [dict(r) for r in rows]


def revoke_user(user_id: str) -> bool:
    with _conn() as c:
        cur = c.execute("UPDATE users SET revoked_at = ? WHERE id = ?", (_now(), user_id))
        return cur.rowcount > 0


def adopt_session_data(old_owner: str, user_id: str) -> None:
    """First claim from a device that already has anonymous data: move it to the user."""
    if old_owner == user_id:
        return
    with _conn() as c:
        for table in ("pages", "modules", "module_versions", "messages", "snapshots"):
            c.execute(f"UPDATE {table} SET session_id = ? WHERE session_id = ?", (user_id, old_owner))
```

(Check each of those five tables' owner column is really named `session_id` — `grep -n "session_id" backend/src/db.py` — and adjust the list to the tables that have it.)

- [ ] **Step 4: Owner resolution + gating in routes**

`backend/src/routes/modules.py` — replace `_session_id` (28-32):

```python
def _owner_id(request: Request) -> str:
    """The data-owner key: the claimed user id, else (dev only) the anonymous sid."""
    uid = request.session.get("uid")
    if uid:
        user = db.user_by_id(uid)
        if user and not user["revoked_at"]:
            return uid
        request.session.pop("uid", None)  # revoked or deleted → back to gate
    if os.environ.get("TRUS_ALLOW_ANON", "1") == "1":
        sid = db.ensure_session(request.session.get("sid"))
        request.session["sid"] = sid
        return sid
    raise HTTPException(status_code=401, detail="Invite required")
```

Rename every `_session_id(request)` call in `modules.py` to `_owner_id(request)` (grep the file). Give `pages.py` and `conversations.py` the same treatment — they have their own copies of `_session_id` (grep for it); extract the shared helper into a new `backend/src/routes/deps.py` and import it from all three (plus `studio.py`, which currently has NO session use: add `owner = _owner_id(request)` to every studio endpoint and filter/stamp `layout_library.owner` in the queries it calls — `db.layout_add`, `db.layout_list`, `db.layout_delete`, `db.layout_promote` gain an `owner` parameter; follow each function's existing signature style).

- [ ] **Step 5: Claim endpoint + auth router**

Create `backend/src/routes/auth.py`:

```python
import os

from fastapi import APIRouter, HTTPException, Request

from src import db

router = APIRouter()


@router.get("/auth/claim")
def claim(token: str, request: Request) -> dict:
    user = db.user_by_token(token)
    if user is None:
        raise HTTPException(status_code=404, detail="Unknown invite")
    if user["revoked_at"]:
        raise HTTPException(status_code=403, detail="Invite revoked")
    old_sid = request.session.get("sid")
    request.session["uid"] = user["id"]
    if old_sid:
        db.adopt_session_data(old_sid, user["id"])  # keep pre-claim anonymous work
    return {"ok": True, "name": user["name"]}


@router.get("/auth/me")
def me(request: Request) -> dict:
    uid = request.session.get("uid")
    user = db.user_by_id(uid) if uid else None
    if user and not user["revoked_at"]:
        return {"claimed": True, "name": user["name"]}
    return {"claimed": bool(os.environ.get("TRUS_ALLOW_ANON", "1") == "1"), "name": None}
```

Mount in `backend/src/main.py`: `from src.routes import auth` … `app.include_router(auth.router, prefix="/api")`.

- [ ] **Step 6: Owner-scope the semantic cache**

`backend/src/semantic_cache.py`: add `owner: str` keyword param to `lookup(kind, prompt, owner)` and `store(kind, prompt, configs, owner)`; thread it into the SQL (`WHERE owner = ?` on select; stamp on insert — the underlying `db.cache_*` functions gain the column). Update the two orchestrator call sites (`generate_modules`) to pass the owner — which requires `generate_modules(prompt, existing_modules, owner)`: add the parameter, pass it from the routes (`orchestrator.generate_modules(prompt, existing_modules=existing, owner=sid)` where `sid = _owner_id(request)`). Keep a default `owner="local"` so direct library use and old tests keep working, and update tests that call `lookup/store` positionally.

- [ ] **Step 7: Invite CLI**

Create `backend/src/invites.py`:

```python
"""Provision alpha invites: python -m src.invites create "Name" | list | revoke <id>"""
import os
import sys

from src import db


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    base = os.environ.get("TRUS_PUBLIC_URL", "http://localhost:3000")
    if cmd == "create":
        u = db.create_user(sys.argv[2])
        print(f"{u['name']}: {base}/claim?token={u['invite_token']}")
    elif cmd == "revoke":
        print("revoked" if db.revoke_user(sys.argv[2]) else "not found")
    else:
        for u in db.list_users():
            state = "REVOKED" if u["revoked_at"] else "active"
            print(f"{u['id']}  {u['name']:<20} {state}  {base}/claim?token={u['invite_token']}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 8: Run tests; fix ripples**

Run: `python -m pytest backend/tests/test_identity.py -v --no-cov` → 4 PASS.
Run: `python -m pytest -q` → 0 failed. Existing tests run with `TRUS_ALLOW_ANON` unset (default `1` = dev) so anonymous flows keep working; any test that asserts studio routes work without a session gets the same default. Fix signature ripples surfaced by the run (semantic_cache/orchestrator/studio db fns).

- [ ] **Step 9: Commit**

```bash
git add -A && git commit -m "feat(backend): invite-claimed identity, gated access, per-owner shared stores

R-901 AC: unauthenticated/unclaimed requests get 401 (no spend, reads, or writes).
R-902 AC: second device claims the same link -> same workspace (adopt-on-claim).
R-903/R-1004 AC: gen_cache + layout_library owner-scoped; cross-owner hit impossible.
R-904: python -m src.invites create/list/revoke. R-905: owner = user id in gen_events.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Production config — env-driven CORS/cookies, secret enforcement, Dockerfile (R-906 buildout, R-901 hardening)

**Files:**
- Modify: `backend/src/main.py:20-35`, `.env.example`
- Create: `backend/Dockerfile`, `deploy/README.md`, `deploy/fly.toml.example`
- Test: `backend/tests/test_prod_config.py` (new)

**Interfaces:**
- Consumes: Task 6 (auth flags).
- Produces: `src.main.create_configured_app()` boot-guard behavior (module import raises in prod with default secret); env-driven middleware config. The operator deploy checkpoint (Stage-Exit) uses the Dockerfile.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_prod_config.py`:

```python
"""R-901/R-906: prod refuses the known-forgeable default secret; CORS is env-driven."""
import importlib

import pytest


def test_prod_refuses_default_session_secret(monkeypatch):
    monkeypatch.setenv("TRUS_ENV", "prod")
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    import src.main
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        importlib.reload(src.main)
    monkeypatch.setenv("TRUS_ENV", "dev")
    importlib.reload(src.main)  # restore for other tests


def test_cors_origins_env_driven(monkeypatch):
    monkeypatch.setenv("TRUS_CORS_ORIGINS", "https://app.example.com,https://trus.example.com")
    import src.main
    importlib.reload(src.main)
    cors = next(m for m in src.main.app.user_middleware if "CORSMiddleware" in str(m))
    assert "https://app.example.com" in cors.kwargs["allow_origins"]
    monkeypatch.delenv("TRUS_CORS_ORIGINS")
    importlib.reload(src.main)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest backend/tests/test_prod_config.py -v --no-cov` → FAIL (no RuntimeError; origins hardcoded).

- [ ] **Step 3: Implement in `backend/src/main.py`**

Replace the middleware block (lines 20-35):

```python
_SECRET = os.environ.get("SESSION_SECRET", "dev-insecure-key-change-me")
if os.environ.get("TRUS_ENV", "dev") == "prod" and _SECRET == "dev-insecure-key-change-me":
    raise RuntimeError(
        "SESSION_SECRET must be set to a strong value in prod (R-901): "
        "the default key is public and makes every session forgeable."
    )

_COOKIE_SECURE = os.environ.get("TRUS_COOKIE_SECURE", "0") == "1"

app.add_middleware(
    SessionMiddleware,
    secret_key=_SECRET,
    session_cookie="trus_sid",
    same_site="none" if _COOKIE_SECURE else "lax",  # cross-origin hosted split needs none+secure
    https_only=_COOKIE_SECURE,
    max_age=60 * 60 * 24 * 365,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get(
        "TRUS_CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)
```

- [ ] **Step 4: Dockerfile + deploy reference**

`backend/Dockerfile`:

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src ./src
ENV TRUS_ENV=prod TRUS_ALLOW_ANON=0 TRUS_COOKIE_SECURE=1 TRUS_DB_PATH=/data/trus.db
EXPOSE 8080
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

`deploy/fly.toml.example` (reference default per spec Appendix A — builder may pick Railway/Render instead):

```toml
app = "trus-backend"
primary_region = "sjc"

[build]
  dockerfile = "../backend/Dockerfile"

[env]
  TRUS_ENV = "prod"
  TRUS_ALLOW_ANON = "0"
  TRUS_COOKIE_SECURE = "1"
  TRUS_DB_PATH = "/data/trus.db"
  # TRUS_CORS_ORIGINS / TRUS_PUBLIC_URL: set to the Vercel URL
  # SESSION_SECRET / TRUS_OPS_TOKEN / GEMINI_API_KEY: set via `fly secrets set`

[mounts]
  source = "trus_data"
  destination = "/data"

[[services]]
  internal_port = 8080
  protocol = "tcp"
  [[services.ports]]
    handlers = ["http"]
    port = 80
  [[services.ports]]
    handlers = ["tls", "http"]
    port = 443
```

`deploy/README.md`: document the 6 required secrets/envs (SESSION_SECRET, TRUS_CORS_ORIGINS, TRUS_PUBLIC_URL, TRUS_OPS_TOKEN, GEMINI_API_KEY, TRUS_DB_PATH), the Vercel side (`NEXT_PUBLIC_API_BASE` → backend URL), the invite provisioning command (`fly ssh console -C "python -m src.invites create 'Name'"`), and the R-906 AC as the smoke test. Update `.env.example` with the new flags and a warning that `dev-insecure-key-change-me` refuses to boot in prod.

- [ ] **Step 5: Run tests**

Run: `python -m pytest backend/tests/test_prod_config.py -v --no-cov` → 2 PASS.
Run: `python -m pytest -q` → 0 failed.
Run: `docker build -t trus-backend backend/` (skip with a note if Docker isn't installed locally — CI/deploy will exercise it).

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat(deploy): prod config guards + Dockerfile + Fly reference

R-901: boot refuses the public default SESSION_SECRET in prod.
R-906 buildout: env-driven CORS/cookies (cross-origin split works), container image,
deploy reference. Actual deployment is the operator checkpoint at stage exit.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: Frontend gate — claim page, 401 handling, identity chip

**Files:**
- Create: `frontend/src/app/claim/page.tsx`, `frontend/src/components/InviteGate.tsx`
- Modify: `frontend/src/lib/api.ts` (add `authMe`, `authClaim`), `frontend/src/app/page.tsx` (401 → gate)
- Test: `cd frontend && npx tsc --noEmit` + manual flow (frontend test infra lands in Task 9)

**Interfaces:**
- Consumes: Task 6 endpoints (`/api/auth/claim`, `/api/auth/me`).
- Produces: `/claim?token=…` claims and redirects to `/`; unclaimed users see `InviteGate` instead of a broken canvas.

- [ ] **Step 1: API client additions** (`frontend/src/lib/api.ts`, inside the `api` object)

```typescript
  authMe: () => request<{ claimed: boolean; name: string | null }>("/api/auth/me"),
  authClaim: (token: string) =>
    request<{ ok: boolean; name: string }>(`/api/auth/claim?token=${encodeURIComponent(token)}`),
```

- [ ] **Step 2: Claim page** — `frontend/src/app/claim/page.tsx`

(Next 16 App Router — verify `useSearchParams` conventions in `node_modules/next/dist/docs/` per `frontend/AGENTS.md` before writing.)

```tsx
"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";

function ClaimInner() {
  const params = useSearchParams();
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const token = params.get("token");
    if (!token) { setError("This invite link is missing its token."); return; }
    api.authClaim(token)
      .then(() => router.replace("/"))
      .catch((e) => setError(e?.message ?? "This invite could not be claimed."));
  }, [params, router]);
  return (
    <main style={{ display: "grid", placeItems: "center", minHeight: "100vh" }}>
      <p>{error ?? "Claiming your invite…"}</p>
    </main>
  );
}

export default function ClaimPage() {
  return <Suspense fallback={null}><ClaimInner /></Suspense>;
}
```

(Style the two states to match the design ethos — reuse the IntroSplash typography tokens rather than inline styles if a shared class exists; check `frontend/src/components/IntroSplash.tsx`.)

- [ ] **Step 3: Invite gate + 401 handling**

`frontend/src/components/InviteGate.tsx`: a full-screen panel matching the app theme: headline "Trus is invite-only right now", body "Open your invite link on this device to enter your workspace.", no inputs.
`frontend/src/app/page.tsx`: on mount (where pages/modules load today), call `api.authMe()` first; if `{ claimed: false }` render `<InviteGate />` instead of the workspace. Also catch `ApiError` with `status === 401` from the initial loads and swap to the gate (belt and braces). Display the claimed `name` unobtrusively in the header area (identity chip) so a user can tell whose workspace they're in.

- [ ] **Step 4: Verify**

Run: `cd frontend && npx tsc --noEmit` → 0 errors. `npm run build` → clean.
Manual: with backend `TRUS_ALLOW_ANON=0`, visiting `/` shows the gate; `python -m src.invites create "Test"`, open the printed link → lands claimed on the canvas; second browser profile with same link → same workspace (R-902 AC).

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(frontend): invite claim page, 401 gate, identity chip

R-901/R-902: unclaimed visitors see the gate; one link-follow enters the workspace.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 9: Single-writer module saves with optimistic in-view updates (R-601, R-602 same-tab half)

**Files:**
- Create: `frontend/src/lib/moduleSaver.ts`, `frontend/src/lib/moduleSaver.test.ts`, `frontend/vitest.config.ts`
- Modify: `frontend/package.json` (vitest devDep + `"test": "vitest run"`), `frontend/src/components/Module.tsx` (drop local state + own persistence), `frontend/src/components/Inspector.tsx` (commit upward, no own PATCH), `frontend/src/components/Canvas.tsx` (layout commits via saver), `frontend/src/app/page.tsx` (owns the saver + save-status pill)

**Interfaces:**
- Consumes: nothing backend-side (rev conflicts arrive in Task 10).
- Produces: `createModuleSaver(deps: { patch: (id: string, config: ModuleConfig) => Promise<StoredModule> }): ModuleSaver` with `commit(id, config, delay?)`, `flush(id)`, `flushAll()`, `status(): SaveStatus` (`"idle" | "saving" | "error"`), `subscribe(fn): () => void`. ALL module persistence flows through one saver instance owned by `page.tsx`; `Module`/`Inspector`/`Canvas` become pure committers.

- [ ] **Step 1: Vitest infra + failing unit tests**

`cd frontend && npm i -D vitest` ; add `"test": "vitest run"` to scripts. `frontend/vitest.config.ts`:

```typescript
import { defineConfig } from "vitest/config";
export default defineConfig({ test: { include: ["src/**/*.test.ts"] } });
```

`frontend/src/lib/moduleSaver.test.ts`:

```typescript
import { describe, expect, it, vi } from "vitest";
import { createModuleSaver } from "./moduleSaver";
import type { ModuleConfig } from "./types";

const cfg = (title: string) => ({ title, icon: "activity", components: [] }) as unknown as ModuleConfig;
const saved = (id: string, config: ModuleConfig) =>
  ({ id, config, created_at: "", updated_at: "", page_id: null, archived: false }) as never;

describe("moduleSaver (R-602: one writer per module, no lost updates)", () => {
  it("coalesces rapid commits into one PATCH with the last config", async () => {
    vi.useFakeTimers();
    const patch = vi.fn(async (id: string, c: ModuleConfig) => saved(id, c));
    const s = createModuleSaver({ patch });
    s.commit("m1", cfg("a"));
    s.commit("m1", cfg("b"));
    s.commit("m1", cfg("c"));
    await vi.runAllTimersAsync();
    expect(patch).toHaveBeenCalledTimes(1);
    expect(patch.mock.calls[0][1].title).toBe("c");
    vi.useRealTimers();
  });

  it("a commit landing during an in-flight save triggers a follow-up save (no dropped edit)", async () => {
    vi.useFakeTimers();
    let resolveFirst!: () => void;
    const patch = vi
      .fn<(id: string, c: ModuleConfig) => Promise<never>>()
      .mockImplementationOnce((id, c) => new Promise((res) => { resolveFirst = () => res(saved(id, c)); }))
      .mockImplementation(async (id, c) => saved(id, c));
    const s = createModuleSaver({ patch });
    s.commit("m1", cfg("first"));
    await vi.runAllTimersAsync();          // first save now in flight
    s.commit("m1", cfg("second"));         // edit while saving
    resolveFirst();
    await vi.runAllTimersAsync();
    expect(patch).toHaveBeenCalledTimes(2);
    expect(patch.mock.calls[1][1].title).toBe("second");
    vi.useRealTimers();
  });

  it("failed saves retry with backoff and expose error status", async () => {
    vi.useFakeTimers();
    const patch = vi
      .fn<(id: string, c: ModuleConfig) => Promise<never>>()
      .mockRejectedValueOnce(new Error("net"))
      .mockImplementation(async (id, c) => saved(id, c));
    const s = createModuleSaver({ patch });
    s.commit("m1", cfg("x"));
    await vi.runAllTimersAsync();
    expect(s.status()).toBe("idle");        // retried and succeeded
    expect(patch).toHaveBeenCalledTimes(2);
    vi.useRealTimers();
  });
});
```

Run: `cd frontend && npm test` → FAIL (`moduleSaver` doesn't exist).

- [ ] **Step 2: Implement `frontend/src/lib/moduleSaver.ts`**

```typescript
import type { ModuleConfig, StoredModule } from "./types";

export type SaveStatus = "idle" | "saving" | "error";

interface Deps {
  patch: (id: string, config: ModuleConfig) => Promise<StoredModule>;
  onSaved?: (m: StoredModule) => void;
  onError?: (id: string, err: unknown) => void;
  debounceMs?: number;
}

export interface ModuleSaver {
  commit(id: string, config: ModuleConfig, delay?: number): void;
  flush(id: string): Promise<void>;
  flushAll(): Promise<void>;
  status(): SaveStatus;
  subscribe(fn: () => void): () => void;
  forget(id: string): void; // module deleted — drop pending work
}

export function createModuleSaver(deps: Deps): ModuleSaver {
  const debounce = deps.debounceMs ?? 400;
  const pending = new Map<string, ModuleConfig>();
  const timers = new Map<string, ReturnType<typeof setTimeout>>();
  const inFlight = new Set<string>();
  const errored = new Set<string>();
  const listeners = new Set<() => void>();
  const retryDelay = new Map<string, number>();

  const notify = () => listeners.forEach((fn) => fn());

  async function save(id: string): Promise<void> {
    const config = pending.get(id);
    if (config === undefined || inFlight.has(id)) return;
    pending.delete(id);
    inFlight.add(id);
    notify();
    try {
      const saved = await deps.patch(id, config);
      errored.delete(id);
      retryDelay.delete(id);
      deps.onSaved?.(saved);
    } catch (err) {
      // keep the newest config: an edit made during the failed save wins
      if (!pending.has(id)) pending.set(id, config);
      errored.add(id);
      deps.onError?.(id, err);
      const delay = Math.min(retryDelay.get(id) ?? 1000, 30_000);
      retryDelay.set(id, delay * 2);
      schedule(id, delay);
    } finally {
      inFlight.delete(id);
      notify();
      if (pending.has(id) && !timers.has(id)) schedule(id, 0); // follow-up for mid-flight edits
    }
  }

  function schedule(id: string, delay: number): void {
    const t = timers.get(id);
    if (t) clearTimeout(t);
    timers.set(id, setTimeout(() => { timers.delete(id); void save(id); }, delay));
  }

  return {
    commit(id, config, delay = debounce) {
      pending.set(id, config);
      schedule(id, delay);
      notify();
    },
    async flush(id) {
      const t = timers.get(id);
      if (t) { clearTimeout(t); timers.delete(id); }
      await save(id);
    },
    async flushAll() {
      await Promise.all([...new Set([...pending.keys(), ...timers.keys()])].map((id) => this.flush(id)));
    },
    status() {
      if (errored.size) return "error";
      if (inFlight.size || pending.size || timers.size) return "saving";
      return "idle";
    },
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
    forget(id) {
      const t = timers.get(id);
      if (t) clearTimeout(t);
      timers.delete(id); pending.delete(id); errored.delete(id); inFlight.delete(id);
      notify();
    },
  };
}
```

Run: `npm test` → 3 PASS.

- [ ] **Step 3: Rewire the three writers through the saver + optimistic bubble**

`frontend/src/app/page.tsx` (the single state owner):
- Create one saver: `const saver = useMemo(() => createModuleSaver({ patch: (id, c) => api.patchModule(id, c), onSaved: (m) => setModules(...) /* reconcile updated_at only if no newer local edit */ }), [])`.
- Add `const commitModule = useCallback((id: string, config: ModuleConfig) => { setModules((ms) => ms.map((m) => (m.id === id ? { ...m, config } : m))); saver.commit(id, config); }, [saver])` — **the optimistic bubble: parent state updates immediately (R-601), the PATCH follows.** Pass `commitModule` down to Canvas/Module/Inspector in place of their current persistence props.
- `useEffect` cleanup + `beforeunload`: `window.addEventListener("beforeunload", (e) => { if (saver.status() !== "idle") { void saver.flushAll(); e.preventDefault(); } })`.
- Save pill: subscribe to the saver; render a small fixed pill near the header — `idle` → nothing (or "Saved"), `saving` → "Saving…", `error` → "Not saved — retrying" in the warning accent. Follow DESIGN-ETHOS.md tokens (R-1305: log a design check in the commit body).

`frontend/src/components/Module.tsx`:
- Delete the local `state` useState + the resync `useEffect` (lines 73-80) — render from `module.config.state` directly (single source of truth kills the keystroke-revert bug).
- `setField` builds `nextConfig = { ...module.config, state: nextState }` (including the existing automations loop) and calls the new `onCommit(module.id, nextConfig)` prop. Delete `persistConfig`/`schedulePersist` (108-131); preview variant keeps its in-memory `onChange` path.

`frontend/src/components/Inspector.tsx`: `persist` (64-94) stops calling `api.patchModule`; it builds the config exactly as today and calls `onCommit(module.id, config)` immediately (no debounce here — the saver debounces).

`frontend/src/components/Canvas.tsx`: drag/resize end (winUp, ~219-231) commits `{ ...module.config, layout: next }` via `onCommit` instead of its own PATCH — **layout and state edits now merge through one writer, retiring the edit-then-drag snap-back (R-602 AC #3).**

- [ ] **Step 4: Verify behavior**

Run: `cd frontend && npx tsc --noEmit && npm test && npm run build` → all clean.
Manual (both stub-mode backend ok): (1) type in a module's field then immediately drag it — both the text and the new position survive the next reload; (2) a metric bound to another module's field updates the instant you type, not after a delay; (3) stop the backend, edit a field — pill shows "Not saved — retrying", restart backend — pill returns to saved and the edit persists after reload.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(frontend): single-writer module saves + optimistic in-view updates

R-601 AC: dependent modules update immediately (parent state first, PATCH after).
R-602 AC: edit-then-drag keeps both changes; edits during in-flight saves never drop;
failed saves retry with visible status + beforeunload flush. Design pill checked
against DESIGN-ETHOS.md (R-1305).

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 10: Rev-based conflict detection — two tabs never silently clobber (R-602 cross-tab half)

**Files:**
- Modify: `backend/src/db.py` (modules `rev` column + `update_module:445-465`), `backend/src/schema.py` (`StoredModule.rev`, `UpdateModuleRequest.rev`), `backend/src/routes/modules.py` (PATCH handler 409 path), `frontend/src/lib/types.ts` (`StoredModule.rev`), `frontend/src/lib/api.ts` (`patchModule` sends rev), `frontend/src/lib/moduleSaver.ts` (409 → onConflict), `frontend/src/app/page.tsx` (conflict toast + reload)
- Test: `backend/tests/test_rev_conflict.py` (new), one more case in `frontend/src/lib/moduleSaver.test.ts`

**Interfaces:**
- Consumes: Task 9 saver.
- Produces: `StoredModule.rev: int` (backend + frontend types); `db.update_module(session_id, module_id, config, expected_rev: int | None = None)` raising `db.RevConflict(current: StoredModule)`; PATCH returns 409 `{"conflict": <current StoredModule>}`; saver `onConflict(current)` hook.

- [ ] **Step 1: Failing backend test**

Create `backend/tests/test_rev_conflict.py`:

```python
"""R-602 AC (two tabs): a stale writer gets 409 + the current module, never a silent wipe."""
from src import db
from src.schema import ModuleConfig
from src.stub_templates import pick_template


def test_stale_rev_raises_conflict(tmp_path, monkeypatch):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    db.init_db()
    sid = db.ensure_session(None)
    m = db.insert_module(sid, ModuleConfig.model_validate(pick_template("track water")))
    assert m.rev == 0
    c2 = m.config.model_copy(update={"title": "Tab A change"})
    updated = db.update_module(sid, m.id, c2, expected_rev=0)
    assert updated.rev == 1
    import pytest
    c3 = m.config.model_copy(update={"title": "Tab B stale change"})
    with pytest.raises(db.RevConflict) as exc:
        db.update_module(sid, m.id, c3, expected_rev=0)  # tab B still thinks rev 0
    assert exc.value.current.config.title == "Tab A change"
```

Run: `python -m pytest backend/tests/test_rev_conflict.py -v --no-cov` → FAIL.

- [ ] **Step 2: Backend implementation**

`db.py`: `_migrate` adds `rev INTEGER NOT NULL DEFAULT 0` to `modules`; add `rev=r["rev"]` in `_stored_from_row` and `rev` to `_MOD_COLS`; define `class RevConflict(Exception): def __init__(self, current): self.current = current`; rewrite `update_module`:

```python
def update_module(
    session_id: str, module_id: str, config: ModuleConfig, expected_rev: int | None = None
) -> StoredModule | None:
    now = _now()
    config_json = config.model_dump_json()
    with _conn() as c:
        if expected_rev is None:
            cur = c.execute(
                "UPDATE modules SET config_json = ?, updated_at = ?, rev = rev + 1"
                " WHERE id = ? AND session_id = ?",
                (config_json, now, module_id, session_id),
            )
        else:
            cur = c.execute(
                "UPDATE modules SET config_json = ?, updated_at = ?, rev = rev + 1"
                " WHERE id = ? AND session_id = ? AND rev = ?",
                (config_json, now, module_id, session_id, expected_rev),
            )
        if cur.rowcount == 0:
            row = c.execute(
                f"SELECT {_MOD_COLS} FROM modules WHERE id = ? AND session_id = ?",
                (module_id, session_id),
            ).fetchone()
            if row is None:
                return None
            current = _stored_from_row(row)
            if current is not None:
                raise RevConflict(current)
            return None
        _record_version(c, module_id, session_id, config_json, now)
        row = c.execute(
            f"SELECT {_MOD_COLS} FROM modules WHERE id = ?", (module_id,)
        ).fetchone()
    return _stored_from_row(row)
```

`schema.py`: `StoredModule` gains `rev: int = 0`; the PATCH request model (find it — `grep -n "class UpdateModuleRequest\|config: ModuleConfig" backend/src/schema.py`) gains `rev: int | None = None`.
`routes/modules.py` PATCH handler: pass `expected_rev=body.rev`, catch `db.RevConflict as e: raise HTTPException(status_code=409, detail={"conflict": e.current.model_dump(mode="json")})`. Internal writers that must win regardless (refine route, snapshot restore) keep `expected_rev=None` — refine-preserves-edits is Stage 2 (R-404).

- [ ] **Step 3: Frontend — send rev, resolve visibly**

`types.ts`: `rev: number` on `StoredModule`. `api.ts` `patchModule(id, config, rev?)` includes `rev` in the body. `moduleSaver.ts`: `Deps` gains `getRev(id): number | undefined` and `onConflict(current: StoredModule): void`; `save()` calls `deps.patch(id, config, deps.getRev(id))`; on `ApiError` with `status === 409`, call `onConflict(detail.conflict)` and drop the pending config (the user must see the newer version before re-editing — R-602 "resolve visibly"). `page.tsx`: `getRev` reads from the modules array; `onConflict` replaces the module in state and shows a toast: `"This module changed in another tab — showing the latest version."` Add a vitest case: patch rejects with a fake 409 → `onConflict` called once, no retry loop.

- [ ] **Step 4: Verify**

Run: `python -m pytest -q` → 0 failed. `cd frontend && npm test && npx tsc --noEmit && npm run build` → clean.
Manual two-tab AC: open the same module in two tabs, edit in both — the slower tab gets the toast + latest content; nothing vanishes silently.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: optimistic-concurrency revs on modules — stale writers get 409 + latest

R-602 AC (two tabs): conflict resolves visibly with a toast and reload, never
last-writer-wins. Refine stays unconditional pending R-404 (Stage 2).

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 11: Stage exit — coverage to gate, CI frontend job, full verification

**Files:**
- Modify: `.github/workflows/code-quality.yml` (frontend job), possibly new backend tests to clear the 80% branch gate (target the worst files: `llm.py` ~50%, `services/studio.py` ~56%, `routes/modules.py` ~57%)
- Test: everything

**Interfaces:**
- Consumes: all prior tasks.
- Produces: a green branch ready for the operator deploy checkpoint and Stage 2 planning.

- [ ] **Step 1: Coverage to the gate**

Run: `python -m pytest -q 2>&1 | tail -5` and read the TOTAL. If under 80%: add targeted tests for the uncovered branches listed in `--cov-report=term-missing` output, in priority order `llm.py` (provider resolution branches, cascade paths — much already covered by Task 3 tests), `routes/modules.py` (preview/insert/file-upload paths — partly covered by Tasks 3/5/6), `services/studio.py` (stub-mode generate/mine). Write real behavioral tests (request → assert response + persisted effect), not line-chasing asserts. Stop when `python -m pytest -q` exits 0 WITH the gate on.

- [ ] **Step 2: CI frontend job**

Append to `.github/workflows/code-quality.yml` (match the existing job style/indentation):

```yaml
  frontend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: frontend
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: npm
          cache-dependency-path: frontend/package-lock.json
      - run: npm ci
      - run: npx tsc --noEmit
      - run: npm test
      - run: npm run build
```

(ESLint stays out of the gate this stage — 42 pre-existing errors are Stage 2's R-1401 cleanup or an explicit retirement decision; note this in the commit body so it's a logged reason, not a zombie gate.)

- [ ] **Step 3: Full gate run (the R-1401 stage-exit evidence)**

```bash
python -m pytest -q          # 0 failed, coverage gate passes
mypy backend/src             # Success
ruff check backend/src && ruff format --check backend/src
cd frontend && npx tsc --noEmit && npm test && npm run build
```

All must pass. Record outputs in the commit body.

- [ ] **Step 4: Commit + hand off to review**

```bash
git add -A && git commit -m "chore: stage-1 exit — coverage gate green, frontend CI job

R-1401 stage-exit evidence in body. ESLint deferred to Stage 2 with logged reason.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

Then: REQUIRED SUB-SKILL `superpowers:requesting-code-review` on the whole branch diff before the operator checkpoint.

---

## Stage-Exit Checklist (maps to spec ACs — spec §0: stage exits only when these pass)

- [ ] **R-1103 AC:** 3 concurrent long generations; unrelated save/load/health each <1s P95 (`test_event_loop.py` + manual with stub sleep).
- [ ] **R-403 AC:** provider forced down → visibly-labeled fallback or honest failure; nothing degraded in any cache (`test_honesty.py`).
- [ ] **R-304 AC:** build/ask/refuse all surfaced distinctly; refine/insights no longer 500 on questions.
- [ ] **R-1105 AC:** corrupted row degrades only itself (`test_tolerant_reads.py`).
- [ ] **R-1201 AC:** "who used it yesterday" answerable from `/api/ops/summary`.
- [ ] **R-1202:** every generation records outcome/latency/tokens per owner.
- [ ] **R-1203 (logged partial):** backend errors reach the operator log ✓; the FRONTEND error path (error boundary + client-error report) is deliberately deferred to Stage 2 where it lands with the R-1101 reliability pass — this checklist line is the logged reason (spec §0 SHOULD-skip rule).
- [ ] **R-901 AC:** unauthenticated + forged-secret requests: no spend, no reads, no writes (`test_identity.py`, `test_prod_config.py`).
- [ ] **R-902 AC:** second device, one link-follow → same workspace.
- [ ] **R-903 AC:** cross-owner cache hit impossible (`test_identity.py`).
- [ ] **R-601/R-602 ACs:** two-tab, refine-during-edit (backend half), edit-then-drag, in-flight-edit — all resolve visibly, nothing silent (vitest + manual).
- [ ] **R-1401:** pytest+coverage gate, mypy, ruff, tsc, vitest, next build all green; dead scaffolding gone; single authoritative test config; ESLint deferral logged.
- [ ] **OPERATOR CHECKPOINT (R-906 buildout):** deploy backend (Fly/Railway/Render) + frontend (Vercel) using `deploy/README.md`; run the R-906 AC smoke test (invite link on a phone over cellular: entry → generate → reload). *Requires Janus's hosting accounts — schedule with him; not agent-executable.*
- [ ] Reconcile with the cloud-session PR if it has landed on `main` (compare per-area against these same ACs; keep the better implementation, document the choice).
- [ ] Write the Stage 2 plan (`superpowers:writing-plans`) against the post-Stage-1 codebase.
