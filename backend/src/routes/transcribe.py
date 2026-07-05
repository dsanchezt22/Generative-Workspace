"""POST /api/transcribe (R-201/R-204 half): pluggable voice transcription.

New file (not routes/modules.py): transcription isn't a ModuleConfig concern,
takes no `page_id`/existing-modules context, and has its own telemetry shape
(kind="transcribe", provider="stt" — no `llm.last_call`, since transcription
is not a "generation"). Mirrors routes/suggestions.py's precedent of one small
file per new capability rather than growing modules.py further.

Unset TRUS_STT_BASE_URL/MODEL is an honest, non-cost 422 (I-1 config-not-code)
checked BEFORE the upload is read — no wasted read for a request that can
never succeed.
"""

import contextlib
import os
import threading
import time

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from src import db, llm
from src.routes.deps import _llm_error_detail, _owner_id, _require_trusted_origin
from src.schema import LLMError

router = APIRouter()

_MAX_BYTES = 25 * 1024 * 1024


class _RateLimiter:
    """A per-key, in-memory sliding-window limiter: at most `max_calls` calls
    per `window_secs` for a given key. Deliberately generic (not hardcoded to
    "owner") — the generate/preview routes are the next customer for the same
    pattern, each with their own instance + limits. Process-local only (fine
    for the MVP's single-instance deployment; a multi-instance deploy would
    need a shared store instead)."""

    def __init__(self, max_calls: int, window_secs: float) -> None:
        self._max_calls = max_calls
        self._window_secs = window_secs
        self._hits: dict[str, list[float]] = {}
        # These routes are sync (threadpool) and /live fires several parallel
        # same-owner calls on page load — the shared `_hits` dict and its per-key
        # lists are touched non-atomically (setdefault→trim→evict→append), so a
        # bare check-then-`del` could race two callers into a KeyError→500. One
        # lock makes the whole read-modify-write atomic; it's trivially cheap.
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits.setdefault(key, [])
            cutoff = now - self._window_secs
            while hits and hits[0] < cutoff:
                hits.pop(0)
            if not hits:
                # An idle key whose window has fully expired: drop its (now empty)
                # entry so per-owner rows don't accumulate forever. Re-added below
                # if this call is allowed. `pop(key, None)` (not `del`) is
                # idempotent — safe even if a concurrent call already evicted it.
                self._hits.pop(key, None)
            if len(hits) >= self._max_calls:
                return False
            hits.append(now)
            self._hits[key] = hits
            return True


# R-204 backlog: ≤20 transcribes / 5 min per owner — cheap abuse guard on a
# cost-bearing endpoint.
_transcribe_limiter = _RateLimiter(max_calls=20, window_secs=5 * 60)


class TranscriptionResponse(BaseModel):
    text: str


def _track_transcribe(sid: str, outcome: str, t0: float) -> None:
    """Records a gen_event for a transcription attempt. Transcription never
    touches `llm.last_call` (it isn't a "generation"), so this can't reuse the
    shared `_track` contextmanager in routes/modules.py, which reads last_call
    for provider/model/tokens. Best-effort, mirrors `_track`'s suppression —
    a telemetry failure must never break the response to the user."""
    with contextlib.suppress(Exception):  # pragma: no cover - logging must not fail the request
        db.add_gen_event(
            sid,
            "transcribe",
            outcome,
            "stt",
            os.environ.get("TRUS_STT_MODEL", "").strip(),
            int((time.monotonic() - t0) * 1000),
            None,
            None,
        )


@router.post("/transcribe", response_model=TranscriptionResponse)
def transcribe_audio(request: Request, file: UploadFile = File(...)) -> TranscriptionResponse:
    _require_trusted_origin(request)
    sid = _owner_id(request)
    if not _transcribe_limiter.allow(sid):
        raise HTTPException(
            status_code=429,
            detail="Too many transcriptions — wait a few minutes and try again.",
        )
    if not llm.stt_available():
        raise HTTPException(
            status_code=422,
            detail="Voice transcription needs a configured model — set TRUS_STT_* or type instead.",
        )
    mime = file.content_type or "application/octet-stream"
    # Only accept audio uploads (mirrors studio.py's image/* gate): a cheap honest
    # 422 for the wrong file, and it shrinks the header-injection surface — an
    # audio/* content_type can't carry the CR/LF a smuggled form field needs.
    if not mime.startswith("audio/"):
        raise HTTPException(status_code=422, detail="Upload an audio recording.")
    # Cap the read before materializing the whole upload in memory: read one byte
    # past the limit so the size check below still fires for oversized files.
    data = file.file.read(_MAX_BYTES + 1)
    if len(data) > _MAX_BYTES:
        raise HTTPException(status_code=413, detail="That recording is too large (max 25MB).")

    t0 = time.monotonic()
    try:
        text = llm.transcribe(data, mime, file.filename)
    except LLMError as e:
        _track_transcribe(sid, "error", t0)
        raise HTTPException(status_code=503, detail=_llm_error_detail(e)) from None
    if not text.strip():
        _track_transcribe(sid, "error", t0)
        raise HTTPException(
            status_code=422, detail="The recording didn't contain recognizable speech."
        )
    _track_transcribe(sid, "ok", t0)
    return TranscriptionResponse(text=text)
