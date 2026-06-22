"""Semantic generation cache + self-growing template library.

One mechanism, two wins:
  1. COST — a near-identical prompt returns a previously generated result with
     ZERO model tokens.
  2. REAL-TIME TEMPLATES — every successful generation is stored, so the SEED
     for the next request is the nearest PAST generation (RAG-style). The library
     grows on its own instead of being a fixed keyword list.

Embeddings default to a dependency-free hashing vector — good for spotting
near-duplicate intents with no model or heavy library. For deeper semantic
matching, set TRUS_EMBED_BASE_URL + TRUS_EMBED_MODEL to any OpenAI-compatible
/embeddings endpoint (e.g. Ollama `nomic-embed-text`).
"""

from __future__ import annotations

import json
import math
import os
import re
import urllib.error
import urllib.request

from src import db

_DIM = 512
_WORD = re.compile(r"[a-z0-9]+")


def enabled() -> bool:
    return os.environ.get("TRUS_CACHE", "on").strip().lower() not in ("off", "0", "false", "no")


def _exact_threshold() -> float:
    try:
        return float(os.environ.get("TRUS_CACHE_THRESHOLD", "0.93"))
    except ValueError:
        return 0.93


def _seed_threshold() -> float:
    try:
        return float(os.environ.get("TRUS_CACHE_SEED_THRESHOLD", "0.6"))
    except ValueError:
        return 0.6


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _fnv1a(s: str) -> int:
    """Deterministic 32-bit hash. Python's built-in hash() is per-process salted;
    embeddings are persisted and compared across restarts, so we need stability."""
    h = 0x811C9DC5
    for ch in s.encode("utf-8"):
        h ^= ch
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def _hash_embed(text: str) -> list[float]:
    """Hash word tokens + char trigrams into a fixed, L2-normalised vector."""
    vec = [0.0] * _DIM
    tokens = _WORD.findall(normalize(text))
    feats: list[str] = list(tokens)
    joined = " ".join(tokens)
    feats += [joined[i : i + 3] for i in range(max(0, len(joined) - 2))]
    if not feats:
        return vec
    for f in feats:
        h = _fnv1a(f)
        vec[h % _DIM] += 1.0 if ((h >> 16) & 1) else -1.0
    n = math.sqrt(sum(v * v for v in vec))
    return [v / n for v in vec] if n else vec


def _remote_embed(text: str) -> list[float] | None:
    base = os.environ.get("TRUS_EMBED_BASE_URL", "").strip().rstrip("/")
    model = os.environ.get("TRUS_EMBED_MODEL", "").strip()
    if not base or not model:
        return None
    body = json.dumps({"model": model, "input": text}).encode("utf-8")
    req = urllib.request.Request(base + "/embeddings", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    key = os.environ.get("TRUS_EMBED_API_KEY") or os.environ.get("TRUS_LLM_API_KEY")
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return payload["data"][0]["embedding"]
    except (urllib.error.URLError, OSError, KeyError, IndexError, json.JSONDecodeError):
        return None  # any failure → fall back to the local hashing embedding


def embed(text: str) -> list[float]:
    if os.environ.get("TRUS_EMBED_BASE_URL", "").strip():
        v = _remote_embed(text)
        if v:
            return v
    return _hash_embed(text)


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def lookup(kind: str, prompt: str) -> tuple[str | None, list | None]:
    """Return (mode, configs):
    "hit"  → reuse this result directly (zero model cost),
    "seed" → use it as the generation seed (still generate),
    None   → nothing close enough."""
    if not enabled():
        return (None, None)
    rows = db.cache_rows(kind)
    if not rows:
        return (None, None)
    norm = normalize(prompt)
    for r in rows:  # deterministic exact reuse first
        if r["norm"] == norm:
            db.cache_hit(r["id"])
            return ("hit", json.loads(r["configs_json"]))
    q = embed(prompt)
    best, best_sim = None, -1.0
    for r in rows:
        try:
            sim = _cosine(q, json.loads(r["embedding"]))
        except (json.JSONDecodeError, TypeError):
            continue
        if sim > best_sim:
            best, best_sim = r, sim
    if best is None:
        return (None, None)
    if best_sim >= _exact_threshold():
        db.cache_hit(best["id"])
        return ("hit", json.loads(best["configs_json"]))
    if best_sim >= _seed_threshold():
        return ("seed", json.loads(best["configs_json"]))
    return (None, None)


def store(kind: str, prompt: str, configs: list) -> None:
    """Remember a successful generation. Never let a cache write break a request."""
    if not enabled():
        return
    try:
        emb = embed(prompt)
        db.cache_add(kind, prompt, normalize(prompt), json.dumps(emb), json.dumps(configs))
    except Exception:  # pragma: no cover - cache is best-effort
        pass


def store_structured(kind: str, structured_text: str, prompt: str, configs: list) -> None:
    """Like store(), but embed a richer structured document (e.g. a screenshot
    capture's component inventory) while keeping `prompt` as the human-readable seed
    key. Gives nearest-neighbour seeding more discriminative signal than the bare
    prompt. Best-effort — never breaks the caller."""
    if not enabled():
        return
    try:
        emb = embed(structured_text or prompt)
        db.cache_add(kind, prompt, normalize(prompt), json.dumps(emb), json.dumps(configs))
    except Exception:  # pragma: no cover - cache is best-effort
        pass
