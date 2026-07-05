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
import time

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from src import db, llm
from src.routes.deps import _llm_error_detail, _owner_id, _RateLimiter, _require_trusted_origin
from src.schema import LLMError

router = APIRouter()

_MAX_BYTES = 25 * 1024 * 1024

# R-204 backlog: ≤20 transcribes / 5 min per owner — cheap abuse guard on a
# cost-bearing endpoint. _RateLimiter now lives in routes/deps.py (Stage 4:
# modules.py became a third importer alongside this file and live.py, so a
# shared deps module is the more sensible home than one specific route file).
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
