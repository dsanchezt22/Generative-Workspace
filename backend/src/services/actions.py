"""Action registry + tier routing + executors + park.

Server-side runtime automation — NOT schema.Automation (a client-side module
rule). One frozen `ACTION_SPECS` registry carries, per action type, the hard
floor / irreversibility / LLM-usage / seam-stub flags and the executor. The
tier taxonomy is a build invariant living in code, not DB rows (AUT-4's floor
is declarative and meta-testable in one parametrized test).
"""

from __future__ import annotations

import contextlib
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from pydantic import TypeAdapter

from src import db, llm
from src.routes.deps import _llm_error_detail
from src.schema import LLMError
from src.schema_automations import AutoAction
from src.services import legibility, live_data, orchestrator

Tier = Literal["autonomous", "consequential"]

_ACTION_ADAPTER: TypeAdapter = TypeAdapter(AutoAction)


def parse_action(action_json: str):
    """Validate a stored action_json against the typed AutoAction union. Raises
    on unreadable/unknown — the caller quarantines (auto-disable + 'failed')."""
    return _ACTION_ADAPTER.validate_json(action_json)


# ── Execution plumbing ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class ExecContext:
    """Per-run context the ACTION_SPECS signature carries beyond (owner, payload):
    the automation's own scratch state (watch's `armed` flag), injected `now`
    (tests never sleep), the surface it belongs to, and its interval (watch's
    live-fetch refresh bound)."""

    automation_id: str
    page_id: str | None
    state: dict
    now: datetime
    interval_secs: int | None = None


@dataclass
class ExecResult:
    result: dict  # arbitrary executor output → legibility.did_do / activity detail
    state: dict | None = None  # new automation state_json to persist (None → unchanged)


Executor = Callable[[str, dict, ExecContext], ExecResult]


@dataclass(frozen=True)
class ActionSpec:
    # Fail-closed floor: a NEW consequential executor is irreversible=True until
    # explicitly reviewed down (test_consequential_floor_is_irreversible_unless_
    # allowlisted guards it; today archive_module is the only reviewed-reversible
    # exception).
    floor: Tier
    irreversible: bool  # True → AUT-4 hard floor: NEVER autonomous, dial ignored
    uses_llm: bool  # True → budget MUST pass before execution
    stub: bool  # True → SEAM-1: executor simulates honestly, results badged simulated
    execute: Executor


class ConflictYield(Exception):
    """A module write lost the optimistic-rev race 3 times — the automation yields
    to the human's live edit. The runner journals 'skipped' (reason conflict),
    never a failure/backoff."""


# ── Shared module-write path (state-only, never structural, HUMAN WINS) ──────


def _update_component_state(
    owner: str, module_id: str, fn: Callable[[object, object], object], component_id: str
) -> bool:
    """Read-modify-write `state[component_id]` through the module-update path
    (bumps rev, writes module_versions), retrying on a rev conflict up to 3 times.
    Returns False when the target module is missing (owner-scoped ⇒ a foreign id
    is a miss, not a leak); raises ConflictYield after 3 lost races."""
    for _ in range(3):
        mod = db.get_module(owner, module_id)
        if mod is None:
            return False
        cfg = mod.config.model_copy(deep=True)
        cfg.state[component_id] = fn(cfg.state.get(component_id), cfg)
        try:
            db.update_module(owner, module_id, cfg, expected_rev=mod.rev)
            return True
        except db.RevConflict:
            continue
    raise ConflictYield()


def _write_state(owner: str, module_id: str, component_id: str, value: object) -> bool:
    return _update_component_state(owner, module_id, lambda _cur, _cfg: value, component_id)


def _deliver(
    owner: str,
    module_id: str,
    component_id: str,
    *,
    title: str,
    body: str,
    badge: str,
    now: datetime,
) -> bool:
    """Land a feed entry. A Note target replaces its text; any other component
    gets a `{ts,title,body,badge}` list entry appended — the state SHAPE is
    written without validating the component type (the trusted Feed renderer
    arrives in a later wave)."""

    def fn(current: object, cfg: object) -> object:
        comp = next((c for c in cfg.components if c.id == component_id), None)  # type: ignore[attr-defined]
        if comp is not None and comp.type == "note":
            return body
        entry = {"ts": now.isoformat(), "title": title, "body": body, "badge": badge}
        items = list(current) if isinstance(current, list) else []
        items.append(entry)
        return items

    return _update_component_state(owner, module_id, fn, component_id)


