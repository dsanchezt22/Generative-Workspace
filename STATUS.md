# Trus — Project Status

_An AI-orchestrated personal operating system: describe what you want to organize, and the system generates the exact tool for it._

**Last updated:** 2026-07-03
**Repo:** https://github.com/dsanchezt22/Generative-Workspace
**Branch state:** Stage 2b complete at `ab6e67c` on `stage2b/inputs`, stacked on `stage2a/reliability` (still unmerged, pending the user's call). Both stages are ahead of `main`; final whole-branch review and merge decision remain open.

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

## Stage 2b — input surfaces (shipped)

Ships the brief's must-have input story — entry-as-interview, voice rambling, sketch-to-module, and the prescriptive idea-generation package:

- **R-101/R-104/R-105 — entry-as-interview front door:** `IntroSplash`'s decorative overlay replaced with a true pre-workspace entry (rotating "Tell me what's on your mind" headline, a large mic affordance as the primary control, a text field as the visible secondary), shown on a first-visit-empty-workspace session or via EmptyState re-entry; dissolves to canvas on submit, Escape/Skip dismisses, keyboard-reachable (`role="dialog"`, focus starts on the text field).
- **R-201-204 — voice rambling:** new pluggable `POST /api/transcribe` (`TRUS_STT_*` env, OpenAI-compatible `/v1/audio/transcriptions`; unset → honest 422) + a PromptBar mic rework — press-to-start/stop recording, transcript appends into the input (never overwrites), Web Speech interim text as live garnish only, mic-denial degrades to typing without breaking the flow.
- **R-221-223 — sketch overlay → snap:** canvas toolbar Sketch toggle (world-coordinate stroke overlay: pen/eraser/clear), "Snap to modules" rasterizes the sketch and routes it through the existing file-upload vision path with a sketch-tuned hint; overlay clears on success or cancel (ephemeral, R-223).
- **R-102/R-103/R-301 — proposal plans + multi-turn interview:** proposals now carry a one-paragraph `plan` (rendered above the preview stack); the clarifying-question exchange moved server-side (`GenerateRequest.exchange`, hard-capped at 4 answered questions) — fixes the earlier answer-drop bug where PromptBar string-concatenated only the latest answer, and interview-specialized results no longer seed the shared prompt cache.
- **R-302 — conversation context:** the owner's last ~10 messages on the current page feed generation context (not the grounded-file path, and never when there's no page scope); the semantic-cache key stays the raw prompt, so an identical re-prompt still hits.
- **R-104 — per-owner suggestions:** `GET /api/suggestions` — usage-seeded chips drawn from this owner's `gen_cache`/`messages`, R-903-scoped (cross-owner isolation is test-pinned, and reconfirmed in this task's own smoke run below).
- Stage-2a triaged backlog closed alongside: CORS origin-parsing single-sourced into `routes/deps.py`, one `_gemini_model()` helper replacing three copies, `nosemgrep` comments scoped to rule ids, SSRF guard now also checks `is_global` (CGNAT) and refuses redirects, a route-level prod test for `/api/llm/status`.

New env: `TRUS_STT_BASE_URL` / `TRUS_STT_MODEL` / `TRUS_STT_API_KEY` (all optional — absent means voice transcription is an honest 422, never a silent failure). Documented in `.env.example`, the conftest isolation list, and `deploy/README.md`'s env table.

## Current gates (this run, 2026-07-03, HEAD `ab6e67c`)

| Gate | Result |
|---|---|
| `python -m pytest -q` (repo root, coverage gate on) | **440 passed, 2 skipped**, 94.27% branch coverage (gate: 80%) |
| `mypy backend/src` | clean, 29 source files |
| `ruff check backend/src` | all checks passed |
| `ruff format --check backend/src` | 29 files already formatted |
| `cd frontend && npm test` | 5 test files, **49 passed** |
| `npx tsc --noEmit` | clean |
| `npm run build` | clean production build (4 static routes) |

API-level smoke against a fresh local instance on a spare port (claim flow for two users, `/api/transcribe` unset-config 422 + non-audio-mime 422, `/api/suggestions` empty→populated→cross-owner-isolated, a 2-turn interview exchange on `/api/modules/preview`, `/api/modules/generate_from_file` with a `hint` field on an image and a `.txt` — both honestly refuse in pure stub mode, per the already-pinned `test_generate_from_file_stub_provider_txt_without_live_model_refuses`, gated `/api/ops/summary` with `users[]` present) — all passed; transcript in `.superpowers/sdd/stage2b-task-9-report.md`.

## Docs

- `docs/MVP-SPEC.md` — the requirements contract (R-IDs cited in commits).
- `docs/MVP-GAP-AUDIT.md` — the audit that drove Stage 1's structural findings.
- `docs/superpowers/plans/` — the Stage 1, Stage 2a, and Stage 2b implementation plans, task-by-task.
- `deploy/README.md` — hosting (Fly + Vercel), env contract, invite provisioning, post-deploy smoke test.

## Next

**Stage 3 (differentiators):** spatial nesting (R-500), live data (R-700), profile (R-800).
