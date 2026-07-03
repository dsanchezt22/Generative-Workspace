"""Invite claim + claim-state endpoints (R-901-905).

Claiming is POST-only: a GET (link previewers, crawlers, or an attacker-forced
navigation to a shared invite link) must never mutate who a browser is signed in
as, or adopt its anonymous work into someone else's account.
"""

import os

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src import db

router = APIRouter()


class ClaimRequest(BaseModel):
    token: str
    confirm: bool = False


def _valid_user_or_raise(token: str) -> dict:
    user = db.user_by_token(token)
    if user is None:
        raise HTTPException(status_code=404, detail="Unknown invite")
    if user["revoked_at"]:
        raise HTTPException(status_code=403, detail="Invite revoked")
    return user


@router.get("/auth/claim")
def preview_claim(token: str) -> dict:
    """READ-ONLY invite check (no session write, no adoption) — safe for the
    claim page to call on load. 404 unknown / 403 revoked, as on POST."""
    user = _valid_user_or_raise(token)
    return {"valid": True, "name": user["name"]}


@router.post("/auth/claim")
def claim(body: ClaimRequest, request: Request) -> dict:
    user = _valid_user_or_raise(body.token)
    current_uid = request.session.get("uid")
    if current_uid and current_uid != user["id"]:
        current = db.user_by_id(current_uid)
        if current and not current["revoked_at"]:
            # The session already belongs to a live, DIFFERENT user: refuse to
            # silently rebind (an attacker-shared link must not hijack a session).
            if not body.confirm:
                raise HTTPException(status_code=409, detail={"rebind": current["name"]})
            # Confirmed account switch: swap the uid only. NO adoption — the
            # previous user's data is keyed by their uid (never by this
            # browser's sid), so nothing of theirs may move to the new user.
            request.session["uid"] = user["id"]
            return {"ok": True, "name": user["name"]}
        # Stale uid (revoked/deleted user) → treat the session as unclaimed.
    old_sid = request.session.get("sid")
    request.session["uid"] = user["id"]
    if old_sid:
        db.adopt_session_data(old_sid, user["id"])  # keep pre-claim anonymous work
    return {"ok": True, "name": user["name"]}


@router.get("/auth/me")
def me(request: Request) -> dict:
    uid = request.session.get("uid")
    user = db.user_by_id(uid) if uid else None
    if user and not user["revoked_at"]:
        return {"claimed": True, "name": user["name"]}
    return {"claimed": os.environ.get("TRUS_ALLOW_ANON", "1") == "1", "name": None}
