from fastapi import APIRouter, Query, Request

from src import db
from src.schema import Message

router = APIRouter()


def _session_id(request: Request) -> str:
    from src.routes.modules import _session_id as _sid

    return _sid(request)


@router.get("/conversations", response_model=list[Message])
async def list_conversation(
    request: Request,
    page_id: str | None = Query(default=None),
) -> list[Message]:
    sid = _session_id(request)
    return db.list_messages(sid, page_id=page_id)


@router.delete("/conversations", status_code=204)
async def clear_conversation(
    request: Request,
    page_id: str | None = Query(default=None),
) -> None:
    sid = _session_id(request)
    db.clear_messages(sid, page_id=page_id)
