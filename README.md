# Trus

> An AI‑orchestrated personal operating system: describe what you need to organize, and Trus shapes the exact tool for it — live, on an infinite canvas.

**North star:** the exact tool you need, in the shape of your life, for the cost of a sentence — and you stay in the driver's seat the entire time.

Type *"track my marathon training"* and Trus builds a training log, a mileage chart, and a calendar — not a generic template, a tool fitted to your words. Everything it makes is editable, draggable, and yours.

---

## How it works

Trus's AI **never writes UI code.** The backend orchestrates an LLM to emit a **`ModuleConfig`** — a small JSON document — and the frontend renders it with a **trusted component library** of ~30 building blocks (tables, charts, kanban boards, habit trackers, gauges, calendars, …). That keeps generation cheap, safe, and instant — and means even a small *local* model can do the job.

```
You ──prompt──▶  Backend (FastAPI) ──▶ LLM orchestrator ──▶ ModuleConfig (JSON)
                                                                  │
                        Infinite canvas (Next.js)  ◀──renders─────┘
```

### Highlights
- **Infinite canvas** — pan/zoom, drag, resize, minimap, full‑page module view.
- **~30 component types** — text, number, slider, checkbox, list, table, chart, kanban, heatmap, gauge, ring, calendar, timeline, rating, KPI, multi‑subject tracker, and more.
- **Multi‑tool decomposition** — *"plan my Japan trip"* becomes a coordinated set (itinerary + budget + packing list + to‑dos).
- **Refine with AI**, a per‑module inspector, snapshots, pages, and undo/history.
- **Pluggable model backend** — run a **free local** open‑source model, a cheap hosted endpoint, or Google Gemini. Switching is config, not code.
- **Self‑growing templates + semantic cache** — repeated prompts are reused for free; every generation improves the seed for the next.

## Tech stack
- **Backend:** Python 3.11+, FastAPI, SQLite (stdlib), a zero‑dependency model‑provider layer.
- **Frontend:** Next.js 16, React 19, TypeScript 5, Tailwind CSS v4.

---

## Quickstart

