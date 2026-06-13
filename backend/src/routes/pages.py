from fastapi import APIRouter, HTTPException, Request

from src import db
from src.schema import CreatePageRequest, Page, RenamePageRequest

router = APIRouter()


def _session_id(request: Request) -> str:
    from src.routes.modules import _session_id as _sid
    return _sid(request)


@router.get("/pages", response_model=list[Page])
async def list_pages(request: Request) -> list[Page]:
    sid = _session_id(request)
    pages = db.list_pages(sid)
    if not pages:
        return [db.ensure_default_page(sid)]
    return pages


@router.post("/pages", response_model=Page, status_code=201)
async def create_page(body: CreatePageRequest, request: Request) -> Page:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Page name cannot be empty")
    sid = _session_id(request)
    return db.create_page(sid, name)


@router.patch("/pages/{page_id}", response_model=Page)
async def rename_page(page_id: str, body: RenamePageRequest, request: Request) -> Page:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Page name cannot be empty")
    sid = _session_id(request)
    updated = db.rename_page(sid, page_id, name)
    if updated is None:
        raise HTTPException(status_code=404, detail="Page not found")
    return updated


@router.delete("/pages/{page_id}", status_code=204)
async def delete_page(page_id: str, request: Request) -> None:
    sid = _session_id(request)
    ok = db.delete_page(sid, page_id)
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete the last page, or page not found.",
        )
