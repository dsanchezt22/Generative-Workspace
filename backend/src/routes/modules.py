import contextlib
import time
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile

from src import db, llm
from src.routes.deps import _llm_error_detail, _owner_id, _require_trusted_origin
from src.schema import (
    ClarifyingQuestion,
    CreateSnapshotRequest,
    ExchangeTurn,
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

# R-102: once 4 questions in a chain have been answered, the route (not just the
# system prompt) forces the model to stop asking and build its best interpretation.
_EXCHANGE_CAP_NOTE = (
    "You have asked enough questions — do NOT ask another; build the best interpretation now."
)


def _fold_exchange(exchange: list[ExchangeTurn] | None) -> str | None:
    """Fold a multi-turn clarifying interview into text the MODEL sees, so a
    second/third/fourth question never loses earlier answers (previously
    PromptBar string-concatenated only the latest answer). Returns None when
    there's no exchange yet. This folded text is passed to the orchestrator as
    `exchange_context` — kept separate from `prompt`, which stays the raw
    original and is the only thing the semantic cache keys on."""
    if not exchange:
        return None
    lines = [f"Q: {turn.question}\nA: {turn.answer}" for turn in exchange]
    if len(exchange) >= 4:
        lines.append(_EXCHANGE_CAP_NOTE)
    return "\n\n".join(lines)


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


@contextlib.contextmanager
def _track(sid: str, kind: str):
    """Times the wrapped orchestrator call and records a gen_event (R-1202).
    Re-raises everything untouched; recording itself is best-effort and never
    fails the request."""
    t0 = time.monotonic()
    outcome = "ok"
    try:
        yield
    except ClarifyingQuestion:
        outcome = "question"
        raise
    except RefusalError:
        outcome = "refusal"
        raise
    except LLMError:
        outcome = "error"
        raise
    finally:
        last = llm.last_call.get()
        if outcome == "ok" and last is not None and last.degraded:
            outcome = "degraded"
        with contextlib.suppress(Exception):
            db.add_gen_event(
                sid,
                kind,
                outcome,
                last.provider if last else None,
                last.model if last else None,
                int((time.monotonic() - t0) * 1000),
                last.tokens_in if last else None,
                last.tokens_out if last else None,
            )


@router.post("/modules/generate", response_model=GenerateResponse)
def generate_module(
    body: GenerateRequest,
    request: Request,
    page_id: str | None = Query(default=None),
) -> GenerateResponse:
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="Prompt cannot be empty")
    sid = _owner_id(request)
    existing = [m.config for m in db.list_modules(sid)]
    exchange_context = _fold_exchange(body.exchange)
    # R-302: the owner's recent conversation on this page feeds generation
    # context (not the grounded-file path — see generate_modules_from_file).
    # page_id None (initial-load race window) → the helper returns [] — no page
    # context = no conversation context, never a whole-session fallback.
    recent = db.recent_messages(sid, page_id, limit=10)
    try:
        with _track(sid, "generate"):
            configs = orchestrator.generate_modules(
                prompt,
                existing_modules=existing,
                owner=sid,
                exchange_context=exchange_context,
                # R-102 hard cap: 4 answered questions → a 5th is never relayed.
                allow_question=not body.exchange or len(body.exchange) < 4,
                recent_messages=recent,
            )
    except ClarifyingQuestion as e:
        return GenerateResponse(question=e.question)
    except RefusalError as e:
        raise HTTPException(status_code=422, detail={"refusal": e.reason}) from e
    except LLMError as e:
        raise HTTPException(status_code=503, detail=_llm_error_detail(e)) from None
    plan = orchestrator.last_plan.get()
    stored = [db.insert_module(sid, c, page_id=page_id) for c in configs]
    _log(sid, "user", prompt, page_id=stored[0].page_id)
    for s in stored:
        _log(sid, "assistant", f"Created {s.config.title}", page_id=s.page_id, module_id=s.id)
    deg = llm.last_call.get()
    return GenerateResponse(
        module=stored[0], modules=stored, degraded=bool(deg and deg.degraded), plan=plan
    )


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
    sid = _owner_id(request)
    existing = [m.config for m in db.list_modules(sid)]
    exchange_context = _fold_exchange(body.exchange)
    # R-302: the owner's recent conversation on this page feeds generation
    # context (not the grounded-file path — see generate_modules_from_file).
    # page_id None (initial-load race window) → the helper returns [] — no page
    # context = no conversation context, never a whole-session fallback.
    recent = db.recent_messages(sid, page_id, limit=10)
    try:
        with _track(sid, "preview"):
            configs = orchestrator.generate_modules(
                prompt,
                existing_modules=existing,
                owner=sid,
                exchange_context=exchange_context,
                # R-102 hard cap: 4 answered questions → a 5th is never relayed.
                allow_question=not body.exchange or len(body.exchange) < 4,
                recent_messages=recent,
            )
    except ClarifyingQuestion as e:
        return GenerateResponse(question=e.question)
    except RefusalError as e:
        raise HTTPException(status_code=422, detail={"refusal": e.reason}) from e
    except LLMError as e:
        raise HTTPException(status_code=503, detail=_llm_error_detail(e)) from None
    plan = orchestrator.last_plan.get()
    deg = llm.last_call.get()
    return GenerateResponse(previews=configs, degraded=bool(deg and deg.degraded), plan=plan)


