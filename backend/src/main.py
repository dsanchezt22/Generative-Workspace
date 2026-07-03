import os
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from src import db, llm
from src.routes import conversations, modules, pages, studio


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="Trus API", lifespan=lifespan)

app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SESSION_SECRET", "dev-insecure-key-change-me"),
    session_cookie="trus_sid",
    same_site="lax",
    https_only=False,
    max_age=60 * 60 * 24 * 365,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

app.include_router(modules.router, prefix="/api")
app.include_router(pages.router, prefix="/api")
app.include_router(conversations.router, prefix="/api")
app.include_router(studio.router, prefix="/api")


@app.get("/api/health")
async def health() -> dict[str, str]:
    # async so this trivial handler runs on the event loop instead of competing for
    # the sync threadpool that serves (blocking) LLM generations.
    return {"status": "ok"}


@app.get("/api/llm/status")
async def llm_status() -> dict:
    """Which model backend is active (provider/model/base_url) — no secrets.
    Lets you confirm a local/open-source model is wired before generating, and
    shows how big the self-growing template cache is."""
    info = llm.provider_info()
    info["vision"] = llm.vision_info()
    with suppress(Exception):  # pragma: no cover - diagnostics must not error
        info["cache"] = db.cache_stats()
    return info
