# LESSONS — V2 build scratchpad

One lesson per entry, one-line summary first. Real component-tree facts, corrections,
confirmed approaches and why. Read before big moves. Don't duplicate what the repo
already records (STATUS.md, plans, CLAUDE.md).

---

- **Toolchain on this machine lives outside PATH defaults.** System python is 3.9;
  the project venv is `.venv/` (Python 3.12 via `uv venv`), created 2026-07-06 —
  run gates as `.venv/bin/python -m pytest -q` etc. mypy+ruff are installed in the
  venv but NOT in requirements-dev.txt (matches CI-less local setup). Frontend needs
  `npm install` after fresh clone (vitest is a devDependency).

- **`.env*` files are permission-blocked for agents in this session.** Don't try to
  read them; probe the running server's `/api/llm/status` instead to learn the
  active provider.

- **The existing `ModuleConfig.automations` is a client-side intra-module rule
  engine** (checked→increment/flag). The V2 always-on runtime is a separate
  server-side concept — never overload the old field.

- **Env knobs must be read fresh per call** (function, not module constant) or
  conftest's `_isolate_llm_env` can't isolate them per test; add every new
  `TRUS_*` knob to that delenv list (backend/tests/conftest.py:42).

- **Injectable time, never sleeps:** the `_RateLimiter.allow(now=...)` pattern
  (routes/deps.py:41) is the house style for testing time-dependent code; the V2
  scheduler must take an injectable clock the same way.

- **Scheduler-thread DB safety is already there:** db.py's per-call `_conn()`
  (WAL + busy_timeout 5000) is thread-safe as-is; multi-step atomic work stays on
  ONE `_conn()` (restore_snapshot is the canonical pattern).

- **Portal tiles paint below modules and auto-place on a shelf at y ≤ -168** so
  they never collide with the module grid (origin 32,96). Keep any portal visual
  upgrade inside the same world-transform layer.

- **`animate-slide-right` creates a transform containing block** — fixed-position
  children (ConfirmDialog) of a sliding panel must be siblings/portals, never
  nested (ArchivedPanel.tsx:32).

- **Zoom clamp [0.3, 2] is duplicated** in Canvas.tsx:166 AND lib/viewPersist.ts:21
  — change both or neither.
