"""Layout Studio API — build/browse a use-case-indexed library of candidate
ModuleConfig layouts, and promote chosen ones into the generation seed pool."""

import ipaddress
import json
import logging
import os
import socket
import urllib.error
import urllib.request
from urllib.parse import urlparse

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel

from src import db, llm, semantic_cache
from src.routes.deps import _llm_error_detail, _owner_id, _require_trusted_origin
from src.schema import LLMError, ModuleConfig, RefusalError
from src.services import studio

_logger = logging.getLogger(__name__)

_MAX_IMAGE_BYTES = 12 * 1024 * 1024


def _autopromote_enabled() -> bool:
    return os.environ.get("TRUS_CAPTURE_AUTOPROMOTE", "on").strip().lower() not in (
        "off",
        "0",
        "false",
        "no",
    )


router = APIRouter(prefix="/studio")


class StudioUseCase(BaseModel):
    key: str
    title: str
    icon: str | None = None
    accent: str | None = None
    apps: list[str] = []
    count: int = 0


class StudioLayout(BaseModel):
    id: str | None = None
    use_case: str
    label: str
    inspired_by: str | None = None
    config: ModuleConfig
    created_at: str | None = None
    capture_meta: dict | None = None  # screenshot-capture metadata (capture endpoint)
    confidence: float | None = None  # capability-coverage confidence (capture endpoint)


class PromoteResponse(BaseModel):
    ok: bool
    seed_prompt: str
    library: dict


def _row_to_layout(r) -> StudioLayout | None:
    """Parse a layout_library row, or quarantine it (R-1105 parity): an
    unreadable row must degrade only itself, never the caller's whole list."""
    try:
        return StudioLayout(
            id=r["id"],
            use_case=r["use_case"],
            label=r["label"],
            inspired_by=r["inspired_by"],
            config=ModuleConfig.model_validate_json(r["config_json"]),
            created_at=r["created_at"],
        )
    except Exception:
        _logger.warning("Quarantined unreadable layout row %s (R-1105)", r["id"])
        return None


@router.get("/use-cases", response_model=list[StudioUseCase])
def list_use_cases(request: Request) -> list[StudioUseCase]:
    counts = db.layout_counts(_owner_id(request))
    return [
        StudioUseCase(
            key=u["key"],
            title=u["title"],
            icon=u.get("icon"),
            accent=u.get("accent"),
            apps=u.get("apps", []),
            count=counts.get(u["key"], 0),
        )
        for u in studio.use_cases()
    ]


@router.post("/use-cases/{key}/generate", response_model=list[StudioLayout])
def generate(
    key: str, request: Request, n: int = Query(default=4, ge=1, le=8)
) -> list[StudioLayout]:
    """Mine N candidate layouts for a use case (modelled after leading apps) and
    store them in the library."""
    owner = _owner_id(request)
    if studio.get_use_case(key) is None:
        raise HTTPException(status_code=404, detail=f"Unknown use case: {key}")
    layouts = studio.generate_layouts(key, n)
    stored: list[StudioLayout] = []
    for ly in layouts:
        # Persist provenance so the promote gate below refuses degraded/stub layouts
        # (R-403), and echo it back so the UI can label them.
        capture_meta = {"degraded": bool(ly.get("degraded")), "source": ly.get("source")}
        lid = db.layout_add(
            key,
            ly["label"],
            ly.get("inspired_by"),
            json.dumps(ly["config"]),
            capture_meta_json=json.dumps(capture_meta),
            owner=owner,
        )
        stored.append(
            StudioLayout(
                id=lid,
                use_case=key,
                label=ly["label"],
                inspired_by=ly.get("inspired_by"),
                config=ModuleConfig.model_validate(ly["config"]),
                capture_meta=capture_meta,
            )
        )
    return stored


def _check_url_allowed(url: str) -> None:
    """SSRF guard (Stage-1 review decision B): refuse non-http(s) schemes,
    private/loopback/link-local/metadata targets, and all URL imports in prod
    unless TRUS_ALLOW_URL_IMPORT=1. Raises HTTPException(422)."""
    if (
        os.environ.get("TRUS_ENV", "dev") == "prod"
        and os.environ.get("TRUS_ALLOW_URL_IMPORT", "0") != "1"
    ):
        raise HTTPException(
            status_code=422, detail="URL import is disabled; upload the image file instead"
        )
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HTTPException(status_code=422, detail="Only http(s) image URLs are supported")
    try:
        # Known accepted limitation (alpha): the fetch is not pinned to these
        # resolved IPs, so a low-TTL DNS rebind between this check and connect
        # can still reach a private host. Mitigated by the image/ content-type
        # gate and the prod-off default; revisit with IP-pinning if exposure grows.
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as e:
        raise HTTPException(status_code=422, detail="Image URL host could not be resolved") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise HTTPException(
                status_code=422, detail="Image URL points at a private address; refused"
            )


