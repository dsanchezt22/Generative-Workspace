# Trus — Project Status

_An AI-orchestrated personal operating system: describe what you want to organize, and the system generates the exact tool for it._

**Last updated:** 2026-07-03
**Repo:** https://github.com/dsanchezt22/Generative-Workspace
**Branch state:** Stage 2a complete at `b80d9c3` on `stage2a/reliability` (15 commits ahead of `main`), pending final whole-branch review and merge decision.

---

## Architecture (the one decision everything rests on)

The AI **never generates UI code**. The orchestrator turns a prompt into a typed
`ModuleConfig` (JSON: which components, how they bind, what's prefilled), and the
frontend renders that config with a fixed, trusted component library. This keeps
output instant, consistent, and impossible to break into "malformed HTML."

```
prompt ──▶ Gemini (orchestrator) ──▶ ModuleConfig (JSON) ──▶ trusted components ──▶ canvas
```

- **Backend:** Python 3.12 (Docker) · FastAPI · SQLite (stdlib) · `google-genai`
- **Frontend:** Next.js 16 · React 19 · TypeScript · Tailwind v4

## Stage 1 — structural blockers (shipped)

Closed the 7 cross-cutting findings from `docs/MVP-GAP-AUDIT.md` that stood between a local demo and a hostable 50-user alpha:

1. **One shared trust domain** → invite-claim identity (`users` table, session `uid`), per-owner scoping of the generation cache and layout library.
2. **Event loop blocked on every model call** → LLM/vision calls moved off the async event loop; one generation no longer freezes health checks and saves for every user.
3. **Silent degradation everywhere** → honest refusal on unreadable input, degraded/cascade output never cached or persisted as a fake success.
4. **No schema versioning for persisted configs** → tolerant reads; one corrupt row quarantines itself instead of 500ing the whole workspace.
5. **Zero observability** → structured logging, per-generation telemetry (`gen_events`), operator summary endpoint.
6. **Data-loss races in the client** → single-writer module saves, rev-based optimistic-concurrency conflict detection across tabs.
7. **Quality gates red at HEAD** → green baseline restored, coverage gate reconciled and raised, frontend test/CI job added.

## Stage 2a — reliability completions (shipped)

Landed the two security decisions from the Stage 1 final review plus the triaged backlog:

- **Security decision A:** Origin gate on state-changing multipart endpoints (upload/import/capture) — closes the `SameSite=None` cross-site CSRF vector.
- **Security decision B:** SSRF guard on studio `image_url` — refuses private/loopback/link-local/metadata targets and redirect bypasses; URL import off by default in prod.
- **R-1102:** destructive actions confirmed or undoable — page delete shows a typed module-count confirm, module removal is archive-first (restorable), permanent delete is confirmed; snapshot restore is now one atomic transaction that preserves module ids (cross-module bindings survive a restore).
- **R-211:** documents ground on every provider, not just Gemini's native multimodal path — server-side text extraction (`pypdf` + plain-text decode) feeds the normal generation path ahead of the honest-refusal fallback.
- **R-1201/R-1202:** telemetry completions — file-upload generations carry real provenance (provider/model), ops summary reports per-user last-seen, `/api/llm/status` is trimmed in prod.
- **R-602/R-1101 backlog:** saver hardening — 404 responses are treated as "forgotten" (no retry loop), `beforeunload` does a best-effort keepalive flush of pending edits, module commits use functional updates (no same-tick stale-closure class), the degraded-generation notice moved off the error-red channel.
- Small-backlog batch: studio layout rows quarantine on parse failure instead of breaking the list; `requirements.txt` (runtime) split from `requirements-dev.txt` (test tooling) so the Docker image doesn't bundle pytest.

## Current gates (this run, 2026-07-03, HEAD `b80d9c3`)

| Gate | Result |
|---|---|
| `python -m pytest -q` (repo root, coverage gate on) | **359 passed, 2 skipped**, 94.22% branch coverage (gate: 80%) |
| `mypy backend/src` | clean, 27 source files |
| `ruff check backend/src` | all checks passed |
| `ruff format --check backend/src` | 27 files already formatted |
| `cd frontend && npm test` | 1 test file, **11 passed** |
| `npx tsc --noEmit` | clean |
| `npm run build` | clean production build (4 static routes) |

API-level smoke against a fresh local instance (claim flow, preview→insert, PATCH stale-rev 409 shape, atomic id-preserving snapshot restore, `.txt` grounded upload, `.bin` honest refusal, gated ops summary with per-user `last-seen`) — all passed; transcript in `.superpowers/sdd/stage2a-task-9-report.md`.

## Docs

- `docs/MVP-SPEC.md` — the requirements contract (R-IDs cited in commits).
- `docs/MVP-GAP-AUDIT.md` — the audit that drove Stage 1's structural findings.
- `docs/superpowers/plans/` — the Stage 1 and Stage 2a implementation plans, task-by-task.
- `deploy/README.md` — hosting (Fly + Vercel), env contract, invite provisioning, post-deploy smoke test.

## Next

**Stage 2b: entry-as-interview, voice, sketch** (R-100, R-200 input surfaces, R-301–305) — builds on a now-finished reliability story. Plan to be written against the post-2a codebase.
