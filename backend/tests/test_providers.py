"""Tests for the LLM provider abstraction (gemini / openai-compatible / stub)."""

import io
import json
import urllib.error
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from src import llm
from src.schema import LLMError

_VARS = (
    "TRUS_LLM_PROVIDER",
    "TRUS_LLM_BASE_URL",
    "TRUS_LLM_MODEL",
    "TRUS_LLM_API_KEY",
    "GEMINI_API_KEY",
    "TRUS_LLM_JSON_MODE",
    "TRUS_LLM_CASCADE",
)


def _clear(monkeypatch):
    for k in _VARS:
        monkeypatch.delenv(k, raising=False)


class _FakeResp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _chat(content):
    return _FakeResp({"choices": [{"message": {"content": content}}]})


class _BadJsonResp:
    def read(self):
        return b"not json"

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_every_outbound_urlopen_passes_explicit_timeout():
    """Source invariant: every urlopen() in the two HTTP-making modules carries an
    explicit timeout=. A future executor must not silently ship an unbounded
    network call that stalls the single scheduler thread. AST walk (not a substring
    grep) so a module-level constant (timeout=_TIMEOUT) counts and a multi-line
    call is still checked correctly."""
    import ast
    from pathlib import Path

    import src.llm
    import src.services.live_data

    for module in (src.llm, src.services.live_data):
        tree = ast.parse(Path(module.__file__).read_text())
        calls = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and (
                (isinstance(n.func, ast.Attribute) and n.func.attr == "urlopen")
                or (isinstance(n.func, ast.Name) and n.func.id == "urlopen")
            )
        ]
        assert calls, f"expected at least one urlopen call in {module.__name__}"
        for call in calls:
            assert "timeout" in {kw.arg for kw in call.keywords}, (
                f"{module.__name__}:{call.lineno} — urlopen without an explicit "
                "timeout can stall the scheduler thread"
            )


def test_resolve_provider_auto(monkeypatch):
    _clear(monkeypatch)
    assert llm._resolve_provider() == "stub"
    assert llm.is_stub_mode() is True

    monkeypatch.setenv("GEMINI_API_KEY", "AIza-real-key")
    assert llm._resolve_provider() == "gemini"

    monkeypatch.setenv("TRUS_LLM_BASE_URL", "http://localhost:11434/v1")
    assert llm._resolve_provider() == "openai"  # a base URL takes precedence

    monkeypatch.setenv("TRUS_LLM_PROVIDER", "stub")
    assert llm._resolve_provider() == "stub"  # explicit override wins


def test_stub_expect_text_returns_honest_prose_not_module_json(monkeypatch):
    # A ModuleConfig-shaped JSON dump (the default stub shape, for module
    # generation) would read as garbage inside an automation's digest/draft
    # Feed entry — expect_text must get honest, clearly-labeled prose instead.
    _clear(monkeypatch)
    monkeypatch.setenv("TRUS_LLM_PROVIDER", "stub")
    default = llm.generate("Summarize this page.", system="s")
    assert default.text.strip().startswith("{")  # unchanged: still the module stub

    text = llm.generate("Summarize this page.", system="s", expect_text=True)
    assert text.provider == "stub"
    assert not text.text.strip().startswith("{")
    assert "no live model configured" in text.text
    assert "Summarize this page." in text.text  # echoes the real prompt, doesn't fabricate


