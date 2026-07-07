"""HTTP surface for the V2 trust spine — server-side runtime automation, NOT
schema.Automation (a client-side module rule).

All handlers are sync `def` (threadpool, never the event loop); the first line
resolves `owner = _owner_id(request)` and every store call is owner-scoped. The
trust tier is NEVER caller-supplied — it is derived from ACTION_SPECS. Approve
executes the FROZEN park-time payload in-handler (the response is the truthful
outcome, zero cross-thread signaling).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from src import db
from src.routes.deps import _check_gen_budget, _owner_id, _RateLimiter
from src.schema_automations import (
    ActivityEntry,
    ApprovalOut,
    AutomationCreate,
    AutomationOut,
    AutomationPatch,
)
from src.services import actions, legibility, runtime

router = APIRouter()
_logger = logging.getLogger(__name__)

# approve/reject/run share one limiter (the transcribe/live pattern); LLM-backed
# execution additionally passes _check_gen_budget in the lifecycle below.
_action_limiter = _RateLimiter(max_calls=60, window_secs=300)


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _rate(owner: str) -> None:
    if not _action_limiter.allow(owner):
        raise HTTPException(status_code=429, detail="Too many actions — please wait a moment.")


def _sweep(owner: str, now: datetime) -> None:
    for row in db.approval_sweep_expired(owner, now.isoformat()):
        db.activity_add(
            owner,
            "expired",
            legibility.expired_summary(row["summary"]),
            automation_id=row["automation_id"],
            approval_id=row["id"],
        )


# ── serializers ──────────────────────────────────────────────────────────────


def _automation_out(row: dict) -> AutomationOut | None:
    """None when the stored action_json is unreadable (quarantine) — the list
    route skips it rather than 500-ing the whole list."""
    try:
        action = actions.parse_action(row["action_json"])
    except Exception:
        _logger.warning("Quarantined unreadable automation %s", row["id"])
        return None
    spec = actions.ACTION_SPECS.get(row["action_type"])
    if spec is None:
        return None
    return AutomationOut(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        page_id=row["page_id"],
        action=action,
        action_type=row["action_type"],
        tier_floor=spec.floor,
        irreversible=spec.irreversible,
        trust_dial=row["trust_dial"],
        enabled=bool(row["enabled"]),
        schedule_kind=row["schedule_kind"],
        interval_secs=row["interval_secs"],
        daily_at=row["daily_at"],
        next_run_at=row["next_run_at"],
        last_run_at=row["last_run_at"],
        last_status=row["last_status"],
        created_at=row["created_at"],
    )


def _approval_out(owner: str, row: dict) -> ApprovalOut:
    auto = db.automation_get(owner, row["automation_id"])
    preview = json.loads(row["preview_json"]) if row["preview_json"] else None
    return ApprovalOut(
        id=row["id"],
        automation_id=row["automation_id"],
        automation_name=auto["name"] if auto else "",
        action_type=row["action_type"],
        summary=row["summary"],
        preview=preview,
        status=row["status"],
        expires_at=row["expires_at"],
        created_at=row["created_at"],
        decided_at=row["decided_at"],
        executed_at=row["executed_at"],
    )


def _activity_out(owner: str, row: dict) -> ActivityEntry:
    detail = json.loads(row["detail_json"]) if row["detail_json"] else {}
    auto = db.automation_get(owner, row["automation_id"]) if row["automation_id"] else None
    return ActivityEntry(
        id=row["id"],
        kind=row["kind"],
        summary=row["summary"],
        automation_id=row["automation_id"],
        automation_name=auto["name"] if auto else None,
        approval_id=row["approval_id"],
        module_id=detail.get("module_id"),
        page_id=detail.get("page_id"),
        simulated=bool(detail.get("simulated")),
        created_at=row["created_at"],
    )


def _validate_targets(owner: str, action) -> None:
    """Every module/page the action targets must belong to the owner (owner-scoped
    ⇒ a foreign id is simply missing → 422, never a cross-owner leak)."""
    module_ids: set[str] = set()
    for attr in ("module_id", "source_module_id", "feed_module_id"):
        v = getattr(action, attr, None)
        if v:
            module_ids.add(v)
    for v in getattr(action, "source_module_ids", None) or []:
        module_ids.add(v)
    if getattr(action, "type", None) == "delete_data":
        if action.target == "module":
            module_ids.add(action.target_id)
        elif db.get_page(owner, action.target_id) is None:
            raise HTTPException(status_code=422, detail=f"Unknown page: {action.target_id}")
    for mid in module_ids:
        if db.get_module(owner, mid) is None:
            raise HTTPException(status_code=422, detail=f"Unknown module: {mid}")


# ── automations CRUD ─────────────────────────────────────────────────────────


@router.get("/automations")
def list_automations(request: Request) -> dict:
    owner = _owner_id(request)
    out = [_automation_out(r) for r in db.automation_list(owner)]
    return {"automations": [a for a in out if a is not None]}


@router.post("/automations", response_model=AutomationOut, status_code=201)
def create_automation(body: AutomationCreate, request: Request) -> AutomationOut:
    owner = _owner_id(request)
    if body.page_id is not None and db.get_page(owner, body.page_id) is None:
        raise HTTPException(status_code=422, detail=f"Unknown page: {body.page_id}")
    _validate_targets(owner, body.action)
    now = _now_dt()
    next_run = runtime._compute_next_run(
        {
            "schedule_kind": body.schedule_kind,
            "interval_secs": body.interval_secs,
            "daily_at": body.daily_at,
        },
        now,
    )
    row = db.automation_create(
        owner,
        page_id=body.page_id,
        name=body.name,
        description=body.description,
        action_type=body.action.type,
        action_json=body.action.model_dump_json(),
        schedule_kind=body.schedule_kind,
        interval_secs=body.interval_secs,
        daily_at=body.daily_at,
        trust_dial=body.trust_dial,
        next_run_at=next_run.isoformat(),
    )
    out = _automation_out(row)
    if out is None:  # unreachable — a just-created row is always readable
        raise HTTPException(status_code=500, detail="Automation could not be created")
    return out


@router.patch("/automations/{aid}", response_model=AutomationOut)
def patch_automation(aid: str, body: AutomationPatch, request: Request) -> AutomationOut:
    owner = _owner_id(request)
    kwargs: dict = {}
    if body.name is not None:
        kwargs["name"] = body.name
    if body.enabled is not None:
        kwargs["enabled"] = body.enabled
    if body.trust_dial is not None:
        kwargs["trust_dial"] = body.trust_dial
    row = db.automation_patch(owner, aid, **kwargs)
    if row is None:
        raise HTTPException(status_code=404, detail="Automation not found")
    out = _automation_out(row)
    if out is None:
        raise HTTPException(status_code=422, detail="Automation is corrupt")
    return out


@router.delete("/automations/{aid}", status_code=204)
def delete_automation(aid: str, request: Request) -> None:
    owner = _owner_id(request)
    if not db.automation_delete(owner, aid):
        raise HTTPException(status_code=404, detail="Automation not found")


@router.post("/automations/{aid}/run")
def run_automation(aid: str, request: Request) -> dict:
    owner = _owner_id(request)
    _rate(owner)
    row = db.automation_get(owner, aid)
    if row is None:
        raise HTTPException(status_code=404, detail="Automation not found")
    activity, approval = runtime.run_once(owner, row, _now_dt(), next_run_at=row["next_run_at"])
    return {
        "activity": _activity_out(owner, activity) if activity else None,
        "approval": _approval_out(owner, approval) if approval else None,
    }


# ── approvals ────────────────────────────────────────────────────────────────


@router.get("/approvals")
def list_approvals(request: Request) -> dict:
    owner = _owner_id(request)
    _sweep(owner, _now_dt())
    pending = db.approval_list_pending(owner)
    return {
        "approvals": [_approval_out(owner, r) for r in pending],
        "pending_count": len(pending),
    }


@router.get("/approvals/count")
def approvals_count(request: Request) -> dict:
    owner = _owner_id(request)
    return {"pending": db.approval_pending_count(owner)}


@router.post("/approvals/{approval_id}/approve")
def approve_approval(approval_id: str, request: Request) -> dict:
    owner = _owner_id(request)
    _rate(owner)
    now = _now_dt()
    _sweep(owner, now)
    claimed = db.approval_claim(owner, approval_id, "approved", now.isoformat())
    if claimed is None:
        row = db.approval_get(owner, approval_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Approval not found")
        raise HTTPException(status_code=409, detail={"state": row["status"]})

    action_type = claimed["action_type"]
    auto = db.automation_get(owner, claimed["automation_id"])
    name = auto["name"] if auto else ""

    # Validate the FROZEN payload (never execute a re-computation).
    try:
        actions.parse_action(claimed["payload_json"])
    except Exception:
        db.approval_set_failed(owner, approval_id)
        db.activity_add(
            owner,
            "failed",
            legibility.failed_summary(name, "stored request was unreadable"),
            automation_id=claimed["automation_id"],
            approval_id=approval_id,
            detail_json=json.dumps({"reason": "quarantine"}),
        )
        raise HTTPException(
            status_code=500, detail="Couldn't run — the stored request was unreadable."
        ) from None

    spec = actions.ACTION_SPECS.get(action_type)
    if spec is None:
        db.approval_set_failed(owner, approval_id)
        db.activity_add(
            owner,
            "failed",
            legibility.failed_summary(name, "unknown action type"),
            automation_id=claimed["automation_id"],
            approval_id=approval_id,
        )
        raise HTTPException(status_code=500, detail="Unknown action type — refused.")

    payload = json.loads(claimed["payload_json"])  # execute the frozen bytes (incl. enriched keys)

    if spec.uses_llm:
        try:
            _check_gen_budget(owner)
        except HTTPException:
            # Budget short-circuits BEFORE any spend; the CAS already claimed the
            # row, so we mark it failed honestly rather than revert (no dishonest
            # 'approved'). Returned as 200 with the failed pair — nothing pretends success.
            db.approval_set_failed(owner, approval_id)
            act = db.activity_add(
                owner,
                "failed",
                legibility.failed_summary(name, "usage budget reached"),
                automation_id=claimed["automation_id"],
                approval_id=approval_id,
                detail_json=json.dumps({"reason": "budget"}),
            )
            claimed["status"] = "failed"
            return {
                "approval": _approval_out(owner, claimed),
                "activity": _activity_out(owner, act),
            }

    ctx = actions.ExecContext(
        automation_id=claimed["automation_id"],
        page_id=auto["page_id"] if auto else None,
        state=json.loads(auto["state_json"]) if auto else {},
        now=now,
        interval_secs=auto["interval_secs"] if auto else None,
    )
    try:
        res = spec.execute(owner, payload, ctx)
    except Exception as e:
        db.approval_set_failed(owner, approval_id)
        db.activity_add(
            owner,
            "failed",
            legibility.failed_summary(name, actions.safe_reason(e)),
            automation_id=claimed["automation_id"],
            approval_id=approval_id,
            detail_json=json.dumps({"reason": "error", "error_class": type(e).__name__}),
        )
        raise HTTPException(
            status_code=502,
            detail="Couldn't complete the action. It's been logged and not marked done.",
        ) from None

    db.approval_set_executed(owner, approval_id, now.isoformat())
    detail: dict = {"simulated": spec.stub}
    if payload.get("module_id"):
        detail["module_id"] = payload["module_id"]
    if auto and auto.get("page_id"):
        detail["page_id"] = auto["page_id"]
    act = db.activity_add(
        owner,
        "approved",
        legibility.did_do(action_type, payload, res.result),
        automation_id=claimed["automation_id"],
        approval_id=approval_id,
        detail_json=json.dumps(detail),
    )
    claimed["executed_at"] = now.isoformat()
    return {"approval": _approval_out(owner, claimed), "activity": _activity_out(owner, act)}


@router.post("/approvals/{approval_id}/reject")
def reject_approval(approval_id: str, request: Request) -> dict:
    owner = _owner_id(request)
    _rate(owner)
    now = _now_dt()
    _sweep(owner, now)
    claimed = db.approval_claim(owner, approval_id, "rejected", now.isoformat())
    if claimed is None:
        row = db.approval_get(owner, approval_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Approval not found")
        raise HTTPException(status_code=409, detail={"state": row["status"]})
    act = db.activity_add(
        owner,
        "rejected",
        legibility.rejected_summary(claimed["summary"]),
        automation_id=claimed["automation_id"],
        approval_id=approval_id,
    )
    return {"approval": _approval_out(owner, claimed), "activity": _activity_out(owner, act)}


# ── activity ─────────────────────────────────────────────────────────────────


@router.get("/activity")
def list_activity(request: Request, limit: int = 50, before: str | None = None) -> dict:
    owner = _owner_id(request)
    rows = db.activity_list(owner, limit=limit, before=before)
    return {"entries": [_activity_out(owner, r) for r in rows]}