def _numeric(value: object) -> float:
    """A number as-is, or the count of a list/checklist's items."""
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, list):
        return float(len(value))
    return 0.0


# ── Off-request LLM helper (records gen_event so the cost cap self-enforces) ──

_SUMMARIZE_SYSTEM = (
    "Summarize this page's current state in <=80 words of plain text. "
    "No markup, no lists, no headings."
)
_DRAFT_SYSTEM = (
    "You compose a short, plain-text draft message from an instruction. "
    "Output only the message body — no markup, no preamble."
)
_LEARN_SYSTEM = (
    "From the user's recent messages, infer durable one-line PATTERN facts about "
    "them (habits, preferences, routines). Output ONLY a JSON array of short "
    "strings. If nothing durable stands out, output []."
)


def _llm_generate(owner: str, prompt: str, system: str, *, expect_text: bool = True) -> str:
    """Run a model call for an automation and record a gen_event(kind='automation')
    from llm.last_call — the same provenance the interactive `_track` records, so
    scheduled + interactive spend share one owner-day cost wallet. Re-raises
    LLMError untouched (the runner sanitizes it).

    `expect_text=True` (the default — every caller here wants prose or a JSON
    array, never a ModuleConfig) tells the stub provider to return honest,
    clearly-labeled placeholder prose instead of the module-generation stub's
    ModuleConfig-shaped JSON, which would otherwise land as garbage inside a
    digest/draft Feed entry when no live model is configured."""
    t0 = time.monotonic()
    outcome = "ok"
    try:
        res = llm.generate(prompt, system=system, expect_text=expect_text)
        return res.text
    except LLMError:
        outcome = "error"
        raise
    finally:
        last = llm.last_call.get()
        if outcome == "ok" and last is not None and last.degraded:
            outcome = "degraded"
        with contextlib.suppress(Exception):
            db.add_gen_event(
                owner,
                "automation",
                outcome,
                last.provider if last else None,
                last.model if last else None,
                int((time.monotonic() - t0) * 1000),
                last.tokens_in if last else None,
                last.tokens_out if last else None,
            )


# ── Executors (all sync, all owner-scoped via db functions) ──────────────────


def _exec_watch(owner: str, payload: dict, ctx: ExecContext) -> ExecResult:
    provider = str(payload["provider"])
    query = payload.get("query") or {}
    module_id, component_id = payload["module_id"], payload["component_id"]
    op, threshold = payload.get("op"), payload.get("threshold")
    data = live_data.fetch(provider, query, refresh_secs=ctx.interval_secs or 600)
    value = data.get("value")
    armed = bool(ctx.state.get("armed", True))
    flagged = False
    new_state: dict | None = None
    if value is not None and op is not None and threshold is not None:
        crossed = (op == "over" and value > threshold) or (op == "under" and value < threshold)
        if crossed and armed:
            flagged = True
            _write_state(owner, module_id, component_id, value)
            fm, fc = payload.get("feed_module_id"), payload.get("feed_component_id")
            if fm and fc:
                label = legibility._watch_label(payload)
                _deliver(
                    owner,
                    fm,
                    fc,
                    title="Watch alert",
                    body=f"{label}: {value}",
                    badge="alert",
                    now=ctx.now,
                )
            new_state = {"armed": False}
        elif not crossed and not armed:
            new_state = {"armed": True}  # back on the safe side → re-arm
    return ExecResult({"value": value, "flagged": flagged, "error": data.get("error")}, new_state)