def test_provider_info_has_no_secrets(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TRUS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("TRUS_LLM_BASE_URL", "http://h/v1")
    monkeypatch.setenv("TRUS_LLM_MODEL", "qwen3:4b")
    monkeypatch.setenv("TRUS_LLM_API_KEY", "super-secret")
    info = llm.provider_info()
    assert info == {"provider": "openai", "model": "qwen3:4b", "base_url": "http://h/v1"}
    assert "super-secret" not in json.dumps(info)


def test_provider_info_gemini_branch(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TRUS_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-pro")
    info = llm.provider_info()
    assert info == {"provider": "gemini", "model": "gemini-2.5-pro"}


def test_openai_generate_posts_chat_completions(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TRUS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("TRUS_LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("TRUS_LLM_MODEL", "qwen3:4b")
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["auth"] = req.get_header("Authorization")
        captured["body"] = json.loads(req.data.decode())
        return _chat('{"title":"X","components":[]}')

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
    out = llm.generate("make a tracker", system="SYS")
    assert json.loads(out.text)["title"] == "X"
    assert captured["url"] == "http://localhost:11434/v1/chat/completions"
    assert captured["auth"] is None  # no key → no auth header (local server)
    assert captured["body"]["model"] == "qwen3:4b"
    assert captured["body"]["messages"][0] == {"role": "system", "content": "SYS"}
    assert captured["body"]["messages"][1]["content"] == "make a tracker"
    assert captured["body"]["response_format"]["type"] == "json_object"  # default object mode


def test_openai_array_path_skips_json_object(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TRUS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("TRUS_LLM_BASE_URL", "http://h/v1")
    monkeypatch.setenv("TRUS_LLM_MODEL", "m")
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["body"] = json.loads(req.data.decode())
        return _chat("[]")

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
    llm.generate("x", system="s", expect_array=True)
    # json_object root would forbid the array the decompose path needs.
    assert "response_format" not in captured["body"]


def test_openai_expect_text_skips_json_object(monkeypatch):
    # A free-text automation call (digest/draft) must not force JSON mode, or
    # a real model's plain-prose output would come back JSON-shaped — the
    # same bug class test_openai_array_path_skips_json_object guards for the
    # decompose path, but for expect_text instead of expect_array.
    _clear(monkeypatch)
    monkeypatch.setenv("TRUS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("TRUS_LLM_BASE_URL", "http://h/v1")
    monkeypatch.setenv("TRUS_LLM_MODEL", "m")
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["body"] = json.loads(req.data.decode())
        return _chat("A short honest sentence.")

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
    out = llm.generate("summarize this", system="s", expect_text=True)
    assert out.text == "A short honest sentence."
    assert "response_format" not in captured["body"]


def test_openai_chat_schema_mode_sets_json_schema(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TRUS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("TRUS_LLM_BASE_URL", "http://h/v1")
    monkeypatch.setenv("TRUS_LLM_MODEL", "m")
    monkeypatch.setenv("TRUS_LLM_JSON_MODE", "schema")
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["body"] = json.loads(req.data.decode())
        return _chat('{"title":"X"}')

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
    llm.generate("x", schema={"type": "object"})
    assert captured["body"]["response_format"]["type"] == "json_schema"
    assert captured["body"]["response_format"]["json_schema"]["schema"] == {"type": "object"}


def test_openai_sends_bearer_when_key_set(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TRUS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("TRUS_LLM_BASE_URL", "https://api.together.xyz/v1")
    monkeypatch.setenv("TRUS_LLM_MODEL", "m")
    monkeypatch.setenv("TRUS_LLM_API_KEY", "k-123")
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["auth"] = req.get_header("Authorization")
        return _chat("{}")

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
    llm.generate("x")
    assert captured["auth"] == "Bearer k-123"


def test_openai_cascade_to_stub_when_unreachable(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TRUS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("TRUS_LLM_BASE_URL", "http://localhost:1/v1")
    monkeypatch.setenv("TRUS_LLM_MODEL", "m")

    def boom(req, timeout=None):
        raise OSError("connection refused")

    monkeypatch.setattr(llm.urllib.request, "urlopen", boom)
    out = llm.generate("a workout tracker")  # no gemini key → degrade to templates
    assert "components" in json.loads(out.text)
    assert out.degraded is True


def test_openai_cascade_to_gemini_when_key_present(monkeypatch):
    """R-403 cascade: an unreachable openai-compatible endpoint with a real Gemini
    key set degrades to gemini (not straight to stub templates)."""
    _clear(monkeypatch)
    monkeypatch.setenv("TRUS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("TRUS_LLM_BASE_URL", "http://localhost:1/v1")
    monkeypatch.setenv("TRUS_LLM_MODEL", "m")
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-real-looking-key")
    monkeypatch.setattr(llm, "_gemini_generate", lambda prompt, system, **_: '{"title":"cascaded"}')

    def boom(req, timeout=None):
        raise OSError("refused")

    monkeypatch.setattr(llm.urllib.request, "urlopen", boom)
    out = llm.generate("a workout tracker")
    assert out.provider == "gemini"
    assert out.degraded is True
    assert out.text == '{"title":"cascaded"}'


def test_cascade_off_raises(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TRUS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("TRUS_LLM_BASE_URL", "http://localhost:1/v1")
    monkeypatch.setenv("TRUS_LLM_MODEL", "m")
    monkeypatch.setenv("TRUS_LLM_CASCADE", "off")

    def boom(req, timeout=None):
        raise OSError("refused")

    monkeypatch.setattr(llm.urllib.request, "urlopen", boom)
    with pytest.raises(LLMError):
        llm.generate("x")


def test_openai_missing_config_errors(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TRUS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("TRUS_LLM_CASCADE", "off")  # so it raises rather than degrading
    with pytest.raises(LLMError):
        llm.generate("x")  # no base_url/model


def test_openai_chat_http_error(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TRUS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("TRUS_LLM_BASE_URL", "http://h/v1")
    monkeypatch.setenv("TRUS_LLM_MODEL", "m")
    monkeypatch.setenv("TRUS_LLM_CASCADE", "off")

    def boom(req, timeout=None):
        raise urllib.error.HTTPError("http://h/v1", 500, "Server Error", {}, io.BytesIO(b"oops"))

    monkeypatch.setattr(llm.urllib.request, "urlopen", boom)
    with pytest.raises(LLMError, match="HTTP 500"):
        llm.generate("x")


def test_openai_chat_non_json_response(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TRUS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("TRUS_LLM_BASE_URL", "http://h/v1")
    monkeypatch.setenv("TRUS_LLM_MODEL", "m")
    monkeypatch.setenv("TRUS_LLM_CASCADE", "off")

    monkeypatch.setattr(llm.urllib.request, "urlopen", lambda req, timeout=None: _BadJsonResp())
    with pytest.raises(LLMError, match="non-JSON"):
        llm.generate("x")


def test_openai_chat_unexpected_shape(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TRUS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("TRUS_LLM_BASE_URL", "http://h/v1")
    monkeypatch.setenv("TRUS_LLM_MODEL", "m")
    monkeypatch.setenv("TRUS_LLM_CASCADE", "off")

    monkeypatch.setattr(
        llm.urllib.request, "urlopen", lambda req, timeout=None: _FakeResp({"unexpected": True})
    )
    with pytest.raises(LLMError, match="Unexpected LLM response shape"):
        llm.generate("x")


def test_openai_chat_empty_content(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TRUS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("TRUS_LLM_BASE_URL", "http://h/v1")
    monkeypatch.setenv("TRUS_LLM_MODEL", "m")
    monkeypatch.setenv("TRUS_LLM_CASCADE", "off")

    monkeypatch.setattr(llm.urllib.request, "urlopen", lambda req, timeout=None: _chat("   "))
    with pytest.raises(LLMError, match="empty response"):
        llm.generate("x")


def test_status_endpoint(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TRUS_LLM_PROVIDER", "stub")
    from fastapi.testclient import TestClient
    from src.main import app

    with TestClient(app) as c:
        r = c.get("/api/llm/status")
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "stub"
    assert "cache" in body and "entries" in body["cache"]


# ---------------------------------------------------------------------------
# _timeout / _max_output_tokens edge cases
# ---------------------------------------------------------------------------


def test_timeout_invalid_value_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("TRUS_LLM_TIMEOUT", "not-a-number")
    assert llm._timeout() == 60.0


def test_max_output_tokens_unset_returns_none(monkeypatch):
    monkeypatch.delenv("TRUS_LLM_MAX_OUTPUT_TOKENS", raising=False)
    assert llm._max_output_tokens() is None


def test_max_output_tokens_invalid_returns_none(monkeypatch):
    monkeypatch.setenv("TRUS_LLM_MAX_OUTPUT_TOKENS", "nope")
    assert llm._max_output_tokens() is None


def test_max_output_tokens_valid_returns_int(monkeypatch):
    monkeypatch.setenv("TRUS_LLM_MAX_OUTPUT_TOKENS", "512")
    assert llm._max_output_tokens() == 512


# ---------------------------------------------------------------------------
# gemini backend — mocked at the client boundary, never hits the network
# ---------------------------------------------------------------------------


class _FakeGeminiResponse:
    def __init__(self, text):
        self.text = text


class _FakeGeminiModels:
    def __init__(self, text=None, exc=None):
        self._text = text
        self._exc = exc

    def generate_content(self, **kwargs):
        if self._exc:
            raise self._exc
        return _FakeGeminiResponse(self._text)


class _FakeGeminiClient:
    def __init__(self, text=None, exc=None):
        self.models = _FakeGeminiModels(text, exc)


@pytest.fixture
def _reset_gemini_client():
    llm._client = None
    yield
    llm._client = None


@pytest.mark.filterwarnings("ignore::DeprecationWarning")  # google.genai import-time noise
def test_get_client_constructs_once_and_caches(monkeypatch, _reset_gemini_client):
    _clear(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-real-key")
    with patch("google.genai.Client") as MockClient:
        MockClient.return_value = "the-client"
        c1 = llm._get_client()
        c2 = llm._get_client()
    assert c1 == "the-client"
    assert c2 == "the-client"
    MockClient.assert_called_once_with(api_key="fake-real-key")


def test_gemini_config_includes_max_output_tokens_when_set(monkeypatch):
    monkeypatch.delenv("TRUS_LLM_MAX_OUTPUT_TOKENS", raising=False)
    cfg = llm._gemini_config("SYS")
    assert cfg.max_output_tokens is None
    monkeypatch.setenv("TRUS_LLM_MAX_OUTPUT_TOKENS", "256")
    cfg2 = llm._gemini_config("SYS")
    assert cfg2.max_output_tokens == 256


def test_gemini_config_forces_json_by_default_but_not_for_expect_text():
    # Every ModuleConfig-generating caller relies on JSON mime by default; a
    # free-text automation call (expect_text=True) must NOT force JSON, or a
    # real model's digest/draft output would come back JSON-shaped instead of
    # plain prose (the bug this pair of tests guards against).
    assert llm._gemini_config("SYS").response_mime_type == "application/json"
    assert llm._gemini_config("SYS", expect_text=True).response_mime_type is None


def test_gemini_generate_expect_text_skips_json_mime(monkeypatch):
    monkeypatch.setattr(
        llm, "_get_client", lambda: _FakeGeminiClient(text="Everything looks fine.")
    )
    text = llm._gemini_generate("prompt", "sys", expect_text=True)
    assert text == "Everything looks fine."


def test_gemini_generate_success(monkeypatch):
    monkeypatch.setattr(llm, "_get_client", lambda: _FakeGeminiClient(text='{"title":"G"}'))
    text = llm._gemini_generate("prompt", "sys")
    assert text == '{"title":"G"}'


def test_gemini_generate_empty_response_raises(monkeypatch):
    monkeypatch.setattr(llm, "_get_client", lambda: _FakeGeminiClient(text=""))
    with pytest.raises(LLMError, match="empty response"):
        llm._gemini_generate("prompt", "sys")


def test_gemini_generate_exception_raises_llmerror(monkeypatch):
    monkeypatch.setattr(
        llm, "_get_client", lambda: _FakeGeminiClient(exc=RuntimeError("429 quota"))
    )
    with pytest.raises(LLMError, match="quota"):
        llm._gemini_generate("prompt", "sys")


def test_gemini_generate_file_success(monkeypatch):
    monkeypatch.setattr(llm, "_get_client", lambda: _FakeGeminiClient(text='{"ok":true}'))
    text = llm._gemini_generate_file("describe", "sys", b"data", "image/png")
    assert text == '{"ok":true}'


def test_gemini_generate_file_empty_raises(monkeypatch):
    monkeypatch.setattr(llm, "_get_client", lambda: _FakeGeminiClient(text=None))
    with pytest.raises(LLMError, match="empty response"):
        llm._gemini_generate_file("describe", "sys", b"data", "image/png")


def test_gemini_generate_file_exception_raises(monkeypatch):
    monkeypatch.setattr(llm, "_get_client", lambda: _FakeGeminiClient(exc=RuntimeError("boom")))
    with pytest.raises(LLMError, match="boom"):
        llm._gemini_generate_file("describe", "sys", b"data", "image/png")


def test_generate_gemini_provider_returns_gemini_result(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TRUS_LLM_PROVIDER", "gemini")
    monkeypatch.setattr(llm, "_gemini_generate", lambda prompt, system, **_: '{"title":"G"}')
    out = llm.generate("x")
    assert out.provider == "gemini"
    assert out.text == '{"title":"G"}'
    assert out.degraded is False


# ---------------------------------------------------------------------------
# F6 — ContextVar hygiene: an exception path leaves last_call = None (unknown
# provenance), never a stale prior value.
# F7 — GenResult carries the model label of the branch that actually answered.
# ---------------------------------------------------------------------------


def test_generate_resets_last_call_to_none_on_error(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TRUS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("TRUS_LLM_BASE_URL", "http://h/v1")
    monkeypatch.setenv("TRUS_LLM_MODEL", "m")
    monkeypatch.setenv("TRUS_LLM_CASCADE", "off")  # raise instead of degrading
    monkeypatch.setattr(
        llm, "_openai_chat", lambda *a, **k: (_ for _ in ()).throw(LLMError("down"))
    )
    llm.last_call.set(llm.GenResult("stale", "stub", "stub"))  # pre-existing value
    with pytest.raises(LLMError):
        llm.generate("x")
    assert llm.last_call.get() is None  # not the stale value


def test_cascade_to_gemini_labels_the_gemini_model(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TRUS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("TRUS_LLM_MODEL", "local-qwen")
    monkeypatch.setenv("TRUS_LLM_BASE_URL", "http://localhost:1/v1")
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-real")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-flash-latest")
    monkeypatch.setattr(
        llm, "_openai_chat", lambda *a, **k: (_ for _ in ()).throw(LLMError("down"))
    )
    monkeypatch.setattr(llm, "_gemini_generate", lambda p, s, **_: '{"title":"cascaded"}')
    out = llm.generate("x")
    assert out.provider == "gemini"
    assert out.model == "gemini-flash-latest"  # NOT the failed openai model
    assert out.degraded is True


def test_openai_success_labels_the_llm_model(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TRUS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("TRUS_LLM_MODEL", "local-qwen")
    monkeypatch.setenv("TRUS_LLM_BASE_URL", "http://h/v1")
    monkeypatch.setattr(llm, "_openai_chat", lambda *a, **k: ('{"title":"X"}', {}))
    out = llm.generate("x")
    assert out.provider == "openai"
    assert out.model == "local-qwen"


def test_gemini_provider_labels_the_gemini_model(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TRUS_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-pro")
    monkeypatch.setattr(llm, "_gemini_generate", lambda p, s, **_: '{"title":"G"}')
    out = llm.generate("x")
    assert out.model == "gemini-2.5-pro"


# ---------------------------------------------------------------------------
# generate_from_file — stub / openai (image, non-image) / gemini
# ---------------------------------------------------------------------------


def test_generate_from_file_stub_returns_empty_object(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TRUS_LLM_PROVIDER", "stub")
    llm.last_call.set(llm.GenResult("stale", "stub", "stub"))
    assert llm.generate_from_file("msg", None, b"data", "image/png") == "{}"
    assert llm.last_call.get() is None  # "{}" is a refusal sentinel, not a success


def test_generate_from_file_openai_image_posts_data_url(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TRUS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("TRUS_LLM_BASE_URL", "http://h/v1")
    monkeypatch.setenv("TRUS_LLM_MODEL", "m")
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["body"] = json.loads(req.data.decode())
        return _chat('[{"title":"FromImage"}]')

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
    out = llm.generate_from_file("describe this", "SYS", b"\x89PNG", "image/png")
    assert "FromImage" in out
    content = captured["body"]["messages"][-1]["content"]
    assert content[0] == {"type": "text", "text": "describe this"}
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert "response_format" not in captured["body"]  # expect_array=True skips json_object


def test_generate_from_file_openai_non_image_returns_empty_object(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TRUS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("TRUS_LLM_BASE_URL", "http://h/v1")
    monkeypatch.setenv("TRUS_LLM_MODEL", "m")
    llm.last_call.set(llm.GenResult("stale", "stub", "stub"))
    assert llm.generate_from_file("msg", None, b"data", "application/pdf") == "{}"
    assert llm.last_call.get() is None  # "{}" is a refusal sentinel, not a success


def test_generate_from_file_gemini_calls_gemini_generate_file(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TRUS_LLM_PROVIDER", "gemini")
    monkeypatch.setattr(
        llm, "_gemini_generate_file_raw", lambda *a, **k: ("gemini-file-text", SimpleNamespace())
    )
    out = llm.generate_from_file("msg", "sys", b"data", "application/pdf")
    assert out == "gemini-file-text"


# ---------------------------------------------------------------------------
# R-1201/R-1202: generate_from_file sets last_call to a real GenResult on
# success — provider/model per generate()'s branch resolution, tokens where the
# payload offers them. The "{}" sentinel paths above are refusals, not
# successes, and are asserted to leave last_call None.
# ---------------------------------------------------------------------------


def test_generate_from_file_gemini_success_sets_last_call_with_tokens(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TRUS_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-pro")
    response = SimpleNamespace(
        text='{"ok":true}',
        usage_metadata=SimpleNamespace(prompt_token_count=120, candidates_token_count=45),
    )
    monkeypatch.setattr(llm, "_gemini_generate_file_raw", lambda *a, **k: ('{"ok":true}', response))
    out = llm.generate_from_file("msg", "sys", b"data", "application/pdf")
    assert out == '{"ok":true}'
    last = llm.last_call.get()
    assert last is not None
    assert last.provider == "gemini"
    assert last.model == "gemini-2.5-pro"
    assert last.degraded is False
    assert last.tokens_in == 120
    assert last.tokens_out == 45


def test_generate_from_file_gemini_success_without_usage_metadata_leaves_tokens_none(monkeypatch):
    """Defensive: not every SDK response (or test double) sets usage_metadata."""
    _clear(monkeypatch)
    monkeypatch.setenv("TRUS_LLM_PROVIDER", "gemini")
    response = SimpleNamespace(text='{"ok":true}')  # no usage_metadata attribute at all
    monkeypatch.setattr(llm, "_gemini_generate_file_raw", lambda *a, **k: ('{"ok":true}', response))
    llm.generate_from_file("msg", "sys", b"data", "application/pdf")
    last = llm.last_call.get()
    assert last is not None
    assert last.tokens_in is None
    assert last.tokens_out is None


def test_generate_from_file_openai_image_success_sets_last_call_with_tokens(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TRUS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("TRUS_LLM_BASE_URL", "http://h/v1")
    monkeypatch.setenv("TRUS_LLM_MODEL", "vision-model")

    def fake_urlopen(req, timeout=None):
        return _FakeResp(
            {
                "choices": [{"message": {"content": '[{"title":"FromImage"}]'}}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 20},
            }
        )

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
    out = llm.generate_from_file("describe this", "SYS", b"\x89PNG", "image/png")
    assert "FromImage" in out
    last = llm.last_call.get()
    assert last is not None
    assert last.provider == "openai"
    assert last.model == "vision-model"
    assert last.degraded is False
    assert last.tokens_in == 50
    assert last.tokens_out == 20


# ---------------------------------------------------------------------------
# vision (image → text): a separate backend for the Layout Studio importer
# ---------------------------------------------------------------------------


def test_vision_available_and_info_when_unset():
    assert llm.vision_available() is False
    assert llm.vision_info() == {"available": False}


def test_vision_available_and_info_when_set(monkeypatch):
    monkeypatch.setenv("TRUS_VISION_MODEL", "qwen2.5vl:7b")
    monkeypatch.setenv("TRUS_VISION_BASE_URL", "http://localhost:11434/v1")
    assert llm.vision_available() is True
    info = llm.vision_info()
    assert info == {
        "available": True,
        "model": "qwen2.5vl:7b",
        "base_url": "http://localhost:11434/v1",
    }


def test_vision_describe_missing_config_raises():
    with pytest.raises(LLMError, match="No vision model"):
        llm.vision_describe(None, "describe", b"data", "image/png")


def test_vision_describe_success(monkeypatch):
    monkeypatch.setenv("TRUS_VISION_MODEL", "vlm")
    monkeypatch.setenv("TRUS_VISION_BASE_URL", "http://h/v1")
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode())
        return _chat("described text")

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
    text = llm.vision_describe("SYS", "what is this", b"\x89PNG", "image/png")
    assert text == "described text"
    assert captured["url"] == "http://h/v1/chat/completions"


def test_vision_describe_http_error(monkeypatch):
    monkeypatch.setenv("TRUS_VISION_MODEL", "vlm")
    monkeypatch.setenv("TRUS_VISION_BASE_URL", "http://h/v1")

    def boom(req, timeout=None):
        raise urllib.error.HTTPError("http://h/v1", 503, "unavailable", {}, io.BytesIO(b"down"))

    monkeypatch.setattr(llm.urllib.request, "urlopen", boom)
    with pytest.raises(LLMError, match="HTTP 503"):
        llm.vision_describe(None, "x", b"data", "image/png")


def test_vision_describe_url_error(monkeypatch):
    monkeypatch.setenv("TRUS_VISION_MODEL", "vlm")
    monkeypatch.setenv("TRUS_VISION_BASE_URL", "http://h/v1")

    def boom(req, timeout=None):
        raise OSError("refused")

    monkeypatch.setattr(llm.urllib.request, "urlopen", boom)
    with pytest.raises(LLMError, match="Could not reach"):
        llm.vision_describe(None, "x", b"data", "image/png")


def test_vision_describe_non_json(monkeypatch):
    monkeypatch.setenv("TRUS_VISION_MODEL", "vlm")
    monkeypatch.setenv("TRUS_VISION_BASE_URL", "http://h/v1")

    monkeypatch.setattr(llm.urllib.request, "urlopen", lambda req, timeout=None: _BadJsonResp())
    with pytest.raises(LLMError, match="non-JSON"):
        llm.vision_describe(None, "x", b"data", "image/png")


def test_vision_describe_unexpected_shape(monkeypatch):
    monkeypatch.setenv("TRUS_VISION_MODEL", "vlm")
    monkeypatch.setenv("TRUS_VISION_BASE_URL", "http://h/v1")

    monkeypatch.setattr(llm.urllib.request, "urlopen", lambda req, timeout=None: _FakeResp({}))
    with pytest.raises(LLMError, match="Unexpected vision response shape"):
        llm.vision_describe(None, "x", b"data", "image/png")


def test_vision_describe_empty_content(monkeypatch):
    monkeypatch.setenv("TRUS_VISION_MODEL", "vlm")
    monkeypatch.setenv("TRUS_VISION_BASE_URL", "http://h/v1")

    monkeypatch.setattr(llm.urllib.request, "urlopen", lambda req, timeout=None: _chat(""))
    with pytest.raises(LLMError, match="empty response"):
        llm.vision_describe(None, "x", b"data", "image/png")


def test_vision_describe_uses_llm_key_and_base_url_fallbacks(monkeypatch):
    monkeypatch.setenv("TRUS_VISION_MODEL", "vlm")
    monkeypatch.delenv("TRUS_VISION_BASE_URL", raising=False)
    monkeypatch.setenv("TRUS_LLM_BASE_URL", "http://fallback/v1")
    monkeypatch.setenv("TRUS_LLM_API_KEY", "fallback-key")
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["auth"] = req.get_header("Authorization")
        return _chat("ok")

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
    llm.vision_describe(None, "x", b"data", "image/png")
    assert captured["url"] == "http://fallback/v1/chat/completions"
    assert captured["auth"] == "Bearer fallback-key"


def test_vision_capture_uses_local_vision_when_available(monkeypatch):
    monkeypatch.setenv("TRUS_VISION_MODEL", "vlm")
    monkeypatch.setattr(llm, "vision_describe", lambda *a, **k: "local-vision-text")
    assert llm.vision_capture(None, "x", b"data", "image/png") == "local-vision-text"


def test_vision_capture_falls_back_to_gemini(monkeypatch):
    monkeypatch.delenv("TRUS_VISION_MODEL", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-real")
    monkeypatch.setattr(llm, "_gemini_generate_file", lambda *a, **k: "gemini-vision-text")
    assert llm.vision_capture(None, "x", b"data", "image/png") == "gemini-vision-text"


def test_vision_capture_raises_when_nothing_available(monkeypatch):
    monkeypatch.delenv("TRUS_VISION_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(LLMError, match="No vision backend"):
        llm.vision_capture(None, "x", b"data", "image/png")
