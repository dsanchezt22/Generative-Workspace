# Generative-Workspace

Full-stack AI workspace app. Python (FastAPI) backend with Gemini/Vertex AI; React frontend.

## Stack

- **Backend**: Python 3.11+, FastAPI, Google Generative AI SDK (`google-generativeai`)
- **Frontend**: React (JS), Vite
- **Testing**: pytest + pytest-cov (backend), Vitest (frontend)
- **Env**: `.env` at repo root — never commit it

## Project Layout

```
backend/
  src/        ← all application code (import as `src.*`)
  tests/      ← pytest test files
  requirements.txt
frontend/
  src/        ← React components and pages
  package.json
```

## Common Commands

```bash
# Backend
cd backend && pip install -r requirements.txt
cd backend && uvicorn src.main:app --reload

# Tests (backend)
cd backend && pytest --cov=src --cov-report=term-missing -q

# Coverage number only (used by AutoResearch Verify)
cd backend && python -m pytest --cov=src --cov-report=term-missing -q 2>/dev/null | grep TOTAL | awk '{print $4}' | tr -d '%'

# Frontend
cd frontend && npm install && npm run dev
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
- Gemini calls go through `src/llm.py` — never call `google.generativeai` directly from route handlers
- Use `python-dotenv` to load env vars; never hardcode API keys
- FastAPI routes live in `src/routes/`; business logic in `src/services/`
