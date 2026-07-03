import contextlib
import os
import tempfile
from collections.abc import Callable

import pytest
from src import llm


def gen_result(
    text: str, degraded: bool = False, provider: str = "test", model: str = "test"
) -> llm.GenResult:
    """Build a GenResult for tests that stub llm.generate's RETURN VALUE
    (e.g. patch(..., return_value=gen_result(RAW)))."""
    return llm.GenResult(text=text, provider=provider, model=model, degraded=degraded)


def fake_generate(text: str, degraded: bool = False) -> Callable[..., llm.GenResult]:
    """Return an llm.generate REPLACEMENT that sets llm.last_call (mirroring the real
    generate) and returns the GenResult — for monkeypatch.setattr(llm, "generate", …)
    where the caller then reads llm.last_call for provenance/degraded state."""

    def _generate(*_args: object, **_kwargs: object) -> llm.GenResult:
        result = gen_result(text, degraded=degraded)
        llm.last_call.set(result)
        return result

    return _generate


@pytest.fixture(autouse=True)
def _isolate_db(monkeypatch):
    """Each test gets a fresh SQLite file so state never leaks across tests."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setenv("TRUS_DB_PATH", path)
    yield
    with contextlib.suppress(FileNotFoundError):
        os.unlink(path)


@pytest.fixture(autouse=True)
def _isolate_llm_env(monkeypatch):
    """Don't let a developer's local-model .env (e.g. TRUS_LLM_BASE_URL pointing
    at Ollama) leak into tests — provider resolution must be deterministic, and
    no test should hit a live endpoint. Tests opt into a provider explicitly."""
    for k in (
        "TRUS_LLM_PROVIDER",
        "TRUS_LLM_BASE_URL",
        "TRUS_LLM_MODEL",
        "TRUS_LLM_API_KEY",
        "TRUS_LLM_JSON_MODE",
        # Cascade + tuning knobs: a dev .env override must not perturb provider
        # behavior, retry counts, timeouts, or output caps under test.
        "TRUS_LLM_CASCADE",
        "TRUS_LLM_MAX_RETRIES",
        "TRUS_LLM_TIMEOUT",
        "TRUS_LLM_MAX_OUTPUT_TOKENS",
        # Semantic-cache toggles — reset to code defaults so cache tests are
        # deterministic regardless of the developer's environment.
        "TRUS_CACHE",
        "TRUS_CACHE_THRESHOLD",
        "TRUS_CACHE_SEED_THRESHOLD",
        "TRUS_VISION_MODEL",
        "TRUS_VISION_BASE_URL",
        "TRUS_VISION_API_KEY",
        # GEMINI_API_KEY decides gemini-vs-stub; clearing it makes the default
        # provider deterministically "stub" on every machine (incl. a dev box
        # with a real key) so no test silently depends on it or hits a live API.
        "GEMINI_API_KEY",
        # Embedding endpoint — keep semantic_cache on its offline hash embedding.
        "TRUS_EMBED_BASE_URL",
        "TRUS_EMBED_MODEL",
        "TRUS_EMBED_API_KEY",
        # Ops-summary gate token — a developer's local .env must not leak a real
        # token into tests that assert 401-without-token behavior.
        "TRUS_OPS_TOKEN",
    ):
        monkeypatch.delenv(k, raising=False)


@pytest.fixture(autouse=True)
def _isolate_llm_last_call():
    """llm.last_call is a module-level contextvar — reset it so a real generate()
    call in one test can't leak its provenance/degraded state into the next
    (production requests are isolated per-thread via anyio's context.run(), but
    sequential direct calls in the same test process share the ambient context)."""
    token = llm.last_call.set(None)
    yield
    llm.last_call.reset(token)
