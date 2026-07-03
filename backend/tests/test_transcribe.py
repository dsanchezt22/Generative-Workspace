"""POST /api/transcribe (R-201/R-204 half): pluggable voice transcription.

Unset TRUS_STT_BASE_URL/MODEL is an honest, non-cost 422 (I-1 config-not-code,
R-403 family) — checked BEFORE the upload is read. A configured endpoint is
exercised via `llm.transcribe` (unit-level, mirrors test_providers.py's
urlopen-mocking style for the other pluggable providers) and via the route
(mirrors test_generate_from_file.py's monkeypatch-the-llm-call style).
"""

import io
import json
import urllib.error

import pytest
from fastapi.testclient import TestClient
from src import db, llm
from src.main import app
from src.schema import LLMError


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _configure_stt(monkeypatch):
    monkeypatch.setenv("TRUS_STT_BASE_URL", "http://localhost:9/v1")
    monkeypatch.setenv("TRUS_STT_MODEL", "whisper-1")


# ---------------------------------------------------------------------------
# Route: config-not-set → honest 422, checked before the file is processed.
# ---------------------------------------------------------------------------


def test_transcribe_unset_config_refuses_honestly(client):
    resp = client.post(
        "/api/transcribe",
        files={"file": ("ramble.webm", b"fake-audio-bytes", "audio/webm")},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == (
        "Voice transcription needs a configured model — set TRUS_STT_* or type instead."
    )


def test_transcribe_unset_config_checked_before_oversized_read(client):
    """The config check happens BEFORE the 25MB read cap — an oversized upload
    with no STT configured still gets the honest 422, not a 413."""
    oversized = b"x" * (25 * 1024 * 1024 + 1)
    resp = client.post(
        "/api/transcribe",
        files={"file": ("big.webm", oversized, "audio/webm")},
    )
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# Route: happy path, empty transcript, oversized, origin gate, owner gate.
# ---------------------------------------------------------------------------


def test_transcribe_success_returns_text(client, monkeypatch):
    _configure_stt(monkeypatch)
    monkeypatch.setattr(llm, "transcribe", lambda data, mime, filename: "buy milk tomorrow")

    resp = client.post(
        "/api/transcribe",
        files={"file": ("ramble.webm", b"fake-audio-bytes", "audio/webm")},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"text": "buy milk tomorrow"}


def test_transcribe_empty_transcript_refuses(client, monkeypatch):
    _configure_stt(monkeypatch)
    monkeypatch.setattr(llm, "transcribe", lambda data, mime, filename: "   ")

    resp = client.post(
        "/api/transcribe",
        files={"file": ("silence.webm", b"fake-audio-bytes", "audio/webm")},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == "The recording didn't contain recognizable speech."


def test_transcribe_rejects_oversized_file(client, monkeypatch):
    _configure_stt(monkeypatch)
    oversized = b"x" * (25 * 1024 * 1024 + 1)
    resp = client.post(
        "/api/transcribe",
        files={"file": ("big.webm", oversized, "audio/webm")},
    )
    assert resp.status_code == 413, resp.text


def test_transcribe_foreign_origin_is_403(client, monkeypatch):
    _configure_stt(monkeypatch)
    resp = client.post(
        "/api/transcribe",
        files={"file": ("ramble.webm", b"fake-audio-bytes", "audio/webm")},
        headers={"Origin": "https://evil.example"},
    )
    assert resp.status_code == 403, resp.text


def test_transcribe_unclaimed_session_401_when_anon_disallowed(client, monkeypatch):
    monkeypatch.setenv("TRUS_ALLOW_ANON", "0")
    # Deliberately leave STT unset — the owner gate must still fire first.
    resp = client.post(
        "/api/transcribe",
        files={"file": ("ramble.webm", b"fake-audio-bytes", "audio/webm")},
    )
    assert resp.status_code == 401, resp.text


def test_transcribe_provider_error_returns_sanitized_503(client, monkeypatch):
    _configure_stt(monkeypatch)

    def boom(data, mime, filename):
        raise LLMError(
            "STT endpoint returned HTTP 500: internal trace http://internal-host:9/v1/audio"
        )

    monkeypatch.setattr(llm, "transcribe", boom)

    resp = client.post(
        "/api/transcribe",
        files={"file": ("ramble.webm", b"fake-audio-bytes", "audio/webm")},
    )
    assert resp.status_code == 503, resp.text
    detail = resp.json()["detail"]
    assert "http" not in detail.lower()
    assert "internal-host" not in detail


def test_transcribe_never_touches_last_call(client, monkeypatch):
    """Transcription isn't a "generation" — it must not set/clear llm.last_call,
    which other routes read for provenance (R-1201/R-1202)."""
    _configure_stt(monkeypatch)
    sentinel = llm.GenResult("sentinel", "stub", "stub")
    llm.last_call.set(sentinel)
    monkeypatch.setattr(llm, "transcribe", lambda data, mime, filename: "hello")

    resp = client.post(
        "/api/transcribe",
        files={"file": ("ramble.webm", b"fake-audio-bytes", "audio/webm")},
    )
    assert resp.status_code == 200, resp.text
    assert llm.last_call.get() is sentinel


# ---------------------------------------------------------------------------
# Telemetry: gen_events row, kind="transcribe", provider="stt".
# ---------------------------------------------------------------------------


def test_transcribe_success_records_ok_telemetry(client, monkeypatch):
    _configure_stt(monkeypatch)
    monkeypatch.setattr(llm, "transcribe", lambda data, mime, filename: "hello world")

    resp = client.post(
        "/api/transcribe",
        files={"file": ("ramble.webm", b"fake-audio-bytes", "audio/webm")},
    )
    assert resp.status_code == 200, resp.text

    with db._conn() as c:
        rows = c.execute(
            "SELECT kind, outcome, provider, model, tokens_in, tokens_out"
            " FROM gen_events WHERE kind = 'transcribe'"
        ).fetchall()
    assert len(rows) == 1
    row = rows[0]
    assert row["outcome"] == "ok"
    assert row["provider"] == "stt"
    assert row["model"] == "whisper-1"
    assert row["tokens_in"] is None
    assert row["tokens_out"] is None


def test_transcribe_provider_error_records_error_telemetry(client, monkeypatch):
    _configure_stt(monkeypatch)

    def boom(data, mime, filename):
        raise LLMError("down")

    monkeypatch.setattr(llm, "transcribe", boom)

    resp = client.post(
        "/api/transcribe",
        files={"file": ("ramble.webm", b"fake-audio-bytes", "audio/webm")},
    )
    assert resp.status_code == 503, resp.text

    with db._conn() as c:
        rows = c.execute(
            "SELECT kind, outcome, provider FROM gen_events WHERE kind = 'transcribe'"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["outcome"] == "error"
    assert rows[0]["provider"] == "stt"


# ---------------------------------------------------------------------------
# llm.transcribe — unit level (mirrors test_providers.py's urlopen mocking).
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_llm_transcribe_missing_config_raises(monkeypatch):
    monkeypatch.delenv("TRUS_STT_BASE_URL", raising=False)
    monkeypatch.delenv("TRUS_STT_MODEL", raising=False)
    with pytest.raises(LLMError, match="TRUS_STT_BASE_URL"):
        llm.transcribe(b"data", "audio/webm", "ramble.webm")


def test_llm_stt_available_requires_both_vars(monkeypatch):
    monkeypatch.delenv("TRUS_STT_BASE_URL", raising=False)
    monkeypatch.delenv("TRUS_STT_MODEL", raising=False)
    assert llm.stt_available() is False
    monkeypatch.setenv("TRUS_STT_BASE_URL", "http://h/v1")
    assert llm.stt_available() is False  # model still unset
    monkeypatch.setenv("TRUS_STT_MODEL", "whisper-1")
    assert llm.stt_available() is True


def test_llm_transcribe_posts_multipart_with_model_and_file(monkeypatch):
    monkeypatch.setenv("TRUS_STT_BASE_URL", "http://h/v1")
    monkeypatch.setenv("TRUS_STT_MODEL", "whisper-1")
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["content_type"] = req.get_header("Content-type")
        captured["auth"] = req.get_header("Authorization")
        captured["body"] = req.data
        captured["timeout"] = timeout
        return _FakeResp({"text": "hello world"})

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
    text = llm.transcribe(b"raw-audio-bytes", "audio/webm", "ramble.webm")

    assert text == "hello world"
    assert captured["url"] == "http://h/v1/audio/transcriptions"
    assert captured["content_type"].startswith("multipart/form-data; boundary=")
    assert captured["auth"] is None  # no key configured
    assert b'name="model"' in captured["body"]
    assert b"whisper-1" in captured["body"]
    assert b'name="file"; filename="ramble.webm"' in captured["body"]
    assert b"Content-Type: audio/webm" in captured["body"]
    assert b"raw-audio-bytes" in captured["body"]


def test_llm_transcribe_sends_bearer_when_key_set(monkeypatch):
    monkeypatch.setenv("TRUS_STT_BASE_URL", "http://h/v1")
    monkeypatch.setenv("TRUS_STT_MODEL", "whisper-1")
    monkeypatch.setenv("TRUS_STT_API_KEY", "k-123")
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["auth"] = req.get_header("Authorization")
        return _FakeResp({"text": "ok"})

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
    llm.transcribe(b"data", "audio/webm", "r.webm")
    assert captured["auth"] == "Bearer k-123"


def test_llm_transcribe_http_error(monkeypatch):
    monkeypatch.setenv("TRUS_STT_BASE_URL", "http://h/v1")
    monkeypatch.setenv("TRUS_STT_MODEL", "whisper-1")

    def boom(req, timeout=None):
        raise urllib.error.HTTPError("http://h/v1", 500, "Server Error", {}, io.BytesIO(b"oops"))

    monkeypatch.setattr(llm.urllib.request, "urlopen", boom)
    with pytest.raises(LLMError, match="HTTP 500"):
        llm.transcribe(b"data", "audio/webm", "r.webm")


def test_llm_transcribe_url_error(monkeypatch):
    monkeypatch.setenv("TRUS_STT_BASE_URL", "http://h/v1")
    monkeypatch.setenv("TRUS_STT_MODEL", "whisper-1")

    def boom(req, timeout=None):
        raise OSError("refused")

    monkeypatch.setattr(llm.urllib.request, "urlopen", boom)
    with pytest.raises(LLMError, match="Could not reach"):
        llm.transcribe(b"data", "audio/webm", "r.webm")


def test_llm_transcribe_non_json_response(monkeypatch):
    monkeypatch.setenv("TRUS_STT_BASE_URL", "http://h/v1")
    monkeypatch.setenv("TRUS_STT_MODEL", "whisper-1")

    class _BadJson:
        def read(self):
            return b"not json"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(llm.urllib.request, "urlopen", lambda req, timeout=None: _BadJson())
    with pytest.raises(LLMError, match="non-JSON"):
        llm.transcribe(b"data", "audio/webm", "r.webm")


def test_llm_transcribe_unexpected_shape_raises(monkeypatch):
    monkeypatch.setenv("TRUS_STT_BASE_URL", "http://h/v1")
    monkeypatch.setenv("TRUS_STT_MODEL", "whisper-1")

    monkeypatch.setattr(
        llm.urllib.request, "urlopen", lambda req, timeout=None: _FakeResp({"unexpected": True})
    )
    with pytest.raises(LLMError, match="Unexpected STT response shape"):
        llm.transcribe(b"data", "audio/webm", "r.webm")


def test_llm_transcribe_filename_none_defaults(monkeypatch):
    monkeypatch.setenv("TRUS_STT_BASE_URL", "http://h/v1")
    monkeypatch.setenv("TRUS_STT_MODEL", "whisper-1")
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["body"] = req.data
        return _FakeResp({"text": "ok"})

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
    llm.transcribe(b"data", "audio/webm", None)
    assert b'filename="audio"' in captured["body"]
