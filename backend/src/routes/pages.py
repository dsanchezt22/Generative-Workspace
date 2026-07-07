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


@router.get("/pages/counts", response_model=dict[str, int])
async def page_module_counts(request: Request) -> dict[str, int]:
    """Live module count per page (R-502): the portal tiles' cheap "N tools"
    preview without loading any child page's module configs. Owner-scoped."""
    return db.page_module_counts(_owner_id(request))


def _require_own_parent(sid: str, parent_id: str | None) -> None:
    """R-503: a non-null parent_id must be a page THIS owner has (a dangling or
    foreign parent makes the page invisible in the sidebar tree + portal layer).
    db.get_page is owner-scoped, so another owner's page id is treated exactly
    like a nonexistent one → the same 422, never a hint that the id exists."""
    if parent_id is not None and db.get_page(sid, parent_id) is None:
        raise HTTPException(status_code=422, detail="Parent page not found.")


@router.post("/pages", response_model=Page, status_code=201)
async def create_page(body: CreatePageRequest, request: Request) -> Page:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Page name cannot be empty")
    sid = _owner_id(request)
    _require_own_parent(sid, body.parent_id)
    return db.create_page(sid, name, icon=body.icon, parent_id=body.parent_id, accent=body.accent)


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
    kwargs: dict[str, str | float | None] = {}
    if "name" in fields:
        name = (body.name or "").strip()
        if not name:
            raise HTTPException(status_code=422, detail="Page name cannot be empty")
        kwargs["name"] = name
    if "icon" in fields:
        kwargs["icon"] = body.icon
    if "accent" in fields:
        kwargs["accent"] = body.accent
    if "parent_id" in fields:
        _require_own_parent(sid, body.parent_id)
        if _would_loop(sid, page_id, body.parent_id):
            raise HTTPException(status_code=409, detail="A page can't be placed inside itself.")
        kwargs["parent_id"] = body.parent_id
    # R-504: portal placement is owner-scoped in db.update_page (WHERE session_id).
    if "portal_x" in fields:
        kwargs["portal_x"] = body.portal_x
    if "portal_y" in fields:
        kwargs["portal_y"] = body.portal_y
    # R-504 completion: the page's own viewport (pan/zoom) — owner-scoped the same way.
    if "view_x" in fields:
        kwargs["view_x"] = body.view_x
    if "view_y" in fields:
        kwargs["view_y"] = body.view_y
    if "view_zoom" in fields:
        kwargs["view_zoom"] = body.view_zoom
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
