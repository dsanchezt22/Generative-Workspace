import contextlib
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile

from src import db
from src.schema import (
    ClarifyingQuestion,
    CreateSnapshotRequest,
    GenerateRequest,
    GenerateResponse,
    InsertModulesRequest,
    LLMError,
    ModuleConfig,
    ModuleVersion,
    PatchRequest,
    RefineRequest,
    RefusalError,
    Snapshot,
    StoredModule,
)
from src.services import orchestrator
from src.stub_templates import pick_template

router = APIRouter()


def _session_id(request: Request) -> str:
    sid = request.session.get("sid")
    sid = db.ensure_session(sid)
    request.session["sid"] = sid
    return sid


def _log(
    sid: str,
    role: Literal["user", "assistant"],
    text: str,
    page_id: str | None = None,
    module_id: str | None = None,
) -> None:
    """Best-effort conversation logging — never let it break a generation."""
    with contextlib.suppress(Exception):  # pragma: no cover - logging must not fail the request
        db.add_message(sid, role, text, page_id=page_id, module_id=module_id)


@router.post("/modules/generate", response_model=GenerateResponse)
def generate_module(
    body: GenerateRequest,
    request: Request,
    page_id: str | None = Query(default=None),
) -> GenerateResponse:
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="Prompt cannot be empty")
    sid = _session_id(request)
    existing = [m.config for m in db.list_modules(sid)]
    try:
        configs = orchestrator.generate_modules(prompt, existing_modules=existing)
    except ClarifyingQuestion as e:
        return GenerateResponse(question=e.question)
    except RefusalError as e:
        raise HTTPException(status_code=422, detail={"refusal": e.reason}) from e
    except LLMError:
        raise HTTPException(
            status_code=503,
            detail="AI generation is temporarily unavailable. Please try again in a moment.",
        ) from None
    stored = [db.insert_module(sid, c, page_id=page_id) for c in configs]
    _log(sid, "user", prompt, page_id=stored[0].page_id)
    for s in stored:
        _log(sid, "assistant", f"Created {s.config.title}", page_id=s.page_id, module_id=s.id)
    return GenerateResponse(module=stored[0], modules=stored)


@router.post("/modules/preview", response_model=GenerateResponse)
def preview_modules(
    body: GenerateRequest,
    request: Request,
    page_id: str | None = Query(default=None),
) -> GenerateResponse:
    """Propose tools for a prompt WITHOUT persisting them (preview-then-accept)."""
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="Prompt cannot be empty")
    sid = _session_id(request)
    existing = [m.config for m in db.list_modules(sid)]
    try:
        configs = orchestrator.generate_modules(prompt, existing_modules=existing)
    except ClarifyingQuestion as e:
        return GenerateResponse(question=e.question)
    except RefusalError as e:
        raise HTTPException(status_code=422, detail={"refusal": e.reason}) from e
    except LLMError:
        raise HTTPException(
            status_code=503,
            detail="AI generation is temporarily unavailable. Please try again in a moment.",
        ) from None
    return GenerateResponse(previews=configs)


@router.post("/modules", response_model=list[StoredModule], status_code=201)
async def insert_modules(
    body: InsertModulesRequest,
    request: Request,
    page_id: str | None = Query(default=None),
) -> list[StoredModule]:
    """Persist accepted preview tools onto the canvas."""
    sid = _session_id(request)
    stored = [db.insert_module(sid, c, page_id=page_id) for c in body.configs]
    if stored and body.prompt:
        _log(sid, "user", body.prompt, page_id=stored[0].page_id)
    for s in stored:
        _log(sid, "assistant", f"Created {s.config.title}", page_id=s.page_id, module_id=s.id)
    return stored


@router.post("/modules/generate_from_file", response_model=GenerateResponse)
def generate_from_file(
    request: Request,
    file: UploadFile = File(...),
    prompt: str = Form(""),
    page_id: str | None = Query(default=None),
) -> GenerateResponse:
    sid = _session_id(request)
    data = file.file.read()
    if not data:
        raise HTTPException(status_code=422, detail="The file is empty.")
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="That file is too large (max 15MB).")
    mime = file.content_type or "application/octet-stream"
    instruction = prompt.strip() or f"Build the tools I need from {file.filename}."
    existing = [m.config for m in db.list_modules(sid)]
    try:
        configs = orchestrator.generate_modules_from_file(
            instruction, data, mime, existing_modules=existing
        )
    except ClarifyingQuestion as e:
        return GenerateResponse(question=e.question)
    except RefusalError as e:
        raise HTTPException(status_code=422, detail={"refusal": e.reason}) from e
    except LLMError:
        raise HTTPException(
            status_code=503,
            detail="AI generation is temporarily unavailable. Please try again in a moment.",
        ) from None
    stored = [db.insert_module(sid, c, page_id=page_id) for c in configs]
    _log(sid, "user", f"📎 {file.filename}: {instruction}", page_id=stored[0].page_id)
    for s in stored:
        _log(sid, "assistant", f"Created {s.config.title}", page_id=s.page_id, module_id=s.id)
    return GenerateResponse(module=stored[0], modules=stored)


