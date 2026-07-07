"""The always-on per-owner runtime: one scheduler daemon thread multiplexing
owner-tagged rows in the `automations` table. Isolation is owner-scoped SQL.

Server-side runtime automation — NOT schema.Automation (a client-side module
rule). The engine mechanics (injectable clock, Event.wait loop, public tick,
advance-before-execute CAS claim, restart-coalesce catch-up, exponential backoff
on executor exceptions only, the budget gate) are wired to the action model:
each due automation either parks (holds for a tap) or executes exactly once.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Callable
from datetime import datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo

from src import db
from src.routes.deps import _RateLimiter
from src.services import actions, legibility

_log = logging.getLogger(__name__)


# Env knobs — read fresh per call (function, not import-time constant) so
# conftest's _isolate_llm_env can isolate them per test.
def _tick_secs() -> float:
    return float(os.environ.get("TRUS_RUNTIME_TICK_SECS", "15"))


def _batch() -> int:
    return int(os.environ.get("TRUS_RUNTIME_BATCH", "20"))


def _backoff_base() -> float:
    return float(os.environ.get("TRUS_RUNTIME_BACKOFF_BASE", "60"))


def _backoff_cap() -> float:
    return float(os.environ.get("TRUS_RUNTIME_BACKOFF_CAP", "21600"))


def _gen_rate_max() -> int:
    return int(os.environ.get("TRUS_RUNTIME_GEN_RATE_MAX", "10"))


def _gen_rate_window() -> float:
    return float(os.environ.get("TRUS_RUNTIME_GEN_RATE_WINDOW", "3600"))


def _max_failures() -> int:
    return int(os.environ.get("TRUS_RUNTIME_MAX_FAILURES", "10"))


def _schedule_tz() -> tzinfo:
    """The IANA zone a daily_at is interpreted in (TRUS_TZ). Unset ⇒ UTC (the
    historical behavior); an unknown/invalid name also falls back to UTC rather
    than crashing the tick. Read fresh per call (conftest isolates it)."""
    name = os.environ.get("TRUS_TZ", "").strip()
    if not name:
        return timezone.utc
    try:
        return ZoneInfo(name)
    except Exception:
        return timezone.utc


# The scheduler's OWN limiter instance — never eats the interactive _gen_limiter
# budget (a chatty voice/live session and a scheduled digest are separate rates).
_runtime_limiter = _RateLimiter(max_calls=10, window_secs=3600)


def budget_ok(owner: str, now: datetime) -> bool:
    """Bool-returning twin of routes.deps._check_gen_budget (no HTTPException
    off-request). Per-owner rate via the runtime's own limiter, PLUS the SAME
    shared TRUS_DAILY_COST_CAP_USD wallet against db.owner_cost_today — scheduled
    and interactive spend share one owner-day budget (deliberate)."""
    if not _runtime_limiter.allow(
        owner, now=now.timestamp(), max_calls=_gen_rate_max(), window_secs=_gen_rate_window()
    ):
        return False
    cap_raw = os.environ.get("TRUS_DAILY_COST_CAP_USD", "").strip()
    if cap_raw:
        cap = float(cap_raw)
        if cap > 0 and db.owner_cost_today(owner)["cost_usd"] >= cap:
            return False
    return True


def _compute_next_run(row: dict, now: datetime) -> datetime:
    """The next fire, ALWAYS computed from now (restart-coalesce: three days down
    ≠ 72 replayed digests). interval → now + interval; daily → the next HH:MM in
    TRUS_TZ (default UTC) strictly after now, returned as a UTC instant."""
    if row["schedule_kind"] == "interval":
        return now + timedelta(seconds=int(row["interval_secs"]))
    h, m = str(row["daily_at"]).split(":")
    local_now = now.astimezone(_schedule_tz())
    cand = local_now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
    if cand <= local_now:
        cand += timedelta(days=1)
    return cand.astimezone(timezone.utc)


def _ran_detail(automation: dict, payload: dict, result: dict) -> dict | None:
    """Deep-link + badge refs for a journal row (RUN-6 zoom-to-portal)."""
    detail: dict = {}
    mid = payload.get("module_id")
    if mid:
        detail["module_id"] = mid
    if automation.get("page_id"):
        detail["page_id"] = automation["page_id"]
    if result.get("simulated"):
        detail["simulated"] = True
    return detail or None


def run_once(
    owner: str, automation: dict, now: datetime, *, next_run_at: str | None
) -> tuple[dict | None, dict | None]:
    """Execute one automation through the exact same path the scheduler and the
    run-now route both use: validate → park-or-(budget-gate)-execute → journal
    exactly one row → bookkeeping (advance/backoff, last_status, scratch state).
    Returns (activity_row_or_None, approval_row_or_None). Raises nothing that a
    caller must translate — every branch is journaled honestly.

    `next_run_at` is the slot to persist on a normal finish (the scheduler passes
    the CAS-advanced slot; run-now passes the automation's current slot to leave
    the schedule untouched). A backoff overrides it on an executor exception."""
    aid = automation["id"]
    name = automation["name"]
    action_type = automation["action_type"]

    # 1. validate action_json (quarantine: auto-disable + a legible 'failed' row).
    try:
        action = actions.parse_action(automation["action_json"])
    except Exception:
        db.automation_mark_run(
            owner,
            aid,
            last_run_at=now.isoformat(),
            next_run_at=next_run_at,
            last_status="failed",
            failure_count=automation["failure_count"],
            enabled=False,
        )
        act = db.activity_add(
            owner,
            "failed",
            legibility.failed_summary(name, "configuration unreadable"),
            automation_id=aid,
            detail_json=json.dumps({"reason": "quarantine"}),
        )
        return act, None

    spec = actions.ACTION_SPECS.get(action_type)
    if spec is None:
        db.automation_mark_run(
            owner,
            aid,
            last_run_at=now.isoformat(),
            next_run_at=next_run_at,
            last_status="failed",
            failure_count=automation["failure_count"],
        )
        act = db.activity_add(
            owner,
            "failed",
            legibility.failed_summary(name, "unknown action type"),
            automation_id=aid,
            detail_json=json.dumps({"reason": "unknown_action"}),
        )
        return act, None

    payload = action.model_dump()

    # 2. requires_approval? → park (nothing executes).
    if actions.requires_approval(action_type, automation["trust_dial"]):
        approval, held = actions.park(owner, automation, payload, now)
        db.automation_mark_run(
            owner,
            aid,
            last_run_at=now.isoformat(),
            next_run_at=next_run_at,
            last_status="held",
            failure_count=0,
        )
        return held, approval

    # 3. uses_llm budget gate — a hold spends ZERO tokens.
    if spec.uses_llm and not budget_ok(owner, now):
        db.automation_mark_run(
            owner,
            aid,
            last_run_at=now.isoformat(),
            next_run_at=next_run_at,
            last_status="skipped",
            failure_count=automation["failure_count"],
        )
        act = db.activity_add(
            owner,
            "skipped",
            "Paused — today's usage budget is reached.",
            automation_id=aid,
            detail_json=json.dumps({"reason": "budget"}),
        )
        return act, None

    # 4. execute.
    ctx = actions.ExecContext(
        automation_id=aid,
        page_id=automation["page_id"],
        state=json.loads(automation["state_json"] or "{}"),
        now=now,
        interval_secs=automation["interval_secs"],
    )
    try:
        res = spec.execute(owner, payload, ctx)
    except actions.ConflictYield:
        db.automation_mark_run(
            owner,
            aid,
            last_run_at=now.isoformat(),
            next_run_at=next_run_at,
            last_status="skipped",
            failure_count=automation["failure_count"],
        )
        act = db.activity_add(
            owner,
            "skipped",
            "Skipped — your live edit took precedence.",
            automation_id=aid,
            detail_json=json.dumps({"reason": "conflict"}),
        )
        return act, None
    except Exception as e:  # failure isolation: raw detail → log only, class name journaled
        _log.exception("automation %s failed", aid)
        failures = automation["failure_count"] + 1
        disabled = failures >= _max_failures()  # chronic failure → stop retrying, turn it off
        backoff = min(_backoff_base() * (2**failures), _backoff_cap())
        summary = legibility.failed_summary(name, actions.safe_reason(e))
        err_detail: dict = {"reason": "error", "error_class": type(e).__name__}
        if disabled:
            summary = legibility.auto_disabled_summary(summary, failures)
            err_detail["auto_disabled"] = True
        db.automation_mark_run(
            owner,
            aid,
            last_run_at=now.isoformat(),
            next_run_at=(now + timedelta(seconds=backoff)).isoformat(),
            last_status="failed",
            failure_count=failures,
            **({"enabled": False} if disabled else {}),
        )
        act = db.activity_add(
            owner,
            "failed",
            summary,
            automation_id=aid,
            detail_json=json.dumps(err_detail),
        )
        return act, None

    # success → journal 'ran', persist scratch state, reset failures.
    summary = legibility.did_do(action_type, payload, res.result)
    detail = _ran_detail(automation, payload, res.result)
    act = db.activity_add(
        owner,
        "ran",
        summary,
        automation_id=aid,
        detail_json=json.dumps(detail) if detail else None,
    )
    state_json = json.dumps(res.state) if res.state is not None else None
    if state_json is not None:
        db.automation_mark_run(
            owner,
            aid,
            last_run_at=now.isoformat(),
            next_run_at=next_run_at,
            last_status="ran",
            failure_count=0,
            state_json=state_json,
        )
    else:
        db.automation_mark_run(
            owner,
            aid,
            last_run_at=now.isoformat(),
            next_run_at=next_run_at,
            last_status="ran",
            failure_count=0,
        )
    return act, None


class Scheduler:
    def __init__(self, now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self._now_fn = now_fn  # injectable clock — tests never sleep
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._reconcile_interrupted(self._now_fn())
        self._thread = threading.Thread(target=self._loop, name="trus-runtime", daemon=True)
        self._thread.start()

    def _reconcile_interrupted(self, now: datetime) -> None:
        """Boot honesty: an automation left with its in-flight marker set (a hard
        process death mid-run — every normal outcome clears it) gets exactly one
        legible 'failed' row and the marker cleared, so a crashed run is never a
        silent loss."""
        for row in db.automations_interrupted():
            db.activity_add(
                row["owner"],
                "failed",
                legibility.interrupted_summary(row["name"]),
                automation_id=row["id"],
                detail_json=json.dumps({"reason": "interrupted"}),
            )
            db.automation_clear_run(row["owner"], row["id"])

    def stop(self, join_timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=join_timeout)

    def _loop(self) -> None:
        while not self._stop.wait(_tick_secs()):  # Event.wait IS the sleep → instant shutdown
            if os.environ.get("TRUS_RUNTIME", "1") != "1":
                continue
            try:
                self.tick(self._now_fn())
            except Exception:  # outer belt: a tick bug never kills the runtime
                _log.exception("runtime tick failed")

    def tick(self, now: datetime) -> int:
        """PUBLIC — tests drive this directly, no thread. Sweeps expiry, then runs
        each due automation exactly once (the CAS claim advances next_run BEFORE
        executing, so a crash mid-run can never hot-loop or double-fire)."""
        self._sweep(now)
        ran = 0
        for row in db.automations_due(now.isoformat(), limit=_batch()):
            if self._stop.is_set():
                break  # finish current row, take no new work
            nxt = _compute_next_run(row, now)
            if not db.automation_claim(row["id"], row["next_run_at"], nxt.isoformat()):
                continue  # a future second worker (or restart catch-up) lost the claim
            db.automation_mark_started(row["id"], now.isoformat())  # in-flight marker
            run_once(row["owner"], row, now, next_run_at=nxt.isoformat())
            ran += 1
        return ran

    def _sweep(self, now: datetime) -> None:
        for row in db.approval_sweep_expired_global(now.isoformat()):
            db.activity_add(
                row["owner"],
                "expired",
                legibility.expired_summary(row["summary"]),
                automation_id=row["automation_id"],
                approval_id=row["id"],
            )
