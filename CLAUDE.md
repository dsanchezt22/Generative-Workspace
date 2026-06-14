# Trus

An AI-orchestrated personal operating system. Backend orchestrates Gemini to emit `ModuleConfig` JSON; the frontend renders that config with a trusted component library on an infinite canvas.

## Stack

- **Backend**: Python 3.11+, FastAPI, SQLite (stdlib), `google-genai` SDK
- **Frontend**: Next.js + TypeScript, Tailwind
- **Testing**: pytest + pytest-cov (backend)
- **Env**: `.env` at repo root — never commit it

## Project Layout

```
backend/
  src/        ← all application code (import as `src.*`)
  tests/      ← pytest test files
  requirements.txt
frontend/
  app/        ← Next.js App Router pages
  components/ ← module renderer + primitive component library
  lib/        ← API client, types
  package.json
```

## Common Commands

```bash
# Backend
cd backend && pip install -r requirements.txt
cd backend && uvicorn src.main:app --reload   # http://localhost:8000

# Tests (backend)
cd backend && pytest --cov=src --cov-report=term-missing -q

# Coverage number only (used by AutoResearch Verify)
cd backend && python -m pytest --cov=src --cov-report=term-missing -q 2>/dev/null | grep TOTAL | awk '{print $4}' | tr -d '%'

# Frontend
cd frontend && npm install && npm run dev     # http://localhost:3000
```

## AutoResearch Configuration

Use these primitives when invoking `/autoresearch`:

```
Goal:    Improve backend test coverage for src/
Metric:  % lines covered (higher is better)
Scope:   backend/src/**/*.py backend/tests/**/*.py
Verify:  cd backend && python -m pytest --cov=src --cov-report=term-missing -q 2>/dev/null | grep TOTAL | awk '{print $4}' | tr -d '%'
Guard:   cd backend && python -m pytest -q 2>/dev/null && echo "passed"
```

## Conventions

- All backend modules live under `backend/src/` and are importable as `src.<module>`
- Tests mirror the src structure: `tests/test_<module>.py`
- Gemini calls go through `src/llm.py` — never call `google.genai` directly from route handlers
- Use `python-dotenv` to load env vars; never hardcode API keys
- FastAPI routes live in `src/routes/`; business logic in `src/services/`
- The orchestrator returns a `ModuleConfig` (Pydantic) — never raw HTML/CSS/JS. The frontend renders that config via a trusted component library.
- Frontend uses the Next.js App Router. Components are server-rendered by default; mark interactive pieces with `"use client"`.

# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.
