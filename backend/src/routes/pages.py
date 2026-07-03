from fastapi import APIRouter, HTTPException, Request

from src import db
from src.routes.deps import _owner_id
from src.schema import CreatePageRequest, Page, RenamePageRequest, ReorderPagesRequest

router = APIRouter()


@router.get("/pages", response_model=list[Page])
async def list_pages(request: Request) -> list[Page]:
    sid = _owner_id(request)
    pages = db.list_pages(sid)
    if not pages:
        return [db.ensure_default_page(sid)]
    return pages


@router.post("/pages", response_model=Page, status_code=201)
async def create_page(body: CreatePageRequest, request: Request) -> Page:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Page name cannot be empty")
    sid = _owner_id(request)
    return db.create_page(sid, name, icon=body.icon, parent_id=body.parent_id)


def _would_loop(sid: str, page_id: str, parent_id: str | None) -> bool:
    """True if making page_id a child of parent_id would create a cycle."""
    if parent_id is None:
        return False
    if parent_id == page_id:
        return True
    pages = {p.id: p for p in db.list_pages(sid)}
    cur = pages.get(parent_id)
    seen = 0
    while cur is not None and seen < 1000:
        if cur.id == page_id:
            return True
        cur = pages.get(cur.parent_id) if cur.parent_id else None
        seen += 1
    return False


@router.patch("/pages/{page_id}", response_model=Page)
async def update_page(page_id: str, body: RenamePageRequest, request: Request) -> Page:
    sid = _owner_id(request)
    fields = body.model_fields_set
    kwargs: dict[str, str | None] = {}
    if "name" in fields:
        name = (body.name or "").strip()
        if not name:
            raise HTTPException(status_code=422, detail="Page name cannot be empty")
        kwargs["name"] = name
    if "icon" in fields:
        kwargs["icon"] = body.icon
    if "parent_id" in fields:
        if _would_loop(sid, page_id, body.parent_id):
            raise HTTPException(status_code=409, detail="A page can't be placed inside itself.")
        kwargs["parent_id"] = body.parent_id
    updated = db.update_page(sid, page_id, **kwargs)
    if updated is None:
        raise HTTPException(status_code=404, detail="Page not found")
    return updated


@router.post("/pages/reorder", response_model=list[Page])
async def reorder_pages(body: ReorderPagesRequest, request: Request) -> list[Page]:
    sid = _owner_id(request)
    return db.reorder_pages(sid, body.ordered_ids)


@router.delete("/pages/{page_id}", status_code=204)
async def delete_page(page_id: str, request: Request) -> None:
    sid = _owner_id(request)
    ok = db.delete_page(sid, page_id)
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete the last page, or page not found.",
        )
