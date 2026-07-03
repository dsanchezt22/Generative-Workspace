"""Shared route dependencies."""

import logging
import os

from fastapi import HTTPException, Request

from src import db
from src.schema import LLMError

_logger = logging.getLogger(__name__)


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