@router.post("/modules", response_model=list[StoredModule], status_code=201)
async def insert_modules(
    body: InsertModulesRequest,
    request: Request,
    page_id: str | None = Query(default=None),
) -> list[StoredModule]:
    """Persist accepted preview tools onto the canvas."""
    sid = _owner_id(request)
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
    hint: str = Form(""),
    page_id: str | None = Query(default=None),
) -> GenerateResponse:
    _require_trusted_origin(request)
    sid = _owner_id(request)
    # Cap the read before materializing the whole upload in memory: read one byte
    # past the limit so the size check below still fires for oversized files.
    data = file.file.read(15 * 1024 * 1024 + 1)
    if not data:
        raise HTTPException(status_code=422, detail="The file is empty.")
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="That file is too large (max 15MB).")
    mime = file.content_type or "application/octet-stream"
    instruction = prompt.strip() or f"Build the tools I need from {file.filename}."
    # R-221: the sketch snap sends a bounded interpretation hint (~200 chars) that
    # the orchestrator folds into the model-visible message; a normal file upload
    # sends none (empty → None) and is unchanged.
    hint_text = hint.strip()[:200] or None
    existing = [m.config for m in db.list_modules(sid)]
    try:
        with _track(sid, "file"):
            configs = orchestrator.generate_modules_from_file(
                instruction,
                data,
                mime,
                existing_modules=existing,
                filename=file.filename,
                hint=hint_text,
            )
    except ClarifyingQuestion as e:
        return GenerateResponse(question=e.question)
    except RefusalError as e:
        raise HTTPException(status_code=422, detail={"refusal": e.reason}) from e
    except LLMError as e:
        raise HTTPException(status_code=503, detail=_llm_error_detail(e)) from None
    stored = [db.insert_module(sid, c, page_id=page_id) for c in configs]
    _log(sid, "user", f"📎 {file.filename}: {instruction}", page_id=stored[0].page_id)
    for s in stored:
        _log(sid, "assistant", f"Created {s.config.title}", page_id=s.page_id, module_id=s.id)
    deg = llm.last_call.get()
    return GenerateResponse(module=stored[0], modules=stored, degraded=bool(deg and deg.degraded))


@router.post("/onboarding/seed", response_model=list[StoredModule])
async def seed_onboarding(
    request: Request,
    page_id: str | None = Query(default=None),
) -> list[StoredModule]:
    """Pre-populate a brand-new session's canvas (no LLM cost). Never reseeds an
    existing workspace — if anything already exists, returns it unchanged."""
    _require_trusted_origin(request)
    sid = _owner_id(request)
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
    include_archived: bool = Query(default=False),
) -> list[StoredModule]:
    sid = _owner_id(request)
    return db.list_modules(sid, page_id=page_id, include_archived=include_archived)


@router.patch("/modules/{module_id}", response_model=StoredModule)
async def patch_module(module_id: str, body: PatchRequest, request: Request) -> StoredModule:
    sid = _owner_id(request)
    try:
        updated = db.update_module(sid, module_id, body.config, expected_rev=body.rev)
    except db.RevConflict as e:
        raise HTTPException(
            status_code=409, detail={"conflict": e.current.model_dump(mode="json")}
        ) from e
    if updated is None:
        raise HTTPException(status_code=404, detail="Module not found")
    return updated


@router.delete("/modules/{module_id}", status_code=204)
async def delete_module(module_id: str, request: Request) -> None:
    sid = _owner_id(request)
    if not db.delete_module(sid, module_id):
        raise HTTPException(status_code=404, detail="Module not found")


@router.get("/modules/archived", response_model=list[StoredModule])
async def list_archived(request: Request) -> list[StoredModule]:
    sid = _owner_id(request)
    return db.list_archived(sid)


@router.post("/modules/{module_id}/archive", response_model=StoredModule)
async def archive_module(module_id: str, request: Request) -> StoredModule:
    sid = _owner_id(request)
    m = db.set_archived(sid, module_id, True)
    if m is None:
        raise HTTPException(status_code=404, detail="Module not found")
    return m


