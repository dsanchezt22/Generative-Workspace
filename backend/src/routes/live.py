"""GET /api/live/{provider} (R-701/R-704): the frontend's live-value refresh
hook calls this for any component carrying a `data_source`. Owner-gated
(`_owner_id`) and rate-limited (reuses routes/deps.py's generic `_RateLimiter`
— the pattern that helper was built for). `TRUS_LIVE_DATA=off` short-circuits
to a disabled marker so components fall back to manual entry instead of
erroring; this is a GET with no state-changing side effect, so (per
`_require_trusted_origin`'s own docstring) the CSRF origin gate doesn't apply.
"""

import os

from fastapi import APIRouter, HTTPException, Query, Request

from src.routes.deps import _owner_id, _RateLimiter
from src.services import live_data

router = APIRouter()

# Cheap abuse guard on an outbound-fetching endpoint (mirrors transcribe.py's
# rate limiter, sized more generously since a live value can be polled often).
_live_limiter = _RateLimiter(max_calls=60, window_secs=5 * 60)


def _live_data_enabled() -> bool:
    return os.environ.get("TRUS_LIVE_DATA", "on").strip().lower() not in ("off", "0", "false", "no")


@router.get("/live/{provider}")
def get_live_value(
    provider: str,
    request: Request,
    lat: float | None = Query(default=None),
    lon: float | None = Query(default=None),
    place: str | None = Query(default=None),
    food: str | None = Query(default=None),
    refresh_secs: int = Query(default=600, ge=60, le=86400),
) -> dict:
    sid = _owner_id(request)
    if not _live_limiter.allow(sid):
        raise HTTPException(
            status_code=429,
            detail="Too many live-data requests — wait a few minutes and try again.",
        )
    if not _live_data_enabled():
        return {
            "value": None,
            "unit": None,
            "as_of": None,
            "source": provider,
            "stale": False,
            # `disabled` is the structured off-mode signal the frontend keys on
            # (R-701 hardening); the human-readable `error` string is kept for
            # back-compat but nothing should string-match it — it's free to be
            # reworded.
            "disabled": True,
            "error": "Live data is disabled",
        }
    if provider not in live_data.ALLOWED_PROVIDERS:
        raise HTTPException(status_code=422, detail=f"Unknown live-data provider: {provider}")
    if provider == "nutrition":
        if not food:
            raise HTTPException(status_code=422, detail="Provide a food name.")
        query: dict[str, str | float] = {"food": food}
    elif place:
        query = {"place": place}
    elif lat is not None and lon is not None:
        query = {"lat": lat, "lon": lon}
    else:
        raise HTTPException(status_code=422, detail="Provide lat & lon, or a place name.")
    return live_data.fetch(provider, query, refresh_secs=refresh_secs)
