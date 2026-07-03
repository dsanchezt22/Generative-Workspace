"""Tests for the semantic cache / self-growing template library."""

import json
import math

from src import llm
from src import semantic_cache as sc

from tests.conftest import gen_result

_VARS = (
    "TRUS_CACHE",
    "TRUS_CACHE_THRESHOLD",
    "TRUS_CACHE_SEED_THRESHOLD",
    "TRUS_EMBED_BASE_URL",
    "TRUS_EMBED_MODEL",
    "TRUS_EMBED_API_KEY",
)


def _clear(monkeypatch):
    for k in _VARS:
        monkeypatch.delenv(k, raising=False)


def test_embed_deterministic_and_case_insensitive(monkeypatch):
    _clear(monkeypatch)
    a = sc.embed("Track My Workouts")
    b = sc.embed("track my workouts")
    assert a == b  # normalise lowercases
    assert sc.embed("hello world") == sc.embed("hello world")  # stable across calls
    n = math.sqrt(sum(x * x for x in a))
    assert abs(n - 1.0) < 1e-6  # L2-normalised


def test_store_and_exact_hit(monkeypatch):
    _clear(monkeypatch)
    cfgs = [{"title": "Budget", "components": [{"id": "x", "type": "kpi", "label": "Total"}]}]
    sc.store("system", "a monthly budget", cfgs)
    mode, got = sc.lookup("system", "A Monthly Budget")  # case-insensitive exact
    assert mode == "hit"
    assert got == cfgs


def test_miss_returns_none(monkeypatch):
    _clear(monkeypatch)
    sc.store("system", "alpha beta gamma", [{"title": "A", "components": []}])
    mode, got = sc.lookup("system", "zeta eta theta iota kappa")
    assert mode is None and got is None


def test_seed_mode_on_partial_overlap(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TRUS_CACHE_THRESHOLD", "0.999")  # too high to count as a direct hit
    monkeypatch.setenv("TRUS_CACHE_SEED_THRESHOLD", "0.05")
    seed_cfg = [{"title": "A", "components": []}]
    sc.store("system", "alpha beta gamma", seed_cfg)
    mode, got = sc.lookup("system", "alpha beta delta")  # 2/3 tokens shared
    assert mode == "seed"
    assert got == seed_cfg


def test_disabled_short_circuits(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TRUS_CACHE", "off")
    sc.store("system", "a budget", [{"title": "A", "components": []}])
    mode, _ = sc.lookup("system", "a budget")
    assert mode is None


def test_kinds_are_isolated(monkeypatch):
    _clear(monkeypatch)
    sc.store("single", "a budget", [{"title": "Single", "components": []}])
    mode, _ = sc.lookup("system", "a budget")  # different kind → no hit
    assert mode is None


def test_disabled_short_circuits_store_too(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TRUS_CACHE", "off")
    from src import db

    sc.store("system", "off cache write", [{"title": "A", "components": []}])
    assert db.cache_stats()["entries"] == 0  # store() never touched the db


def test_hash_embed_empty_text_returns_zero_vector(monkeypatch):
    _clear(monkeypatch)
    assert sc._hash_embed("   ") == [0.0] * sc._DIM
    assert sc._hash_embed("") == [0.0] * sc._DIM


def test_cosine_guards_mismatched_or_empty_vectors():
    assert sc._cosine([], [1.0]) == 0.0
    assert sc._cosine([1.0], []) == 0.0
    assert sc._cosine([1.0, 0.0], [1.0]) == 0.0  # length mismatch


def test_threshold_env_parsing_falls_back_on_bad_value(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TRUS_CACHE_THRESHOLD", "not-a-number")
    assert sc._exact_threshold() == 0.93
    monkeypatch.setenv("TRUS_CACHE_SEED_THRESHOLD", "not-a-number")
    assert sc._seed_threshold() == 0.6


def test_remote_embed_used_when_configured(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TRUS_EMBED_BASE_URL", "http://h/v1")
    monkeypatch.setenv("TRUS_EMBED_MODEL", "nomic-embed-text")
    monkeypatch.setenv("TRUS_EMBED_API_KEY", "k-embed")
    captured = {}

    class _FakeResp:
        def read(self):
            import json as _json

            return _json.dumps({"data": [{"embedding": [0.1, 0.2, 0.3]}]}).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["auth"] = req.get_header("Authorization")
        return _FakeResp()

    monkeypatch.setattr(sc.urllib.request, "urlopen", fake_urlopen)
    vec = sc.embed("a remote-embedded prompt")
    assert vec == [0.1, 0.2, 0.3]
    assert captured["url"] == "http://h/v1/embeddings"
    assert captured["auth"] == "Bearer k-embed"


def test_remote_embed_falls_back_to_hash_on_failure(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TRUS_EMBED_BASE_URL", "http://h/v1")
    monkeypatch.setenv("TRUS_EMBED_MODEL", "nomic-embed-text")

    def boom(req, timeout=None):
        raise OSError("refused")

    monkeypatch.setattr(sc.urllib.request, "urlopen", boom)
    vec = sc.embed("hello world")
    assert vec == sc._hash_embed("hello world")  # fell back to the local embedding


def test_remote_embed_returns_none_when_not_configured(monkeypatch):
    _clear(monkeypatch)
    assert sc._remote_embed("anything") is None


def test_lookup_embed_based_hit_when_norm_differs_but_vectors_match(monkeypatch):
    """Two prompts that normalise differently but embed identically still count
    as a cache hit through the cosine-similarity path (not the exact-norm path)."""
    _clear(monkeypatch)
    monkeypatch.setattr(sc, "embed", lambda text: [1.0, 0.0])
    cfgs = [{"title": "Same Vector", "components": []}]
    sc.store("system", "alpha prompt", cfgs)
    mode, got = sc.lookup("system", "totally different wording")
    assert mode == "hit"
    assert got == cfgs


def test_generate_modules_cache_hit_skips_model(monkeypatch):
    """A repeated prompt is served from cache without calling the model again —
    this is both the cost win and the real-time-template mechanism."""
    from src.services import orchestrator

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("TRUS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("TRUS_LLM_BASE_URL", "http://h/v1")
    monkeypatch.setenv("TRUS_LLM_MODEL", "m")
    for k in _VARS:
        monkeypatch.delenv(k, raising=False)  # cache on by default

    calls = {"n": 0}

    def fake_generate(prompt, system=None, *, schema=None, expect_array=False):
        calls["n"] += 1
        text = json.dumps(
            [
                {
                    "title": "Cached Tool",
                    "components": [{"id": "a", "type": "text_input", "label": "A"}],
                },
            ]
        )
        result = gen_result(text, provider="openai", model="m")
        llm.last_call.set(result)  # mirrors what the real llm.generate() does
        return result

    monkeypatch.setattr(orchestrator.llm, "generate", fake_generate)

    prompt = "a very specific unique caching prompt"
    r1 = orchestrator.generate_modules(prompt)
    assert [m.title for m in r1] == ["Cached Tool"]
    assert calls["n"] == 1

    r2 = orchestrator.generate_modules(prompt)  # exact match → from cache
    assert [m.title for m in r2] == ["Cached Tool"]
    assert calls["n"] == 1  # model NOT called again
