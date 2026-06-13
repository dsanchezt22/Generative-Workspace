from fastapi import APIRouter, HTTPException, Request

from src import db
from src.schema import (
    GenerateRequest,
    GenerateResponse,
    PatchRequest,
    RefusalError,
    StoredModule,
)
from src.services import orchestrator

router = APIRouter()


def _session_id(request: Request) -> str:
    sid = request.session.get("sid")
    sid = db.ensure_session(sid)
    request.session["sid"] = sid
    return sid


@router.post("/modules/generate", response_model=GenerateResponse)
async def generate_module(body: GenerateRequest, request: Request) -> GenerateResponse:
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="Prompt cannot be empty")
    sid = _session_id(request)
    try:
        config = orchestrator.generate_module(prompt)
    except RefusalError as e:
        raise HTTPException(status_code=422, detail={"refusal": e.reason})
    stored = db.insert_module(sid, config)
    return GenerateResponse(module=stored)


@router.get("/modules", response_model=list[StoredModule])
async def list_modules(request: Request) -> list[StoredModule]:
    sid = _session_id(request)
    return db.list_modules(sid)


@router.patch("/modules/{module_id}", response_model=StoredModule)
async def patch_module(module_id: str, body: PatchRequest, request: Request) -> StoredModule:
    sid = _session_id(request)
    updated = db.update_module(sid, module_id, body.config)
    if updated is None:
        raise HTTPException(status_code=404, detail="Module not found")
    return updated
