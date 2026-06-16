# LLM providers, cost, and real-time templates

Trus turns a prompt into a `ModuleConfig` via **one seam** — `generate()` /
`generate_from_file()` in `backend/src/llm.py`. Behind that seam are three
backends, chosen by environment variables. **Switching is config, not code.**

| Provider | What it is | Cost |
|---|---|---|
| `openai` | Any OpenAI-compatible `/chat/completions` — a **local** open model (Ollama, llama.cpp, vLLM, LM Studio) **or** a cheap hosted endpoint (Together, Fireworks, Groq, DeepInfra, OpenRouter) | $0 local · pennies hosted |
| `gemini` | Google Gemini (the original cloud path) | cheap if you pin a Lite tier |
| `stub` | Offline keyword templates — no key, no network | free |

Auto-detection (no `TRUS_LLM_PROVIDER` set): a `TRUS_LLM_BASE_URL` → `openai`;
a real `GEMINI_API_KEY` → `gemini`; otherwise `stub`.

See `.env.example` for every variable.

---

## Option A — Free local model (recommended)

**Fastest — one command** (installs Ollama, starts it, pulls a model, wires
`.env`, smoke-tests; safe to re-run):

```bash
make ollama-setup        # → then `make dev-local` to run the backend against it
```

Or do it by hand on macOS / Windows / Linux with [Ollama](https://ollama.com):

```bash
brew install ollama                       # or download the installer
ollama pull qwen3:4b-instruct-2507-q4_K_M # ~2.5 GB, Apache-2.0, runs on a 16 GB Mac
```

Then in `.env`:

```ini
TRUS_LLM_PROVIDER=openai
TRUS_LLM_BASE_URL=http://localhost:11434/v1
TRUS_LLM_MODEL=qwen3:4b-instruct-2507-q4_K_M
```

Restart the backend and confirm: `curl localhost:8000/api/llm/status` →
`{"provider":"openai","model":"qwen3:4b-instruct-2507-q4_K_M", ...}`.

- **Bigger/better** (32 GB+ Mac or a GPU box): `qwen3:30b-a3b-instruct-2507-q4_K_M`
  (MoE — ~3.3B active params, so ~30B quality at small-model speed).
- **External GPU**: run vLLM/llama.cpp on a rented box (RunPod serverless RTX 4090
  is per-second, ~$0 idle) and point `TRUS_LLM_BASE_URL` at it. Same provider.
- **Validity**: output is Pydantic-validated with one automatic retry. For stricter
  decoding on vLLM/llama.cpp/recent Ollama, set `TRUS_LLM_JSON_MODE=schema`.
- **Quality**: a 4–8B local model is modestly behind Gemini on *semantic* choices
  (which component fits the intent). Two things close most of the gap: every call
  is **seeded** with the nearest template, and a **cascade** falls back to Gemini
  (if a key is set) then templates when the local endpoint is unreachable.

## Option B — Cheap hosted open model

Any OpenAI-compatible host, e.g. Groq (often free at this volume):

```ini
TRUS_LLM_PROVIDER=openai
TRUS_LLM_BASE_URL=https://api.groq.com/openai/v1
TRUS_LLM_MODEL=llama-3.1-8b-instant
TRUS_LLM_API_KEY=your_key
```

At ~2,000 generations/month every hosted open-model option is **single-digit
dollars or free**. Optimize for reliable JSON + a clean swap, not cheapest token.

## Option C — Gemini, but cheaper

```ini
GEMINI_API_KEY=your_key
GEMINI_MODEL=gemini-3.1-flash-lite     # ~5–20x cheaper than the drifting "flash-latest" alias
# TRUS_LLM_MAX_OUTPUT_TOKENS=1536      # optional; output is ~4x input price
```

> ⚠️ Do **not** pin `gemini-2.5-flash-lite` — it is scheduled for shutdown
> (2026-07-22). Use a current 3.x Lite tier. Implicit prompt caching (automatic
> on 2.5/3.x) already discounts the repeated ~1.5–2k-token system prompt for free,
> so explicit caching and the Batch API aren't worth the complexity here.

---

## Real-time templates (self-growing library)

The old keyword library is now a *fallback seed*, not the ceiling. A semantic
cache (`backend/src/semantic_cache.py` + the `gen_cache` table) does two things at
once:

1. **Cost** — an (almost) identical past prompt returns a stored result with
   **zero model tokens** (proven live: a repeated prompt makes no model call).
2. **Real-time growth** — every successful generation is stored, so the seed for
   the next request is the nearest *past* result, and the library improves with use.

Embeddings are **dependency-free by default** (a deterministic hashing vector —
good for near-duplicate detection, no model or heavy library). For deeper semantic
matching, point it at any OpenAI-compatible embeddings endpoint:

```ini
TRUS_EMBED_BASE_URL=http://localhost:11434/v1
TRUS_EMBED_MODEL=nomic-embed-text
# TRUS_CACHE_THRESHOLD=0.93       # reuse a prior result for free at/above this similarity
# TRUS_CACHE_SEED_THRESHOLD=0.6   # use a prior result as the seed at/above this
# TRUS_CACHE=off                  # disable entirely
```

**Scraping productivity apps was evaluated and rejected** — it violates those
apps' terms, their formats don't map to Trus's component model (each would need
costly LLM re-translation), and scrapers are brittle. The self-growing cache
delivers the "real-time templates" goal without those problems.

---

## How robust is it?

`openai` (local) → **cascade** → `gemini` (if a key is set) → `stub` templates.
So a stopped Ollama, a quota error, or being fully offline all degrade gracefully
instead of failing the request. Toggle with `TRUS_LLM_CASCADE=off`.

Full design rationale, current pricing, and the feasibility/appropriateness table
are in [`llm-research-report.md`](./llm-research-report.md).
