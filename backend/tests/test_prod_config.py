"""R-901/R-906: prod refuses the known-forgeable default secret; CORS/cookies
are env-driven (cross-origin hosted split needs same_site=none + https_only).

The brief's original tests reload `src.main` end-to-end. That module now wires
five routers, a lifespan, logging, and an ops-token gate, so most of the guard
logic is exercised here as small, directly-testable pure functions instead —
faster and immune to reload ordering issues. One reload-based integration test
is kept per function (secret guard, CORS) to prove the wiring itself is live.
"""

import importlib

import pytest
from src.main import (
    DEFAULT_SESSION_SECRET,
    _cookie_settings,
    _parse_cors_origins,
    _require_prod_secret,
)


class TestRequireProdSecret:
    def test_dev_env_allows_default_secret(self):
        _require_prod_secret("dev", DEFAULT_SESSION_SECRET)  # must not raise

    def test_missing_trus_env_treated_as_dev_allows_default_secret(self):
        # Callers pass os.environ.get("TRUS_ENV", "dev"); simulate the default here.
        _require_prod_secret("dev", DEFAULT_SESSION_SECRET)

    def test_prod_env_with_default_secret_raises(self):
        with pytest.raises(RuntimeError, match="SESSION_SECRET"):
            _require_prod_secret("prod", DEFAULT_SESSION_SECRET)

    def test_prod_env_with_strong_secret_boots_fine(self):
        _require_prod_secret("prod", "a-real-random-64-char-secret")  # must not raise


class TestParseCorsOrigins:
    def test_single_default_origin(self):
        assert _parse_cors_origins("http://localhost:3000") == ["http://localhost:3000"]

    def test_multiple_comma_separated_origins(self):
        assert _parse_cors_origins("https://a.example.com,https://b.example.com") == [
            "https://a.example.com",
            "https://b.example.com",
        ]

    def test_whitespace_trailing_comma_and_empty_entries_are_dropped(self):
        assert _parse_cors_origins(" https://a.example.com , , https://b.example.com ,\t") == [
            "https://a.example.com",
            "https://b.example.com",
        ]

    def test_empty_string_yields_no_origins(self):
        assert _parse_cors_origins("") == []


class TestCookieSettings:
    def test_default_insecure_is_lax_and_not_https_only(self):
        assert _cookie_settings(False) == ("lax", False)

    def test_secure_flag_sets_none_and_https_only_together(self):
        assert _cookie_settings(True) == ("none", True)


class TestLlmStatusPayload:
    """R-1201: /api/llm/status must not leak internal topology (base_url) or
    operational internals (cache stats) in prod. Dev keeps both — it's the
    documented local-setup verification tool. Tested at the function level
    (same pattern as the guards above): the payload builder reads TRUS_ENV
    per call, so no app reimport is needed."""

    def test_dev_payload_keeps_base_url_and_cache(self, tmp_path, monkeypatch):
        from src.main import _llm_status_payload

        monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
        monkeypatch.setenv("TRUS_ENV", "dev")
        monkeypatch.setenv("TRUS_LLM_PROVIDER", "openai")
        monkeypatch.setenv("TRUS_LLM_BASE_URL", "http://localhost:11434/v1")
        monkeypatch.setenv("TRUS_LLM_MODEL", "qwen")
        payload = _llm_status_payload()
        assert payload["provider"] == "openai"
        assert payload["base_url"] == "http://localhost:11434/v1"
        assert "cache" in payload
        assert "vision" in payload

    def test_prod_payload_omits_base_url_and_cache(self, tmp_path, monkeypatch):
        from src.main import _llm_status_payload

        monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
        monkeypatch.setenv("TRUS_ENV", "prod")
        monkeypatch.setenv("TRUS_LLM_PROVIDER", "openai")
        monkeypatch.setenv("TRUS_LLM_BASE_URL", "http://internal-llm:8000/v1")
        monkeypatch.setenv("TRUS_LLM_MODEL", "qwen")
        monkeypatch.setenv("TRUS_VISION_MODEL", "qwen-vl")
        payload = _llm_status_payload()
        assert "base_url" not in payload
        assert "cache" not in payload
        # Provider/model/vision availability are harmless and stay …
        assert payload["provider"] == "openai"
        assert payload["model"] == "qwen"
        assert payload["vision"]["available"] is True
        # … but vision's nested base_url is the same topology leak, and goes too.
        assert "base_url" not in payload["vision"]


def test_prod_refuses_default_session_secret_on_reload(monkeypatch):
    """Integration: the guard actually runs at module import/reload time, not
    just when called directly."""
    monkeypatch.setenv("TRUS_ENV", "prod")
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    import src.main

    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        importlib.reload(src.main)

    # Restore a healthy module for any other test that imported `app` earlier.
    monkeypatch.setenv("TRUS_ENV", "dev")
    importlib.reload(src.main)


def test_cors_origins_env_driven_on_reload(monkeypatch):
    monkeypatch.setenv("TRUS_CORS_ORIGINS", "https://app.example.com,https://trus.example.com")
    import src.main

    importlib.reload(src.main)
    cors = next(m for m in src.main.app.user_middleware if "CORSMiddleware" in str(m))
    assert "https://app.example.com" in cors.kwargs["allow_origins"]
    assert "https://trus.example.com" in cors.kwargs["allow_origins"]

    monkeypatch.delenv("TRUS_CORS_ORIGINS")
    importlib.reload(src.main)


def test_cookie_secure_env_flips_same_site_and_https_only_together_on_reload(monkeypatch):
    monkeypatch.setenv("TRUS_COOKIE_SECURE", "1")
    import src.main

    importlib.reload(src.main)
    session_mw = next(m for m in src.main.app.user_middleware if "SessionMiddleware" in str(m))
    assert session_mw.kwargs["same_site"] == "none"
    assert session_mw.kwargs["https_only"] is True

    monkeypatch.delenv("TRUS_COOKIE_SECURE")
    importlib.reload(src.main)