def _exec_sort(owner: str, payload: dict, ctx: ExecContext) -> ExecResult:
    module_id, component_id = payload["module_id"], payload["component_id"]
    by = str(payload.get("by", "date"))
    captured: dict = {"n": 0, "module_title": ""}

    def fn(current: object, cfg: object) -> object:
        captured["module_title"] = cfg.title  # type: ignore[attr-defined]
        if not isinstance(current, list):
            return current
        items = list(current)
        captured["n"] = len(items)
        items.sort(key=lambda it: str(it.get(by, "")) if isinstance(it, dict) else str(it))
        return items

    if not _update_component_state(owner, module_id, fn, component_id):
        raise ValueError("sort target module not found")
    return ExecResult({"n": captured["n"], "module_title": captured["module_title"], "by": by})


def _exec_track(owner: str, payload: dict, ctx: ExecContext) -> ExecResult:
    src_mod, src_comp = payload["source_module_id"], payload["source_component_id"]
    tgt_mod, tgt_comp = payload["module_id"], payload["component_id"]
    label = payload.get("label") or "value"
    smod = db.get_module(owner, src_mod)
    if smod is None:
        raise ValueError("track source module not found")
    value = _numeric(smod.config.state.get(src_comp))
    date = ctx.now.date().isoformat()
    captured: dict = {"module_title": ""}

    def fn(current: object, cfg: object) -> object:
        captured["module_title"] = cfg.title  # type: ignore[attr-defined]
        items = list(current) if isinstance(current, list) else []
        items.append({"date": date, "value": value})
        return items

    if not _update_component_state(owner, tgt_mod, fn, tgt_comp):
        raise ValueError("track target module not found")
    return ExecResult({"metric": label, "value": value, "module_title": captured["module_title"]})


def _exec_remind(owner: str, payload: dict, ctx: ExecContext) -> ExecResult:
    module_id, component_id = payload["module_id"], payload["component_id"]
    mod = db.get_module(owner, module_id)
    if mod is None:
        raise ValueError("remind module not found")
    st = mod.config.state.get(component_id)
    today = ctx.now.date().isoformat()
    pending: list[str] = []
    if isinstance(st, dict) and isinstance(st.get("rows"), list):  # Tracker
        for row in st["rows"]:
            if isinstance(row, dict) and today not in (row.get("done") or []):
                pending.append(str(row.get("name", "?")))
    elif isinstance(st, list):  # Checklist
        for it in st:
            if isinstance(it, dict) and not it.get("done"):
                pending.append(str(it.get("text", "?")))
    body = f"{len(pending)} not done today: {', '.join(pending)}" if pending else "all done today"
    fm, fc = payload.get("feed_module_id"), payload.get("feed_component_id")
    if pending and fm and fc:
        _deliver(owner, fm, fc, title="Reminder", body=body, badge="reminder", now=ctx.now)
    return ExecResult({"pending": pending, "body": body})


def _exec_summarize(owner: str, payload: dict, ctx: ExecContext) -> ExecResult:
    module_id, component_id = payload["module_id"], payload["component_id"]
    source_ids = payload.get("source_module_ids") or []
    configs = []
    if source_ids:
        for mid in source_ids:
            m = db.get_module(owner, mid)
            if m is not None:
                configs.append(m.config)
    elif ctx.page_id:
        configs = [m.config for m in db.list_modules(owner, ctx.page_id)]
    target = db.get_module(owner, module_id)
    name = target.config.title if target is not None else ""
    prompt = (
        "Summarize the current state of these tools for me."
        + orchestrator._module_context(configs)
        + orchestrator._profile_block(db.profile_list(owner))
    )
    text = _llm_generate(owner, prompt, _SUMMARIZE_SYSTEM)
    _deliver(
        owner,
        module_id,
        component_id,
        title=f"{name} digest",
        body=text,
        badge="digest",
        now=ctx.now,
    )
    return ExecResult({"n": len(configs), "name": name, "text": legibility._trunc(text)})


def _exec_draft(owner: str, payload: dict, ctx: ExecContext) -> ExecResult:
    module_id, component_id = payload["module_id"], payload["component_id"]
    recipient, instruction = payload.get("recipient", ""), payload.get("instruction", "")
    text = _llm_generate(
        owner, f"Draft a message to {recipient}. Instruction: {instruction}", _DRAFT_SYSTEM
    )
    target = db.get_module(owner, module_id)
    module_title = target.config.title if target is not None else ""
    _deliver(
        owner,
        module_id,
        component_id,
        title=f"Draft for {recipient}",
        body=text,
        badge="draft",
        now=ctx.now,
    )
    return ExecResult({"topic": legibility._trunc(instruction, 60), "module_title": module_title})


