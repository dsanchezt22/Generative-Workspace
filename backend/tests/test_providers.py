"""Tests for the LLM provider abstraction (gemini / openai-compatible / stub)."""

import json

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


def test_provider_info_has_no_secrets(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TRUS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("TRUS_LLM_BASE_URL", "http://h/v1")
    monkeypatch.setenv("TRUS_LLM_MODEL", "qwen3:4b")
    monkeypatch.setenv("TRUS_LLM_API_KEY", "super-secret")
    info = llm.provider_info()
    assert info == {"provider": "openai", "model": "qwen3:4b", "base_url": "http://h/v1"}
    assert "super-secret" not in json.dumps(info)


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
