"""The Scheduler engine: due selection, restart-coalesce (CAS claim), daily/interval
next-run, failure isolation + exponential backoff + reset, loop survival,
quarantine, the budget gate, shutdown, and adopt_session_data re-owning.

Scheduler(now_fn=…) is constructed but tick(now) is called directly — no thread,
no sleeps. All time injected.
"""

from datetime import datetime, timedelta, timezone

import pytest
from src import db, llm
from src.schema import ModuleConfig
from src.services import actions, runtime

NOW = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clear_runtime_limiter():
    # The runtime's gen-rate limiter is a module-level instance; clear it so
    # budget_ok is deterministic per test regardless of order.
    runtime._runtime_limiter._hits.clear()
    yield


def _owner():
    return db.ensure_session(None)


def _mk(owner, action_type, action_json, *, next_run="2020-01-01T00:00:00+00:00", interval=3600):
    return db.automation_create(
        owner,
        page_id=None,
        name=action_type,
        description="",
        action_type=action_type,
        action_json=action_json,
        schedule_kind="interval",
        interval_secs=interval,
        daily_at=None,
        trust_dial=1,
        next_run_at=next_run,
    )


def _mk_learn(owner, **kw):
    return _mk(owner, "learn", '{"type":"learn","lookback_days":7,"max_facts":3}', **kw)


def _mk_note_module(owner):
    cfg = ModuleConfig(
        title="M", components=[{"id": "n", "type": "note", "label": "N"}], state={"n": ""}
    )
    return db.insert_module(owner, cfg)


# ── due selection ────────────────────────────────────────────────────────────


def test_due_selection_past_runs_future_and_disabled_do_not():
    owner = _owner()
    _mk_learn(owner, next_run="2020-01-01T00:00:00+00:00")  # past → due
    _mk_learn(owner, next_run="2999-01-01T00:00:00+00:00")  # future → not due
    dis = _mk_learn(owner, next_run="2020-01-01T00:00:00+00:00")
    db.automation_patch(owner, dis["id"], enabled=False)  # disabled → not due
    assert runtime.Scheduler(now_fn=lambda: NOW).tick(NOW) == 1


# ── restart-coalesce: exactly one run, next_run from now, CAS proven ─────────


def test_restart_coalesces_to_one_and_advances_from_now():
    owner = _owner()
    a = _mk_learn(owner, next_run="2020-01-01T00:00:00+00:00", interval=3600)
    s = runtime.Scheduler(now_fn=lambda: NOW)
    assert s.tick(NOW) == 1  # three days stale → ONE run, not 72 replays
    row = db.automation_get(owner, a["id"])
    assert row["next_run_at"] == (NOW + timedelta(seconds=3600)).isoformat()
    assert s.tick(NOW) == 0  # second tick claims nothing (CAS token moved)


# ── next-run arithmetic ──────────────────────────────────────────────────────


def test_compute_next_run_interval():
    nxt = runtime._compute_next_run(
        {"schedule_kind": "interval", "interval_secs": 600, "daily_at": None}, NOW
    )
    assert nxt == NOW + timedelta(seconds=600)


def test_compute_next_run_daily_today_vs_tomorrow():
    row = {"schedule_kind": "daily", "daily_at": "07:30", "interval_secs": None}
    before = datetime(2026, 7, 6, 7, 29, tzinfo=timezone.utc)
    assert runtime._compute_next_run(row, before) == datetime(
        2026, 7, 6, 7, 30, tzinfo=timezone.utc
    )
    after = datetime(2026, 7, 6, 7, 31, tzinfo=timezone.utc)
    assert runtime._compute_next_run(row, after) == datetime(2026, 7, 7, 7, 30, tzinfo=timezone.utc)


# ── failure isolation + backoff doubling + cap + reset ───────────────────────


def test_failure_isolation_healthy_sibling_runs():
    owner = _owner()
    bad = _mk(owner, "sort", '{"type":"sort","module_id":"gone","component_id":"c","by":"date"}')
    good = _mk_learn(owner)
    runtime.Scheduler(now_fn=lambda: NOW).tick(NOW)
    assert db.automation_get(owner, bad["id"])["last_status"] == "failed"
    assert db.automation_get(owner, good["id"])["last_status"] == "ran"


def test_backoff_doubles_caps_and_resets(monkeypatch):
    monkeypatch.setenv("TRUS_RUNTIME_BACKOFF_BASE", "10")
    monkeypatch.setenv("TRUS_RUNTIME_BACKOFF_CAP", "35")
    owner = _owner()
    a = _mk(
        owner,
        "sort",
        '{"type":"sort","module_id":"m","component_id":"c","by":"date"}',
        interval=3600,
    )
    mode = {"fail": True}

    def maybe(owner, payload, ctx):
        if mode["fail"]:
            raise RuntimeError("boom")
        return actions.ExecResult({"n": 0, "module_title": "M", "by": "date"})

    monkeypatch.setitem(
        actions.ACTION_SPECS, "sort", actions.ActionSpec("autonomous", False, False, False, maybe)
    )
    s = runtime.Scheduler(now_fn=lambda: NOW)

    s.tick(NOW)  # fail #1: base*2^1 = 20
    row = db.automation_get(owner, a["id"])
    assert row["failure_count"] == 1
    assert row["next_run_at"] == (NOW + timedelta(seconds=20)).isoformat()

    s.tick(NOW + timedelta(seconds=20))  # fail #2: 40 capped → 35
    row = db.automation_get(owner, a["id"])
    assert row["failure_count"] == 2
    assert row["next_run_at"] == (NOW + timedelta(seconds=20) + timedelta(seconds=35)).isoformat()

    s.tick(NOW + timedelta(seconds=55))  # fail #3: 80 capped → 35
    assert db.automation_get(owner, a["id"])["failure_count"] == 3

    mode["fail"] = False
    s.tick(NOW + timedelta(seconds=90))  # success → reset to 0, next = now + interval
    row = db.automation_get(owner, a["id"])
    assert row["failure_count"] == 0
    assert row["last_status"] == "ran"
    assert row["next_run_at"] == (NOW + timedelta(seconds=90) + timedelta(seconds=3600)).isoformat()