def _load_image(file: UploadFile | None, image_url: str) -> tuple[bytes, str]:
    """Image bytes + mime from an upload or a single http(s) fetch of a URL."""
    if file is not None:
        # Cap the read (one byte past the limit) so an oversized upload is rejected
        # by the size check below instead of being fully materialized first.
        data = file.file.read(_MAX_IMAGE_BYTES + 1)
        mime = file.content_type or "image/png"
        if not mime.startswith("image/"):
            raise HTTPException(status_code=422, detail="That file isn't an image.")
        if len(data) > _MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="Image too large (max 12MB).")
        return data, mime
    url = (image_url or "").strip()
    if not url:
        raise HTTPException(status_code=422, detail="Provide an image file or an image_url.")
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(status_code=422, detail="image_url must be an http(s) link.")
    _check_url_allowed(url)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Trus/0.1 (layout studio)"})
        # Scheme + host validated by _check_url_allowed above (SSRF guard, Stage-1
        # review decision B); the redirect re-check below closes the TOCTOU gap.
        with urllib.request.urlopen(req, timeout=20) as resp:  # nosemgrep
            # TOCTOU: _check_url_allowed above only resolved the ORIGINAL host — a
            # redirect can still bounce to a private/metadata address (the classic
            # 169.254.169.254 bypass). urlopen follows redirects itself, so re-check
            # the FINAL url it actually landed on before trusting the response.
            _check_url_allowed(resp.url)
            ct = (resp.headers.get("Content-Type") or "").split(";")[0].strip()
            if not ct.startswith("image/"):
                raise HTTPException(status_code=422, detail="That URL didn't return an image.")
            data = resp.read(_MAX_IMAGE_BYTES + 1)
    except HTTPException:
        raise
    except (urllib.error.URLError, OSError) as e:
        raise HTTPException(status_code=422, detail=f"Couldn't fetch that image: {e}") from e
    if len(data) > _MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image too large (max 12MB).")
    return data, ct


@router.post("/use-cases/{key}/import", response_model=StudioLayout)
def import_layout(
    key: str,
    request: Request,
    file: UploadFile | None = File(default=None),
    image_url: str = Form(default=""),
) -> StudioLayout:
    """Read a reference screenshot (upload or image URL) with a vision model and add
    the DERIVED layout to the library. Only the layout is stored — never the image."""
    _require_trusted_origin(request)
    owner = _owner_id(request)
    if studio.get_use_case(key) is None:
        raise HTTPException(status_code=404, detail=f"Unknown use case: {key}")
    data, mime = _load_image(file, image_url)
    try:
        ly = studio.import_from_image(key, data, mime)
    except RefusalError as e:
        raise HTTPException(status_code=422, detail={"refusal": e.reason}) from e
    except LLMError as e:
        raise HTTPException(status_code=503, detail=_llm_error_detail(e)) from e
    lid = db.layout_add(
        key, ly["label"], ly.get("inspired_by"), json.dumps(ly["config"]), owner=owner
    )
    return StudioLayout(
        id=lid,
        use_case=key,
        label=ly["label"],
        inspired_by=ly.get("inspired_by"),
        config=ModuleConfig.model_validate(ly["config"]),
    )