def _exec_learn(owner: str, payload: dict, ctx: ExecContext) -> ExecResult:
    lookback = int(payload.get("lookback_days", 7))
    max_facts = int(payload.get("max_facts", 3))
    since = (ctx.now - timedelta(days=lookback)).isoformat()
    msgs = db.recent_user_messages(owner, since, limit=50)
    if not msgs:
        return ExecResult({"n": 0})
    joined = "\n".join(f"- {m}" for m in msgs)
    text = _llm_generate(
        owner,
        f"Recent messages:\n{joined}\n\nReturn up to {max_facts} pattern facts as a JSON array.",
        _LEARN_SYSTEM,
    )
    added = 0
    seen: set[str] = set()
    for fact in _parse_str_list(text)[:max_facts]:
        fact = str(fact).strip()[:500]
        if fact and fact.lower() not in seen:
            seen.add(fact.lower())
            db.profile_add(owner, "pattern", fact, source="activity")
            added += 1
    return ExecResult({"n": added})


def _parse_str_list(text: str) -> list[str]:
    try:
        data = json.loads(orchestrator._strip_codefence(text))
    except (json.JSONDecodeError, ValueError):
        return []
    return [str(x) for x in data] if isinstance(data, list) else []


def _exec_archive_module(owner: str, payload: dict, ctx: ExecContext) -> ExecResult:
    mod = db.set_archived(owner, payload["module_id"], True)
    if mod is None:
        raise ValueError("archive target module not found")
    return ExecResult({"module_title": mod.config.title})


def _exec_send_email_stub(owner: str, payload: dict, ctx: ExecContext) -> ExecResult:
    # SEAM-1 honest stub: never claims real sending; the badged 'simulated' record
    # IS the activity row the runner journals.
    return ExecResult(
        {"simulated": True, "to": payload.get("to", ""), "subject": payload.get("subject", "")}
    )


def _exec_message_stub(owner: str, payload: dict, ctx: ExecContext) -> ExecResult:
    return ExecResult({"simulated": True, "to": payload.get("to", "")})


def _exec_pay_stub(owner: str, payload: dict, ctx: ExecContext) -> ExecResult:
    return ExecResult(
        {
            "simulated": True,
            "payee": payload.get("payee", ""),
            "amount_usd": payload.get("amount_usd", 0),
        }
    )


def _exec_delete_data(owner: str, payload: dict, ctx: ExecContext) -> ExecResult:
    target, target_id = payload["target"], payload["target_id"]
    ok = (
        db.delete_module(owner, target_id)
        if target == "module"
        else db.delete_page(owner, target_id)
    )
    if not ok:
        raise ValueError("delete target not found")
    return ExecResult({"target": target, "target_id": target_id})


# ── The frozen registry (12 types, every one with a real executor) ───────────
#
# INVARIANT (test_no_spec_is_both_llm_and_irreversible): no spec is BOTH uses_llm
# AND irreversible. _freeze_payload is a documented no-op for uses_llm actions
# (zero-spend park freezes the SPEC, not composed content), so a spec with both
# flags would let "approve" authorize model output that was never previewed for
# an irreversible delivery. The escape for a future compose-and-send action is
# two-stage approval: approve spend → compose → approve the frozen bytes — never
# a single ActionSpec carrying both flags.

ACTION_SPECS: dict[str, ActionSpec] = {
    # autonomous floor — reversible, internal to the owner's workspace
    "watch": ActionSpec("autonomous", False, False, False, _exec_watch),
    "sort": ActionSpec("autonomous", False, False, False, _exec_sort),
    "track": ActionSpec("autonomous", False, False, False, _exec_track),
    "remind": ActionSpec("autonomous", False, False, False, _exec_remind),
    "summarize": ActionSpec("autonomous", False, True, False, _exec_summarize),
    "draft": ActionSpec("autonomous", False, True, False, _exec_draft),
    "learn": ActionSpec("autonomous", False, True, False, _exec_learn),
    # consequential floor, REVERSIBLE inside Trus — dial 2 may run this autonomously
    "archive_module": ActionSpec("consequential", False, False, False, _exec_archive_module),
    # consequential floor + hard floor (irreversible) — always park, dial can never win
    "send_email": ActionSpec("consequential", True, False, True, _exec_send_email_stub),
    "message_human": ActionSpec("consequential", True, False, True, _exec_message_stub),
    "pay": ActionSpec("consequential", True, False, True, _exec_pay_stub),
    "delete_data": ActionSpec("consequential", True, False, False, _exec_delete_data),
}


