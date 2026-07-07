"""Per-surface read-only sharing (SHARE-1..3)."""

import os

from fastapi import APIRouter, HTTPException, Request

from src import db
from src.routes.deps import _owner_id, _RateLimiter
from src.schema import SharedModule, SharedPage, SharedPageResponse, ShareStatus

router = APIRouter()


# Fresh-per-call env knobs (the _gen_rate_max pattern) — never import-time constants.
def _share_rate_max() -> int:
    return int(os.environ.get("TRUS_SHARE_RATE_MAX", "60"))


def _share_rate_window() -> float:
    return float(os.environ.get("TRUS_SHARE_RATE_WINDOW", "60"))


# Its own limiter instance — anonymous readers must never eat an owner's
# generation/live/transcribe budget. No LLM call happens on this path, so
# _check_gen_budget is deliberately not involved.
_share_limiter = _RateLimiter(max_calls=60, window_secs=60)


# ── Owner-gated management (session cookie via _owner_id; foreign page ≡ 404) ──


@router.post("/pages/{page_id}/share", response_model=ShareStatus, status_code=201)
async def create_share(page_id: str, request: Request) -> ShareStatus:
    """Create-or-rotate: calling again mints a new token and kills the old."""
    sid = _owner_id(request)
    created = db.share_create(sid, page_id)
    if created is None:
        raise HTTPException(status_code=404, detail="Page not found")
    return ShareStatus(active=True, token=created["token"], created_at=created["created_at"])


@router.get("/pages/{page_id}/share", response_model=ShareStatus)
async def get_share(page_id: str, request: Request) -> ShareStatus:
    sid = _owner_id(request)
    if db.get_page(sid, page_id) is None:
        raise HTTPException(status_code=404, detail="Page not found")
    status = db.share_status(sid, page_id)
    if status is None:
        return ShareStatus(active=False)
    return ShareStatus(active=True, token=status["token"], created_at=status["created_at"])


@router.delete("/pages/{page_id}/share", status_code=204)
async def revoke_share(page_id: str, request: Request) -> None:
    sid = _owner_id(request)
    if db.get_page(sid, page_id) is None:
        raise HTTPException(status_code=404, detail="Page not found")
    db.share_revoke(sid, page_id)  # idempotent: 204 even when already inactive


# ── The public read path — the ONLY route that accepts a token; reads only ──


@router.get("/share/{token}", response_model=SharedPageResponse)
async def read_shared(token: str, request: Request) -> SharedPageResponse:
    """NO session: never reads request.session, never calls _owner_id — no
    Set-Cookie is emitted, no sessions row is minted, and it works under
    TRUS_ALLOW_ANON=0. Unknown, revoked, rotated-away, cascade-deleted, and
    revoked-owner tokens all return the identical 404."""
    key = request.client.host if request.client else "unknown"
    if not _share_limiter.allow(key, max_calls=_share_rate_max(), window_secs=_share_rate_window()):
        raise HTTPException(status_code=429, detail="Too many requests.")
    link = db.share_resolve(token)
    if link is None:
        raise HTTPException(status_code=404, detail="Not found")
    mods = db.list_modules(link["owner"], link["page_id"])  # non-archived only (default)
    out = []
    for m in mods:
        cfg = m.config.model_copy(deep=True)
        # Strip live bindings server-side (defense in depth): DataSource.query
        # can carry location-like data, and the public view never fetches live
        # values anyway (/api/live is session-gated). Typed strip — every
        # component class that can carry one has the field by name.
        for comp in cfg.components:
            # Only Metric/Kpi/Ring/Gauge/ProgressBar declare data_source; the
            # getattr guard skips the rest, so this assignment is always valid.
            if getattr(comp, "data_source", None) is not None:
                comp.data_source = None  # type: ignore[union-attr]
        out.append(SharedModule(id=m.id, config=cfg, updated_at=m.updated_at))
    return SharedPageResponse(page=SharedPage(name=link["name"], icon=link["icon"]), modules=out)
