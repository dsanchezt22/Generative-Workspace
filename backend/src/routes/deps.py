"""Shared route dependencies."""

import logging
import os
import threading
import time

from fastapi import HTTPException, Request

from src import db
from src.schema import LLMError

_logger = logging.getLogger(__name__)


class _RateLimiter:
    """A per-key, in-memory sliding-window limiter: at most `max_calls` calls
    per `window_secs` for a given key (both overridable per-`allow()` call —
    see below). Deliberately generic (not hardcoded to "owner"). Process-local
    only (fine for the MVP's single-instance deployment; a multi-instance
    deploy would need a shared store instead).

    Lives here (not in one specific route file) because three route modules
    now share it: transcribe.py (Stage 2b, where this was first built), live.py
    (Stage 3), and modules.py (Stage 4's generate-route limiter, R-1202)."""

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

    def allow(
        self,
        key: str,
        now: float | None = None,
        max_calls: int | None = None,
        window_secs: float | None = None,
    ) -> bool:
        """`max_calls`/`window_secs` override the instance defaults for this one
        call (added for modules.py's generate limiter, whose TRUS_GEN_RATE_MAX/
        WINDOW must be re-read from the environment on every request rather than
        baked in at import time — the same reason semantic_cache.py's thresholds
        are read via a function instead of a module-level constant: a value read
        once at import can't be overridden by a test's per-test env isolation,
        which runs before each test body but after collection-time imports).
        transcribe.py/live.py don't pass these, so their behavior is unchanged."""
        now = time.monotonic() if now is None else now
        max_calls = self._max_calls if max_calls is None else max_calls
        window_secs = self._window_secs if window_secs is None else window_secs
        with self._lock:
            hits = self._hits.setdefault(key, [])
            cutoff = now - window_secs
            while hits and hits[0] < cutoff:
                hits.pop(0)
            if not hits:
                # An idle key whose window has fully expired: drop its (now empty)
                # entry so per-owner rows don't accumulate forever. Re-added below
                # if this call is allowed. `pop(key, None)` (not `del`) is
                # idempotent — safe even if a concurrent call already evicted it.
                self._hits.pop(key, None)
            if len(hits) >= max_calls:
                return False
            hits.append(now)
            self._hits[key] = hits
            return True


def _parse_cors_origins(raw: str) -> list[str]:
    """Comma-separated origin list, tolerant of whitespace/trailing commas/blanks.

    Single source of truth: main.py imports this for the CORS middleware, and
    `_require_trusted_origin` below uses it directly — previously each kept its
    own copy. Defined HERE (not in main.py) so both directions work: main.py
    can import from this module, but this module importing from main.py would
    be circular (main imports routes.modules/routes.studio, which import this
    module, before main.py finishes defining anything)."""
    return [o.strip() for o in raw.split(",") if o.strip()]


def _llm_error_detail(e: LLMError) -> str:
    """Map an internal LLMError to a small set of safe, honest client messages.

    LLMError messages can embed the internal endpoint URL and up to 400 chars of an
    upstream response body (see llm.py), so the raw text is logged server-side and
    NEVER returned to the client. Status stays 503 at the call sites (R-1104)."""
    raw = str(e)
    _logger.warning("LLM error (returned to client as sanitized 503): %s", raw)
    low = raw.lower()
    if any(s in low for s in ("could not reach", "unreachable", "timed out", "timeout")):
        return "The AI model endpoint is unreachable right now. Please try again in a moment."
    if any(s in low for s in ("offline", "set trus_llm_base_url", "template mode", "stub")):
        return "No live AI model is configured. Configure a model to use AI generation."
    if any(
        s in low for s in ("empty response", "unexpected", "non-json", "returned http", "invalid")
    ):
        return "The AI model returned an unusable response. Please try again."
    return "AI generation is temporarily unavailable. Please try again in a moment."


def _require_trusted_origin(request: Request) -> None:
    """CSRF gate for state-changing multipart endpoints (Stage-1 review decision A).

    Multipart POSTs are CORS-'simple': with SameSite=None cookies a malicious
    page can send credentialed FormData cross-site without a preflight. If the
    browser declares a cross-site Origin that isn't ours, refuse. Requests
    without an Origin header (curl, same-origin) pass — the browser vector is
    the one being closed.

    Parses TRUS_CORS_ORIGINS via `_parse_cors_origins` above (same rules the
    CORS middleware in main.py uses)."""
    origin = request.headers.get("origin")
    if not origin:
        return
    allowed = _parse_cors_origins(os.environ.get("TRUS_CORS_ORIGINS", "http://localhost:3000"))
    if origin not in allowed:
        raise HTTPException(status_code=403, detail="Cross-site upload refused")


def _owner_id(request: Request) -> str:
    """The data-owner key: the claimed user id, else (dev only) the anonymous sid.

    With TRUS_ALLOW_ANON != "1", an unclaimed request is refused with 401 — no
    reads, writes, or model spend without an invite (R-901). A revoked or deleted
    user is re-checked on every request and bounced back to the gate (R-905)."""
    uid = request.session.get("uid")
    if uid:
        user = db.user_by_id(uid)
        if user and not user["revoked_at"]:
            return str(uid)
        request.session.pop("uid", None)  # revoked or deleted → back to the gate
    if os.environ.get("TRUS_ALLOW_ANON", "1") == "1":
        sid = db.ensure_session(request.session.get("sid"))
        request.session["sid"] = sid
        return sid
    raise HTTPException(status_code=401, detail="Invite required")