@router.post("/use-cases/{key}/capture", response_model=StudioLayout)
def capture_layout(
    key: str,
    request: Request,
    file: UploadFile | None = File(default=None),
    image_url: str = Form(default=""),
    match_colors: bool = Form(default=False),
) -> StudioLayout:
    """Staged, high-fidelity screenshot import: CAPTURE the image into a full IR, then
    TRANSFORM it onto the trusted component library (re-skinned, no feature dropped),
    score capability coverage, store the enriched layout, and auto-seed high-confidence
    captures into the generation pool. Only the layout is stored — never the image."""
    _require_trusted_origin(request)
    owner = _owner_id(request)
    if studio.get_use_case(key) is None:
        raise HTTPException(status_code=404, detail=f"Unknown use case: {key}")
    data, mime = _load_image(file, image_url)
    try:
        ly = studio.capture_layout(key, data, mime, match_colors=match_colors)
    except RefusalError as e:
        raise HTTPException(status_code=422, detail={"refusal": e.reason}) from e
    except LLMError as e:
        raise HTTPException(status_code=503, detail=_llm_error_detail(e)) from e

    # R-403: the TRANSFORM stage's llm.generate() call can cascade-degrade even
    # though capability coverage still scores "high" — record that on the
    # layout's capture_meta so neither auto-promote below, nor a later manual
    # promote (see promote_layout), can seed a degraded result.
    last = llm.last_call.get()
    degraded = bool(last is not None and last.degraded)
    if ly.get("capture_meta") is not None:
        ly["capture_meta"]["degraded"] = degraded

    lid = db.layout_add(
        key,
        ly["label"],
        ly.get("inspired_by"),
        json.dumps(ly["config"]),
        capture_meta_json=json.dumps(ly.get("capture_meta")),
        ir_digest_json=json.dumps(ly.get("ir_digest")),
        confidence=ly.get("confidence"),
        owner=owner,
    )

    # Auto-seed: high-confidence captures join the generation seed pool so future
    # prompts for similar tools immediately benefit (decided: auto-seed ON).
    quality = (ly.get("capture_meta") or {}).get("capture_quality")
    if _autopromote_enabled() and quality == "high":
        if degraded:
            _logger.warning("degraded capture not seeded (use_case=%s)", key)
        else:
            uc = studio.get_use_case(key)
            seed_prompt = (uc.get("seed_prompts") or [ly["label"]])[0] if uc else ly["label"]
            semantic_cache.store_structured(
                "system", ly.get("structured_text", ""), seed_prompt, [ly["config"]], owner=owner
            )

    return StudioLayout(
        id=lid,
        use_case=key,
        label=ly["label"],
        inspired_by=ly.get("inspired_by"),
        config=ModuleConfig.model_validate(ly["config"]),
        capture_meta=ly.get("capture_meta"),
        confidence=ly.get("confidence"),
    )


@router.get("/layouts", response_model=list[StudioLayout])
def list_layouts(
    request: Request, use_case: str | None = Query(default=None)
) -> list[StudioLayout]:
    rows = db.layout_list(use_case, owner=_owner_id(request))
    return [ly for ly in (_row_to_layout(r) for r in rows) if ly is not None]


@router.delete("/layouts/{layout_id}", status_code=204)
def delete_layout(layout_id: str, request: Request) -> None:
    if not db.layout_delete(layout_id, owner=_owner_id(request)):
        raise HTTPException(status_code=404, detail="Layout not found")


@router.post("/layouts/{layout_id}/promote", response_model=PromoteResponse)
def promote_layout(layout_id: str, request: Request) -> PromoteResponse:
    """Add a layout to the main app's generation seed pool, so future generations
    for this use case draw on it (the 'upload template ideas' connection)."""
    owner = _owner_id(request)
    row = db.layout_get(layout_id, owner=owner)
    if row is None:
        raise HTTPException(status_code=404, detail="Layout not found")
    # Fail closed: unparseable or non-dict capture_meta is UNKNOWN provenance, which
    # is not safe to promote — treat it as degraded (R-403).
    raw_meta = row["capture_meta_json"]
    if raw_meta is None:
        unsafe = False
        capture_meta: object = None
    else:
        try:
            capture_meta = json.loads(raw_meta)
        except (json.JSONDecodeError, ValueError):
            capture_meta = None
            unsafe = True
        else:
            unsafe = not isinstance(capture_meta, dict)
    if unsafe or (isinstance(capture_meta, dict) and capture_meta.get("degraded")):
        raise HTTPException(
            status_code=409,
            detail="This layout came from a degraded capture and cannot be "
            "promoted to the generation seed pool.",
        )
    uc = studio.get_use_case(row["use_case"])
    seed_prompt = (uc.get("seed_prompts") or [row["label"]])[0] if uc else row["label"]
    config = json.loads(row["config_json"])
    semantic_cache.store("system", seed_prompt, [config], owner=owner)
    return PromoteResponse(ok=True, seed_prompt=seed_prompt, library=db.cache_stats())
