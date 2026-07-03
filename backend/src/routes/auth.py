"""Invite claim + claim-state endpoints (R-901-905)."""

import os

from fastapi import APIRouter, HTTPException, Request

from src import db

router = APIRouter()


@router.get("/auth/claim")
def claim(token: str, request: Request) -> dict:
    user = db.user_by_token(token)
    if user is None:
        raise HTTPException(status_code=404, detail="Unknown invite")
    if user["revoked_at"]:
        raise HTTPException(status_code=403, detail="Invite revoked")
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
