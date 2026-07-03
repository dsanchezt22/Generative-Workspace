import logging
import os
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from src import db, llm
from src.routes import auth, conversations, modules, pages, studio

logging.basicConfig(
    level=os.environ.get("TRUS_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


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


@app.middleware("http")
async def log_unhandled(request, call_next):
    """Every unhandled exception reaches the operator log, not just the client (R-1203)."""
    try:
        return await call_next(request)
    except Exception:
        logging.getLogger("trus.unhandled").exception("%s %s", request.method, request.url.path)
        raise


app.include_router(auth.router, prefix="/api")
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


@app.get("/api/ops/summary")
def ops_summary(token: str = Query(default="")) -> dict:
    """Gated operator surface (R-1201/R-1203): generation volume/outcomes + DAU."""
    expected = os.environ.get("TRUS_OPS_TOKEN", "")
    if not expected or token != expected:
        raise HTTPException(status_code=401, detail="ops token required")
    return {"generations": db.gen_stats(days=7), "daily_active": db.daily_active(days=14)}
