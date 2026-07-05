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


def test_transcribe_non_audio_mime_refuses(client, monkeypatch):
    """A non-audio upload is a cheap honest 422 (mirrors studio.py's image/* gate)
    — never reaches llm.transcribe. Also shrinks the header-injection surface."""
    _configure_stt(monkeypatch)
    called = {"n": 0}
    monkeypatch.setattr(
        llm, "transcribe", lambda *a, **k: called.__setitem__("n", called["n"] + 1) or "x"
    )
    resp = client.post(
        "/api/transcribe",
        files={"file": ("notes.txt", b"not audio", "text/plain")},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == "Upload an audio recording."
    assert called["n"] == 0


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


def test_transcribe_empty_transcript_records_error_telemetry(client, monkeypatch):
    """An empty/whitespace transcript is a non-ok outcome — pinned as "error"
    (the contract's only two outcomes are ok/error)."""
    _configure_stt(monkeypatch)
    monkeypatch.setattr(llm, "transcribe", lambda data, mime, filename: "   ")

    resp = client.post(
        "/api/transcribe",
        files={"file": ("silence.webm", b"fake-audio-bytes", "audio/webm")},
    )
    assert resp.status_code == 422, resp.text

    with db._conn() as c:
        rows = c.execute(
            "SELECT outcome, provider FROM gen_events WHERE kind = 'transcribe'"
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


def test_llm_transcribe_sanitizes_filename_header_injection(monkeypatch):
    """A CR/LF in the client-supplied filename must NOT smuggle an extra form
    field into the multipart body POSTed to the operator's STT server. The body
    must contain EXACTLY ONE file part and no injected field."""
    monkeypatch.setenv("TRUS_STT_BASE_URL", "http://h/v1")
    monkeypatch.setenv("TRUS_STT_MODEL", "whisper-1")
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["body"] = req.data
        return _FakeResp({"text": "ok"})

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
    # Attempt to close the file part and open a "language" field.
    evil = 'r.webm"\r\nContent-Disposition: form-data; name="language"\r\n\r\nen\r\n--x'
    llm.transcribe(b"data", "audio/webm", evil)

    body = captured["body"]
    # A boundary-preceded header line always reads `\r\nContent-Disposition:`; only
    # the two legitimate parts (model, file) produce it. The injected one lost its
    # CRLF, so it can't materialize as a third part.
    assert body.count(b"\r\nContent-Disposition:") == 2
    assert b'name="language"' not in body  # quoted field name (how a real field appears)
    assert b"\r\nen\r\n" not in body  # the smuggled value never lands as its own part


def test_llm_transcribe_sanitizes_mime_header_injection(monkeypatch):
    """Same guard for a CR/LF-bearing content_type spliced into the Content-Type
    header line."""
    monkeypatch.setenv("TRUS_STT_BASE_URL", "http://h/v1")
    monkeypatch.setenv("TRUS_STT_MODEL", "whisper-1")
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["body"] = req.data
        return _FakeResp({"text": "ok"})

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
    evil_mime = 'audio/webm\r\nContent-Disposition: form-data; name="language"\r\n\r\nen'
    llm.transcribe(b"data", evil_mime, "r.webm")

    body = captured["body"]
    assert b'name="language"' not in body  # quoted field name (how a real field appears)
    # Only the two legitimate boundary-preceded header lines survive; the CRLF-
    # stripped injection collapses inertly onto the Content-Type value line.
    assert body.count(b"\r\nContent-Disposition:") == 2


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


# ---------------------------------------------------------------------------
# Stage-2b backlog: per-owner sliding-window rate limit (≤20 / 5 min) → 429.
# ---------------------------------------------------------------------------


def test_rate_limiter_allows_up_to_max_then_blocks():
    from src.routes.transcribe import _RateLimiter

    limiter = _RateLimiter(max_calls=3, window_secs=60)
    assert limiter.allow("a", now=1000.0)
    assert limiter.allow("a", now=1000.0)
    assert limiter.allow("a", now=1000.0)
    assert not limiter.allow("a", now=1000.0)


def test_rate_limiter_sliding_window_expires_old_hits():
    from src.routes.transcribe import _RateLimiter

    limiter = _RateLimiter(max_calls=1, window_secs=10)
    assert limiter.allow("a", now=0.0)
    assert not limiter.allow("a", now=5.0)
    assert limiter.allow("a", now=11.0)  # the first hit has slid out of the window


def test_rate_limiter_is_independent_per_key():
    from src.routes.transcribe import _RateLimiter

    limiter = _RateLimiter(max_calls=1, window_secs=60)
    assert limiter.allow("a", now=0.0)
    assert limiter.allow("b", now=0.0)  # a different key is unaffected
    assert not limiter.allow("a", now=1.0)


def test_rate_limiter_evicts_idle_keys():
    """A key whose window has fully expired must not leave an empty list behind
    in the internal map — per-owner rows would otherwise accumulate forever.
    The invariant: the map never holds an empty list for any key."""
    from src.routes.transcribe import _RateLimiter

    limiter = _RateLimiter(max_calls=1, window_secs=10)
    assert limiter.allow("a", now=0.0)
    assert "a" in limiter._hits
    # Window fully expires; the next call for "a" trims its stale hit to empty
    # and evicts the entry before re-adding, so no empty list ever lingers.
    assert limiter.allow("a", now=100.0)
    assert limiter._hits["a"] == [100.0]  # exactly one fresh hit, no stale residue
    assert all(hits for hits in limiter._hits.values())  # never an empty list


def test_rate_limiter_parallel_same_key_evictions_never_raise():
    """/transcribe and /live are sync (threadpool) routes and /live fires several
    parallel same-owner calls on page load. The eviction step used to `del
    self._hits[key]` on a shared dict — two callers racing the check-then-del
    could KeyError → 500. With `pop(key, None)` under a lock the shared
    read-modify-write is atomic, so hammering parallel same-key calls that expire
    the window every iteration must never surface an exception."""
    import threading

    from src.routes.transcribe import _RateLimiter

    limiter = _RateLimiter(max_calls=1, window_secs=10)
    errors: list[Exception] = []
    start = threading.Barrier(16)

    def worker() -> None:
        start.wait()  # release all threads at once to maximize interleaving
        try:
            for t in range(200):
                # Each call's `now` jumps a full window past the last, so every
                # call trims the shared list to empty and hits the evict branch.
                limiter.allow("shared", now=float(t * 100))
        except Exception as e:  # a raced KeyError would land here
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(16)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    assert not errors, f"eviction raced into an error: {errors[:3]}"
    assert all(hits for hits in limiter._hits.values())  # never an empty list


def test_transcribe_21st_call_in_window_is_429(client, monkeypatch):
    _configure_stt(monkeypatch)
    monkeypatch.setattr(llm, "transcribe", lambda data, mime, filename: "ok")
    for _ in range(20):
        resp = client.post(
            "/api/transcribe", files={"file": ("r.webm", b"fake-audio-bytes", "audio/webm")}
        )
        assert resp.status_code == 200, resp.text
    resp = client.post(
        "/api/transcribe", files={"file": ("r.webm", b"fake-audio-bytes", "audio/webm")}
    )
    assert resp.status_code == 429, resp.text
    assert "too many" in resp.json()["detail"].lower()


def test_transcribe_rate_limit_is_per_owner(client, monkeypatch):
    """A different owner (a separate session/cookie jar) is unaffected by
    another owner's exhausted rate limit."""
    _configure_stt(monkeypatch)
    monkeypatch.setattr(llm, "transcribe", lambda data, mime, filename: "ok")
    for _ in range(20):
        resp = client.post(
            "/api/transcribe", files={"file": ("r.webm", b"fake-audio-bytes", "audio/webm")}
        )
        assert resp.status_code == 200, resp.text
    resp = client.post(
        "/api/transcribe", files={"file": ("r.webm", b"fake-audio-bytes", "audio/webm")}
    )
    assert resp.status_code == 429, resp.text

    with TestClient(app) as other:
        resp2 = other.post(
            "/api/transcribe", files={"file": ("r.webm", b"fake-audio-bytes", "audio/webm")}
        )
        assert resp2.status_code == 200, resp2.text
