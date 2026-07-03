import logging
import os
from contextlib import asynccontextmanager, suppress
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from src import db, llm
from src.routes import auth, conversations, modules, pages, studio
from src.routes.deps import _parse_cors_origins

logging.basicConfig(
    level=os.environ.get("TRUS_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="Trus API", lifespan=lifespan)

DEFAULT_SESSION_SECRET = "dev-insecure-key-change-me"  # noqa: S105 — known-public dev placeholder, not a real secret


def _require_prod_secret(trus_env: str, secret: str) -> None:
    """R-901: prod must not boot with the public default secret — anyone can
    read it from source, so it makes every session forgeable."""
    if trus_env == "prod" and secret == DEFAULT_SESSION_SECRET:
        raise RuntimeError(
            "SESSION_SECRET must be set to a strong value in prod (R-901): "
            "the default key is public and makes every session forgeable."
        )


def _cookie_settings(cookie_secure: bool) -> tuple[Literal["lax", "none"], bool]:
    """TRUS_COOKIE_SECURE flips same_site and https_only together — a
    cross-origin hosted split (Vercel frontend + Fly/Railway backend) needs
    same_site=none + secure, or the browser drops the cookie entirely (R-906)."""
    return ("none", True) if cookie_secure else ("lax", False)


_TRUS_ENV = os.environ.get("TRUS_ENV", "dev")
_SECRET = os.environ.get("SESSION_SECRET", DEFAULT_SESSION_SECRET)
_require_prod_secret(_TRUS_ENV, _SECRET)

_SAME_SITE, _HTTPS_ONLY = _cookie_settings(os.environ.get("TRUS_COOKIE_SECURE", "0") == "1")

app.add_middleware(
    SessionMiddleware,
    secret_key=_SECRET,
    session_cookie="trus_sid",
    same_site=_SAME_SITE,
    https_only=_HTTPS_ONLY,
    max_age=60 * 60 * 24 * 365,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_parse_cors_origins(os.environ.get("TRUS_CORS_ORIGINS", "http://localhost:3000")),
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


def _llm_status_payload() -> dict:
    """Payload for /api/llm/status, read fresh per call so it's testable without
    an app reimport. In prod (TRUS_ENV=prod) the internal endpoint topology
    (base_url) and cache internals are omitted — the endpoint is unauthenticated,
    and neither belongs on the public surface (R-1201). Provider/model/vision
    availability are harmless and stay. Dev keeps everything: this endpoint is
    the local-setup verification tool the README documents."""
    info = llm.provider_info()
    info["vision"] = llm.vision_info()
    if os.environ.get("TRUS_ENV", "dev") == "prod":
        info.pop("base_url", None)
        info["vision"].pop("base_url", None)  # same topology leak, one level down
        return info
    with suppress(Exception):  # pragma: no cover - diagnostics must not error
        info["cache"] = db.cache_stats()
    return info


@app.get("/api/llm/status")
async def llm_status() -> dict:
    """Which model backend is active (provider/model/base_url) — no secrets.
    Lets you confirm a local/open-source model is wired before generating, and
    shows how big the self-growing template cache is. Prod trims it (see
    _llm_status_payload)."""
    return _llm_status_payload()


@app.get("/api/ops/summary")
def ops_summary(token: str = Query(default="")) -> dict:
    """Gated operator surface (R-1201/R-1203): generation volume/outcomes + DAU +
    per-user last-seen ("which of the 50 used it yesterday")."""
    expected = os.environ.get("TRUS_OPS_TOKEN", "")
    if not expected or token != expected:
        raise HTTPException(status_code=401, detail="ops token required")
    return {
        "generations": db.gen_stats(days=7),
        "daily_active": db.daily_active(days=14),
        "users": db.last_seen_by_user(30),
    }
