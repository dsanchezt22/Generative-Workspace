from fastapi import APIRouter, Query, Request

from src import db
from src.routes.deps import _owner_id
from src.schema import Message

router = APIRouter()


@router.get("/conversations", response_model=list[Message])
async def list_conversation(
    request: Request,
    page_id: str | None = Query(default=None),
) -> list[Message]:
    sid = _owner_id(request)
    return db.list_messages(sid, page_id=page_id)


@router.delete("/conversations", status_code=204)
async def clear_conversation(
    request: Request,
    page_id: str | None = Query(default=None),
) -> None:
    sid = _owner_id(request)
    db.clear_messages(sid, page_id=page_id)
