"""Shared route dependencies."""

import os

from fastapi import HTTPException, Request

from src import db


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
