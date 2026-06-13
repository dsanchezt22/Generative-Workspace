from fastapi import APIRouter, HTTPException, Request

from src import db
from src.schema import (
    GenerateRequest,
    GenerateResponse,
    LLMError,
    ModuleVersion,
    PatchRequest,
    RefineRequest,
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
    except LLMError:
        raise HTTPException(
            status_code=503,
            detail="AI generation is temporarily unavailable. Please try again in a moment.",
        )
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


@router.delete("/modules/{module_id}", status_code=204)
async def delete_module(module_id: str, request: Request) -> None:
    sid = _session_id(request)
    if not db.delete_module(sid, module_id):
        raise HTTPException(status_code=404, detail="Module not found")


@router.post("/modules/{module_id}/refine", response_model=StoredModule)
async def refine_module(module_id: str, body: RefineRequest, request: Request) -> StoredModule:
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="Prompt cannot be empty")
    sid = _session_id(request)
    existing = db.get_module(sid, module_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Module not found")
    try:
        new_config = orchestrator.refine_module(existing.config, prompt)
    except RefusalError as e:
        raise HTTPException(status_code=422, detail={"refusal": e.reason})
    except LLMError:
        raise HTTPException(
            status_code=503,
            detail="AI generation is temporarily unavailable. Please try again in a moment.",
        )
    updated = db.update_module(sid, module_id, new_config)
    if updated is None:
        raise HTTPException(status_code=404, detail="Module not found")
    return updated


@router.post("/modules/{module_id}/undo", response_model=StoredModule)
async def undo_module(module_id: str, request: Request) -> StoredModule:
    sid = _session_id(request)
    reverted = db.undo_module(sid, module_id)
    if reverted is None:
        raise HTTPException(status_code=409, detail="Nothing to undo")
    return reverted


@router.get("/modules/{module_id}/history", response_model=list[ModuleVersion])
async def module_history(module_id: str, request: Request) -> list[ModuleVersion]:
    sid = _session_id(request)
    return db.list_versions(sid, module_id)