@router.post("/modules/{module_id}/restore", response_model=StoredModule)
async def restore_module(module_id: str, request: Request) -> StoredModule:
    sid = _owner_id(request)
    m = db.set_archived(sid, module_id, False)
    if m is None:
        raise HTTPException(status_code=404, detail="Module not found")
    return m


@router.post("/modules/{module_id}/duplicate", response_model=StoredModule)
async def duplicate_module(module_id: str, request: Request) -> StoredModule:
    sid = _owner_id(request)
    m = db.duplicate_module(sid, module_id)
    if m is None:
        raise HTTPException(status_code=404, detail="Module not found")
    return m


@router.post("/modules/{module_id}/refine", response_model=StoredModule)
def refine_module(module_id: str, body: RefineRequest, request: Request) -> StoredModule:
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="Prompt cannot be empty")
    sid = _owner_id(request)
    existing = db.get_module(sid, module_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Module not found")
    other_modules = [m.config for m in db.list_modules(sid) if m.id != module_id]
    try:
        with _track(sid, "refine"):
            new_config = orchestrator.refine_module(
                existing.config, prompt, existing_modules=other_modules
            )
        last = llm.last_call.get()
        if last is not None and last.degraded:
            # R-1104/R-403: a cascade-degraded call still parses into a valid (but
            # generic, ungrounded) ModuleConfig — never persist that as a fake
            # success. The gen_event above already recorded outcome=degraded;
            # this just stops the route from acting on it.
            raise LLMError("The AI model is unavailable — refine was not applied.")
    except ClarifyingQuestion as e:
        raise HTTPException(status_code=422, detail={"question": e.question}) from e
    except RefusalError as e:
        raise HTTPException(status_code=422, detail={"refusal": e.reason}) from e
    except LLMError as e:
        raise HTTPException(status_code=503, detail=_llm_error_detail(e)) from None
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
    sid = _owner_id(request)
    reverted = db.undo_module(sid, module_id)
    if reverted is None:
        raise HTTPException(status_code=409, detail="Nothing to undo")
    return reverted


@router.get("/modules/{module_id}/history", response_model=list[ModuleVersion])
async def module_history(module_id: str, request: Request) -> list[ModuleVersion]:
    sid = _owner_id(request)
    return db.list_versions(sid, module_id)


@router.post("/pages/{page_id}/snapshots", response_model=Snapshot, status_code=201)
async def create_snapshot(page_id: str, body: CreateSnapshotRequest, request: Request) -> Snapshot:
    sid = _owner_id(request)
    label = (body.label or "").strip() or "Snapshot"
    return db.create_snapshot(sid, page_id, label)


@router.get("/pages/{page_id}/snapshots", response_model=list[Snapshot])
async def list_snapshots(page_id: str, request: Request) -> list[Snapshot]:
    sid = _owner_id(request)
    return db.list_snapshots(sid, page_id)


@router.post("/snapshots/{snapshot_id}/restore", status_code=204)
async def restore_snapshot(snapshot_id: str, request: Request) -> None:
    sid = _owner_id(request)
    result = db.restore_snapshot(sid, snapshot_id)
    if result == "missing":
        raise HTTPException(status_code=404, detail="Snapshot not found")
    if result == "corrupt":
        raise HTTPException(
            status_code=409, detail="This snapshot is unreadable and was not restored."
        )


@router.delete("/snapshots/{snapshot_id}", status_code=204)
async def delete_snapshot(snapshot_id: str, request: Request) -> None:
    sid = _owner_id(request)
    if not db.delete_snapshot(sid, snapshot_id):
        raise HTTPException(status_code=404, detail="Snapshot not found")


@router.post("/workspace/insights", response_model=GenerateResponse)
def workspace_insights(
    request: Request,
    page_id: str | None = Query(default=None),
) -> GenerateResponse:
    _require_trusted_origin(request)
    sid = _owner_id(request)
    modules = db.list_modules(sid, page_id=page_id)
    if not modules:
        raise HTTPException(status_code=422, detail="No modules on canvas to synthesize.")
    existing_configs = [m.config for m in modules]
    try:
        with _track(sid, "insights"):
            config = orchestrator.synthesize_workspace(existing_configs)
        last = llm.last_call.get()
        if last is not None and last.degraded:
            # R-1104/R-403: mirror the refine guard above — a cascade-degraded
            # synthesis must not be inserted as a fake-success dashboard module.
            raise LLMError("The AI model is unavailable — insights were not generated.")
    except ClarifyingQuestion as e:
        raise HTTPException(status_code=422, detail={"question": e.question}) from e
    except RefusalError as e:
        raise HTTPException(status_code=422, detail={"refusal": e.reason}) from e
    except LLMError as e:
        raise HTTPException(status_code=503, detail=_llm_error_detail(e)) from None
    stored = db.insert_module(sid, config, page_id=page_id)
    return GenerateResponse(module=stored)
