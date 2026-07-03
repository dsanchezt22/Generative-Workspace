"""Per-owner usage-seeded suggestions (R-104 half): recent distinct prompts
drawn from this owner's own generation cache + conversation history — no
model spend, no telemetry, R-903-scoped (see db.suggestion_prompts)."""

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from src import db
from src.routes.deps import _owner_id

router = APIRouter()


class Suggestion(BaseModel):
    prompt: str


@router.get("/suggestions", response_model=list[Suggestion])
async def suggestions(
    request: Request,
    limit: int = Query(default=5),
) -> list[Suggestion]:
    owner = _owner_id(request)
    clamped = max(1, min(10, limit))
    return [Suggestion(prompt=p) for p in db.suggestion_prompts(owner, clamped)]