def requires_approval(action_type: str, trust_dial: int) -> bool:
    """The single tier-routing choke point. Pure, time-free. KeyError on an
    unknown type → the caller journals a refusal (closed world)."""
    spec = ACTION_SPECS[action_type]
    if spec.irreversible:
        return True  # AUT-4: checked FIRST, dial irrelevant
    if trust_dial <= 0:
        return True  # dial 0: hold everything
    if spec.floor == "consequential":
        return trust_dial < 2  # dial 2 unlocks reversible-consequential only
    return False  # autonomous floor at dial >= 1


def safe_reason(e: Exception) -> str:
    """A sanitized failure reason for an activity summary: LLMError text passes
    through the shared sanitizer (never a raw URL/response body); anything else
    surfaces only its class name."""
    if isinstance(e, LLMError):
        return _llm_error_detail(e)
    return type(e).__name__


# ── Park (freeze + journal a consequential fire for the owner's tap) ─────────


def _approval_ttl_hours() -> int:
    return int(os.environ.get("TRUS_APPROVAL_TTL_HOURS", "72"))


def _freeze_payload(owner: str, action_type: str, payload: dict) -> dict:
    """Resolve the payload to the exact bytes approve will execute. For uses_llm
    actions this is a NO-OP (zero-spend park — the frozen payload is the spec, not
    pre-composed content; approve composes then). For non-LLM consequential
    actions any content is read NOW (e.g. send_email's body from its source
    component) so the preview shows exactly what will run."""
    p = dict(payload)
    spec = ACTION_SPECS.get(action_type)
    if spec is not None and spec.uses_llm:
        return p
    if action_type == "send_email":
        mid, cid = p.get("module_id"), p.get("component_id")
        if mid and cid:
            mod = db.get_module(owner, mid)
            if mod is not None:
                p["body"] = str(mod.config.state.get(cid, ""))
        p.setdefault("body", "")
    elif action_type == "archive_module":
        mod = db.get_module(owner, p.get("module_id", ""))
        if mod is not None:
            p["module_title"] = mod.config.title
    elif action_type == "delete_data":
        if p.get("target") == "module":
            mod = db.get_module(owner, p.get("target_id", ""))
            if mod is not None:
                p["target_name"] = mod.config.title
        else:
            pg = db.get_page(owner, p.get("target_id", ""))
            if pg is not None:
                p["target_name"] = pg.name
    return p


def park(owner: str, automation: dict, payload: dict, now: datetime) -> tuple[dict, dict | None]:
    """Freeze the fully-resolved payload, compose the future-tense summary +
    typed preview, insert a pending approval (deduped), and journal one 'held'
    row. Returns (approval_row, held_activity_row_or_None). Nothing executes.
    A second park of the same pending fire re-uses the existing approval and does
    NOT re-journal (anti-flood)."""
    aid = automation["id"]
    action_type = automation["action_type"]
    existing = db.approval_pending_for(owner, aid, action_type)
    if existing is not None:
        return existing, None
    frozen = _freeze_payload(owner, action_type, payload)
    summary = legibility.will_do(action_type, frozen)
    preview = legibility.preview(action_type, frozen)
    preview_json = preview.model_dump_json() if preview is not None else None
    expires_at = (now + timedelta(hours=_approval_ttl_hours())).isoformat()
    approval = db.approval_create(
        owner, aid, action_type, json.dumps(frozen), summary, preview_json, expires_at
    )
    activity = db.activity_add(
        owner,
        "held",
        legibility.held_summary(summary),
        automation_id=aid,
        approval_id=approval["id"],
    )
    return approval, activity