@router.post("/onboarding/seed", response_model=list[StoredModule])
async def seed_onboarding(
    request: Request,
    page_id: str | None = Query(default=None),
) -> list[StoredModule]:
    """Pre-populate a brand-new session's canvas (no LLM cost). Never reseeds an
    existing workspace — if anything already exists, returns it unchanged."""
    sid = _session_id(request)
    if db.list_modules(sid):
        return db.list_modules(sid, page_id=page_id)
    note = {
        "title": "Today",
        "icon": "📝",
        "accent": "amber",
        "components": [
            {
                "id": "note",
                "type": "text_input",
                "label": "Today's note",
                "placeholder": "What's on your mind?",
            },
            {
                "id": "remember",
                "type": "list",
                "label": "To remember",
                "item_label": "Item",
                "placeholder": "Add a reminder…",
            },
        ],
        "summary_component_id": "note",
    }
    specs = [
        (pick_template("a simple to-do list"), 32),
        (pick_template("habit tracker"), 404),
        (note, 776),
    ]
    out: list[StoredModule] = []
    for cfg, x in specs:
        cfg["layout"] = {"x": x, "y": 140, "width": 340, "height": 300}
        out.append(db.insert_module(sid, ModuleConfig.model_validate(cfg), page_id=page_id))
    return out


@router.get("/modules", response_model=list[StoredModule])
async def list_modules(
    request: Request,
    page_id: str | None = Query(default=None),
) -> list[StoredModule]:
    sid = _session_id(request)
    return db.list_modules(sid, page_id=page_id)


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


@router.get("/modules/archived", response_model=list[StoredModule])
async def list_archived(request: Request) -> list[StoredModule]:
    sid = _session_id(request)
    return db.list_archived(sid)


@router.post("/modules/{module_id}/archive", response_model=StoredModule)
async def archive_module(module_id: str, request: Request) -> StoredModule:
    sid = _session_id(request)
    m = db.set_archived(sid, module_id, True)
    if m is None:
        raise HTTPException(status_code=404, detail="Module not found")
    return m


@router.post("/modules/{module_id}/restore", response_model=StoredModule)
async def restore_module(module_id: str, request: Request) -> StoredModule:
    sid = _session_id(request)
    m = db.set_archived(sid, module_id, False)
    if m is None:
        raise HTTPException(status_code=404, detail="Module not found")
    return m


@router.post("/modules/{module_id}/duplicate", response_model=StoredModule)
async def duplicate_module(module_id: str, request: Request) -> StoredModule:
    sid = _session_id(request)
    m = db.duplicate_module(sid, module_id)
    if m is None:
        raise HTTPException(status_code=404, detail="Module not found")
    return m


@router.post("/modules/{module_id}/refine", response_model=StoredModule)
def refine_module(module_id: str, body: RefineRequest, request: Request) -> StoredModule:
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="Prompt cannot be empty")
    sid = _session_id(request)
    existing = db.get_module(sid, module_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Module not found")
    other_modules = [m.config for m in db.list_modules(sid) if m.id != module_id]
    try:
        new_config = orchestrator.refine_module(
            existing.config, prompt, existing_modules=other_modules
        )
    except RefusalError as e:
        raise HTTPException(status_code=422, detail={"refusal": e.reason}) from e
    except LLMError:
        raise HTTPException(
            status_code=503,
            detail="AI generation is temporarily unavailable. Please try again in a moment.",
        ) from None
    updated = db.update_module(sid, module_id, new_config)
    if updated is None:
        raise HTTPException(status_code=404, detail="Module not found")
    _log(sid, "user", prompt, page_id=updated.page_id, module_id=module_id)
    _log(
        sid,
        "assistant",
        f"Refined {new_config.title}",
        page_id=updated.page_id,
        module_id=module_id,
    )
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


@router.post("/pages/{page_id}/snapshots", response_model=Snapshot, status_code=201)
async def create_snapshot(page_id: str, body: CreateSnapshotRequest, request: Request) -> Snapshot:
    sid = _session_id(request)
    label = (body.label or "").strip() or "Snapshot"
    return db.create_snapshot(sid, page_id, label)


@router.get("/pages/{page_id}/snapshots", response_model=list[Snapshot])
async def list_snapshots(page_id: str, request: Request) -> list[Snapshot]:
    sid = _session_id(request)
    return db.list_snapshots(sid, page_id)


@router.post("/snapshots/{snapshot_id}/restore", status_code=204)
async def restore_snapshot(snapshot_id: str, request: Request) -> None:
    sid = _session_id(request)
    if not db.restore_snapshot(sid, snapshot_id):
        raise HTTPException(status_code=404, detail="Snapshot not found")


@router.delete("/snapshots/{snapshot_id}", status_code=204)
async def delete_snapshot(snapshot_id: str, request: Request) -> None:
    sid = _session_id(request)
    if not db.delete_snapshot(sid, snapshot_id):
        raise HTTPException(status_code=404, detail="Snapshot not found")


@router.post("/workspace/insights", response_model=GenerateResponse)
def workspace_insights(
    request: Request,
    page_id: str | None = Query(default=None),
) -> GenerateResponse:
    sid = _session_id(request)
    modules = db.list_modules(sid, page_id=page_id)
    if not modules:
        raise HTTPException(status_code=422, detail="No modules on canvas to synthesize.")
    existing_configs = [m.config for m in modules]
    try:
        config = orchestrator.synthesize_workspace(existing_configs)
    except RefusalError as e:
        raise HTTPException(status_code=422, detail={"refusal": e.reason}) from e
    except LLMError:
        raise HTTPException(
            status_code=503,
            detail="AI generation is temporarily unavailable. Please try again in a moment.",
        ) from None
    stored = db.insert_module(sid, config, page_id=page_id)
    return GenerateResponse(module=stored)