### Prerequisites
- Python 3.11+
- Node.js 20+
- *(Recommended)* [Ollama](https://ollama.com) — to run generation locally for free (see below).

### 1. Backend
```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn src.main:app --reload          # → http://localhost:8000
```

### 2. Frontend
```bash
cd frontend
npm install
npm run dev                            # → http://localhost:3000
```

Open **http://localhost:3000**. With no model configured, Trus runs in **offline "stub" mode** — it serves built‑in keyword templates so you can explore the UI with no key and no network. For real AI generation, pick a model backend below.

---

## Choosing a model backend

Generation funnels through one seam, selected by environment variables (see [`.env.example`](.env.example)). Pick one:

| Backend | What it is | Cost |
|---|---|---|
| **Local** — Ollama / llama.cpp / vLLM / LM Studio | an open‑source model on your machine | **free** |
| **Hosted open model** — Together · Fireworks · Groq · DeepInfra · OpenRouter | OpenAI‑compatible API | pennies (often a free tier) |
| **Google Gemini** | the original cloud path | cheap on a Lite tier |
| **Stub** | offline keyword templates | free, no AI |

> Because the model only ever emits a small JSON config, a 4B local model is plenty. **Local is recommended** — free, private, and works offline.

---

## Run generation locally with Ollama (recommended — free)

[Ollama](https://ollama.com) runs open‑source models on your own machine and exposes an OpenAI‑compatible API that Trus speaks natively.

### Fastest — one command (macOS / Linux)
From the repo root:
```bash
make ollama-setup      # install Ollama, start it, pull a model, wire .env, smoke-test
make dev-local         # run the backend against the local model
make verify-local      # confirm which backend is active
```
Then start the frontend (`cd frontend && npm run dev`) and open http://localhost:3000. Every generation now runs on your GPU — **$0 per call.** `make ollama-setup` is safe to re‑run.

### Manual setup (any OS)

1. **Install Ollama**
   - **macOS:** `brew install ollama` (or download from [ollama.com](https://ollama.com))
   - **Linux:** `curl -fsSL https://ollama.com/install.sh | sh`
   - **Windows:** download the installer from [ollama.com](https://ollama.com)

2. **Start the server** (skip if the Ollama app/service is already running)
   ```bash
   ollama serve          # serves on http://localhost:11434
   ```

3. **Pull a model**
   ```bash
   ollama pull qwen3:4b-instruct-2507-q4_K_M   # ~2.5 GB, Apache-2.0, runs on a 16 GB machine
   ```

4. **Point Trus at it** — put these in **`backend/.env`**
   > ⚠️ Use `backend/.env`, **not** the repo‑root `.env`. python‑dotenv loads the `.env`
   > nearest to `backend/`, so `backend/.env` is the file that actually takes effect.
   > (`make ollama-setup` handles this for you.)
   ```ini
   TRUS_LLM_PROVIDER=openai
   TRUS_LLM_BASE_URL=http://localhost:11434/v1
   TRUS_LLM_MODEL=qwen3:4b-instruct-2507-q4_K_M
   ```

5. **Restart the backend**, then verify
   ```bash
   curl http://localhost:8000/api/llm/status
   # → {"provider":"openai","model":"qwen3:4b-instruct-2507-q4_K_M", ...}
   ```

**Model choices:** `qwen3:4b-instruct-2507-q4_K_M` (default, ~16 GB RAM) · `qwen2.5:7b-instruct` (alternative) · `qwen3:30b-a3b-instruct-2507` (stronger; ~32 GB RAM or a GPU box). Any OpenAI‑compatible server works — point `TRUS_LLM_BASE_URL` at llama.cpp, vLLM, LM Studio, or a hosted endpoint instead.

**Robustness:** if the local server is down, Trus automatically falls back to Gemini (when a key is set) and then to offline templates, so it never hard‑fails.

**Keep it running** (macOS): `brew services start ollama` launches Ollama at login. Note that Ollama unloads an idle model after ~5 minutes, so the first request after a pause has a brief warm‑up.

---

## Other backends

**Hosted open model** (e.g. Groq — often free at low volume) in `backend/.env`:
```ini
TRUS_LLM_PROVIDER=openai
TRUS_LLM_BASE_URL=https://api.groq.com/openai/v1
TRUS_LLM_MODEL=llama-3.1-8b-instant
TRUS_LLM_API_KEY=your_key
```

**Google Gemini** in `backend/.env`:
```ini
GEMINI_API_KEY=your_key
GEMINI_MODEL=gemini-3.1-flash-lite      # pin a cheap, current tier
```

Full configuration reference and a cost/feasibility writeup live in
[`.env.example`](.env.example), [`docs/llm-providers-and-cost.md`](docs/llm-providers-and-cost.md), and [`docs/llm-research-report.md`](docs/llm-research-report.md).

---

## Real‑time templates & cost cache

Instead of a fixed template list, Trus embeds each prompt and:
- **reuses** an (almost) identical past result with **zero model tokens**, and
- **seeds** new generations from the nearest past result, so the library grows with use.

Embeddings are dependency‑free by default; set `TRUS_EMBED_BASE_URL` / `TRUS_EMBED_MODEL` to any OpenAI‑compatible embeddings endpoint for deeper matching. Toggle the whole thing with `TRUS_CACHE`.

---

## Project layout

```
backend/
  src/
    main.py                  FastAPI app, routes, GET /api/llm/status
    llm.py                   provider abstraction (gemini | openai-compatible | stub)
    semantic_cache.py        embed + reuse/seed generations (growing templates)
    services/orchestrator.py prompt → ModuleConfig (seed → validate → retry → cascade)
    schema.py                ModuleConfig + ~30 component types (Pydantic)
    db.py                    SQLite (stdlib)
    routes/                  modules · pages · conversations
  tests/                     pytest
frontend/
  src/
    app/                     Next.js App Router
    components/              Canvas · Module · Inspector · primitives/ (component library)
    lib/                     API client · types · theme
scripts/                     setup-ollama.sh · run-local.sh · verify-local.sh
docs/                        LLM provider + cost documentation
Makefile                     make ollama-setup / dev-local / verify-local / …
```

## Make targets

```
make ollama-setup    Install Ollama, pull a model, wire backend/.env, smoke-test (re-runnable)
make dev-local       Run the backend against the local Ollama model
make verify-local    Show Ollama + backend status
make ollama-serve    Start the Ollama server in the background
make ollama-stop     Stop it
make frontend        Run the Next.js frontend
```

## Testing

Test dependencies live in `backend/requirements-dev.txt` (which pulls in the runtime `requirements.txt` too):

```bash
cd backend && pip install -r requirements-dev.txt   # once — runtime + test deps
cd backend && pytest -q              # backend test suite
cd frontend && npx tsc --noEmit      # frontend type-check
```

---

## Design principle

The orchestrator returns a **`ModuleConfig` — never HTML, CSS, or JavaScript.** The frontend renders that config with a fixed, trusted component library. This is what makes generation **cheap** (small structured output), **safe** (no arbitrary code), **portable** (any model that can emit JSON works — local or cloud), and **instantly editable** (it's just data).