# ── loop survival: a tick bug never kills the runtime ────────────────────────


def test_loop_survives_tick_exception(monkeypatch):
    monkeypatch.setenv("TRUS_RUNTIME", "1")
    monkeypatch.setenv("TRUS_RUNTIME_TICK_SECS", "0")
    s = runtime.Scheduler(now_fn=lambda: NOW)
    calls = {"n": 0}

    def boom(now):
        calls["n"] += 1
        s._stop.set()  # let the loop exit after this iteration
        raise RuntimeError("tick blew up")

    monkeypatch.setattr(s, "tick", boom)
    s._loop()  # must catch + log, never propagate
    assert calls["n"] == 1


# ── quarantine: corrupt action_json auto-disables, siblings still run ────────


def test_quarantine_disables_and_isolates():
    owner = _owner()
    bad = _mk(owner, "watch", "{not valid json")
    good = _mk_learn(owner)
    runtime.Scheduler(now_fn=lambda: NOW).tick(NOW)
    brow = db.automation_get(owner, bad["id"])
    assert brow["enabled"] == 0 and brow["last_status"] == "failed"
    assert db.automation_get(owner, good["id"])["last_status"] == "ran"
    entries = db.activity_list(owner, limit=10)
    assert any(e["kind"] == "failed" for e in entries)


# ── budget gate: LLM skip journals 'skipped', zero LLM, A's cap ≠ B's ────────


def test_budget_skip_journals_skipped_and_isolates_owners(monkeypatch):
    monkeypatch.setenv("TRUS_DAILY_COST_CAP_USD", "0.01")
    monkeypatch.setenv("TRUS_TOKEN_COST_IN", "1")  # $1 per 1k input tokens
    owner_a, owner_b = _owner(), _owner()
    db.add_gen_event(owner_a, "automation", "ok", "p", "m", 10, 1000, 0)  # A over cap ($1)

    calls = {"n": 0}

    def gen(*a, **k):
        calls["n"] += 1
        llm.last_call.set(llm.GenResult("digest", "test", "test"))
        return llm.GenResult("digest", "test", "test")

    monkeypatch.setattr("src.services.actions.llm.generate", gen)

    ma, mb = _mk_note_module(owner_a), _mk_note_module(owner_b)
    a = _mk(
        owner_a, "summarize", f'{{"type":"summarize","module_id":"{ma.id}","component_id":"n"}}'
    )
    b = _mk(
        owner_b, "summarize", f'{{"type":"summarize","module_id":"{mb.id}","component_id":"n"}}'
    )

    runtime.Scheduler(now_fn=lambda: NOW).tick(NOW)

    arow = db.automation_get(owner_a, a["id"])
    assert arow["last_status"] == "skipped"  # A held by its own cap
    a_entry = db.activity_list(owner_a, limit=5)[0]
    assert a_entry["kind"] == "skipped"

    brow = db.automation_get(owner_b, b["id"])
    assert brow["last_status"] == "ran"  # B unaffected by A's cap
    assert calls["n"] == 1  # LLM ran once (B only) — A spent zero


# ── shutdown ─────────────────────────────────────────────────────────────────


def test_tick_takes_no_new_work_when_stopped():
    owner = _owner()
    _mk_learn(owner)
    s = runtime.Scheduler(now_fn=lambda: NOW)
    s._stop.set()
    assert s.tick(NOW) == 0


def test_start_stop_joins_within_timeout(monkeypatch):
    monkeypatch.setenv("TRUS_RUNTIME_TICK_SECS", "0.01")
    s = runtime.Scheduler(now_fn=lambda: NOW)
    s.start()
    s.stop(join_timeout=2.0)
    assert s._thread is not None and not s._thread.is_alive()


# ── adopt_session_data re-owns automations + approvals + activity ────────────


def test_adopt_reowns_all_three_tables():
    old, new = "anon-sid", "user-id"
    auto = db.automation_create(
        old,
        page_id=None,
        name="A",
        description="",
        action_type="send_email",
        action_json='{"type":"send_email","to":"a@b.co","subject":"S"}',
        schedule_kind="interval",
        interval_secs=3600,
        daily_at=None,
        trust_dial=1,
        next_run_at="2020-01-01T00:00:00+00:00",
    )
    db.approval_create(
        old, auto["id"], "send_email", "{}", "sum", None, "2999-01-01T00:00:00+00:00"
    )
    db.activity_add(old, "held", "x", automation_id=auto["id"])

    db.adopt_session_data(old, new)

    assert len(db.automation_list(new)) == 1 and db.automation_list(old) == []
    assert db.approval_pending_count(new) == 1 and db.approval_pending_count(old) == 0
    assert len(db.activity_list(new)) == 1 and db.activity_list(old) == []
