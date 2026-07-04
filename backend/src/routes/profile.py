"""Evolving user profile store (R-801/R-802) — a real, inspectable surface for
what Trus has learned about an owner. All routes are owner-gated via
`_owner_id` (R-903): every read/write is scoped to the caller's own facts."""

from fastapi import APIRouter, HTTPException, Request

from src import db
from src.routes.deps import _owner_id
from src.schema import ProfileAddRequest, ProfileUpdateRequest, UserProfileEntry

router = APIRouter()


@router.get("/profile", response_model=list[UserProfileEntry])
async def list_profile(request: Request) -> list[dict]:
    sid = _owner_id(request)
    return db.profile_list(sid)


@router.post("/profile", response_model=UserProfileEntry, status_code=201)
async def add_profile(body: ProfileAddRequest, request: Request) -> dict:
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Text cannot be empty")
    sid = _owner_id(request)
    return db.profile_add(sid, body.kind, text, source="manual")


@router.patch("/profile/{profile_id}", response_model=UserProfileEntry)
async def update_profile(profile_id: str, body: ProfileUpdateRequest, request: Request) -> dict:
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Text cannot be empty")
    sid = _owner_id(request)
    updated = db.profile_update(sid, profile_id, text)
    if updated is None:
        raise HTTPException(status_code=404, detail="Profile entry not found")
    return updated


@router.delete("/profile/{profile_id}", status_code=204)
async def delete_profile(profile_id: str, request: Request) -> None:
    sid = _owner_id(request)
    if not db.profile_delete(sid, profile_id):
        raise HTTPException(status_code=404, detail="Profile entry not found")


@router.delete("/profile")
async def clear_profile(request: Request) -> dict:
    sid = _owner_id(request)
    return {"deleted": db.profile_clear(sid)}
