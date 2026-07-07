"""The /api/automations + /api/approvals + /api/activity HTTP surface:
cross-owner isolation, dial clamping, PATCH-as-sole-dial-writer, DELETE cascade,
run-now-same-path, target validation, and sync-def introspection.
"""

import asyncio
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from src import db
from src.main import app
from src.routes import automations as auto_routes
from src.services import actions, runtime

NOW = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def other():
    with TestClient(app) as c:
        yield c


def _insert_module(client, components, state=None, title="M"):
    r = client.post(
        "/api/modules",
        json={"configs": [{"title": title, "components": components, "state": state or {}}]},
    )
    assert r.status_code == 201, r.text
    return r.json()[0]


def _create(client, action, trust_dial=1, name="A", schedule_kind="interval", **extra):
    body = {
        "name": name,
        "action": action,
        "schedule_kind": schedule_kind,
        "trust_dial": trust_dial,
    }
    if schedule_kind == "interval":
        body["interval_secs"] = extra.get("interval_secs", 3600)
    else:
        body["daily_at"] = extra.get("daily_at", "07:00")
    r = client.post("/api/automations", json=body)
    return r


def _ensure_owner(owner):
    with db._conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO sessions (id, created_at) VALUES (?, ?)", (owner, db._now())
        )
    return owner


# ── create: validation, dial clamp, target ownership ─────────────────────────


def test_create_returns_derived_tier_and_dial(client):
    r = _create(
        client,
        {
            "type": "watch",
            "provider": "weather",
            "query": {"place": "SF"},
            "module_id": "x",
            "component_id": "c",
        },
    )
    # watch targets an unowned module → 422
    assert r.status_code == 422


def test_create_validates_owned_module(client):
    m = _insert_module(client, [{"id": "c", "type": "note", "label": "N"}], {})
    r = _create(
        client,
        {
            "type": "watch",
            "provider": "weather",
            "query": {"place": "SF"},
            "module_id": m["id"],
            "component_id": "c",
            "op": "over",
            "threshold": 30,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["action_type"] == "watch"
    assert body["tier_floor"] == "autonomous"
    assert body["irreversible"] is False
    assert body["trust_dial"] == 1


def test_create_rejects_dial_above_one(client):
    # AUT-3: the wire model caps creation at 1 (a model can never propose elevated).
    r = _create(client, {"type": "send_email", "to": "a@b.co", "subject": "S"}, trust_dial=2)
    assert r.status_code == 422


def test_create_send_email_is_consequential_irreversible(client):
    r = _create(client, {"type": "send_email", "to": "a@b.co", "subject": "S"})
    assert r.status_code == 201
    body = r.json()
    assert body["tier_floor"] == "consequential"
    assert body["irreversible"] is True


# ── PATCH is the ONLY trust_dial writer (AUT-3) ──────────────────────────────


def test_scheduler_runs_never_touch_trust_dial():
    owner = _ensure_owner("o")
    auto = db.automation_create(
        owner,
        page_id=None,
        name="Learner",
        description="",
        action_type="learn",
        action_json='{"type":"learn","lookback_days":7,"max_facts":3}',
        schedule_kind="interval",
        interval_secs=3600,
        daily_at=None,
        trust_dial=1,
        next_run_at="2020-01-01T00:00:00+00:00",
    )
    # 3 scheduler-path runs (learn with no messages → 'ran', no LLM, no network)
    for _ in range(3):
        row = db.automation_get(owner, auto["id"])
        runtime.run_once(owner, row, NOW, next_run_at=row["next_run_at"])
    assert db.automation_get(owner, auto["id"])["trust_dial"] == 1
    # Only PATCH lifts it — and it can reach 2.
    assert db.automation_patch(owner, auto["id"], trust_dial=2)["trust_dial"] == 2


def test_patch_clamps_range_and_404s_cross_owner(client):
    m = _insert_module(client, [{"id": "c", "type": "note", "label": "N"}], {})
    auto = _create(client, {"type": "summarize", "module_id": m["id"], "component_id": "c"}).json()
    # 422 outside 0..2 (Pydantic)
    assert client.patch(f"/api/automations/{auto['id']}", json={"trust_dial": 5}).status_code == 422
    # a valid PATCH flips enabled + dial
    r = client.patch(f"/api/automations/{auto['id']}", json={"enabled": False, "trust_dial": 2})
    assert r.status_code == 200
    assert r.json()["enabled"] is False and r.json()["trust_dial"] == 2
    # unknown id → 404
    assert client.patch("/api/automations/nope", json={"enabled": True}).status_code == 404


# ── DELETE cascade-expires pending approvals ─────────────────────────────────


def test_delete_cascade_expires_pending_approvals(client):
    auto = _create(client, {"type": "send_email", "to": "a@b.co", "subject": "S"}).json()
    client.post(f"/api/automations/{auto['id']}/run")  # parks (irreversible)
    assert client.get("/api/approvals").json()["pending_count"] == 1
    assert client.delete(f"/api/automations/{auto['id']}").status_code == 204
    assert client.get("/api/approvals").json()["pending_count"] == 0
    kinds = [e["kind"] for e in client.get("/api/activity").json()["entries"]]
    assert "expired" in kinds


def test_delete_unknown_404(client):
    assert client.delete("/api/automations/nope").status_code == 404


# ── run-now = the same requires_approval / park / execute path ───────────────


def test_run_now_autonomous_executes(client, monkeypatch):
    m = _insert_module(client, [{"id": "t", "type": "number_input", "label": "T"}], {})
    monkeypatch.setattr(
        "src.services.live_data.fetch", lambda *a, **k: {"value": 40.0, "error": None}
    )
    auto = _create(
        client,
        {
            "type": "watch",
            "provider": "weather",
            "query": {"place": "SF"},
            "module_id": m["id"],
            "component_id": "t",
            "op": "over",
            "threshold": 30,
        },
    ).json()
    run = client.post(f"/api/automations/{auto['id']}/run").json()
    assert run["approval"] is None
    assert run["activity"]["kind"] == "ran"


def test_run_now_consequential_parks(client):
    auto = _create(client, {"type": "send_email", "to": "a@b.co", "subject": "S"}).json()
    run = client.post(f"/api/automations/{auto['id']}/run").json()
    assert run["approval"] is not None and run["approval"]["status"] == "pending"
    assert run["activity"]["kind"] == "held"


def test_run_unknown_404(client):
    assert client.post("/api/automations/nope/run").status_code == 404


# ── cross-owner isolation everywhere (RUN-5) ─────────────────────────────────


def test_cross_owner_isolation(client, other, monkeypatch):
    auto = _create(client, {"type": "send_email", "to": "a@b.co", "subject": "S"}).json()
    approval = client.post(f"/api/automations/{auto['id']}/run").json()["approval"]

    # owner B sees nothing of A's
    assert other.get("/api/automations").json()["automations"] == []
    assert other.get("/api/approvals").json()["pending_count"] == 0
    assert other.get("/api/activity").json()["entries"] == []

    # B cannot address A's ids
    assert other.patch(f"/api/automations/{auto['id']}", json={"enabled": False}).status_code == 404
    assert other.delete(f"/api/automations/{auto['id']}").status_code == 404
    assert other.post(f"/api/automations/{auto['id']}/run").status_code == 404

    # B approving A's approval → 404, and A's approval stays pending, executor uncalled
    def boom(owner, payload, ctx):
        raise AssertionError("must not execute across owners")

    orig = actions.ACTION_SPECS["send_email"]
    monkeypatch.setitem(
        actions.ACTION_SPECS,
        "send_email",
        actions.ActionSpec(orig.floor, orig.irreversible, orig.uses_llm, orig.stub, boom),
    )
    assert other.post(f"/api/approvals/{approval['id']}/approve").status_code == 404
    assert client.get("/api/approvals").json()["pending_count"] == 1


# ── handlers are sync def (threadpool, never the event loop) ─────────────────


def test_all_handlers_are_sync_def():
    for name in (
        "list_automations",
        "create_automation",
        "patch_automation",
        "delete_automation",
        "run_automation",
        "list_approvals",
        "approvals_count",
        "approve_approval",
        "reject_approval",
        "list_activity",
    ):
        fn = getattr(auto_routes, name)
        assert not asyncio.iscoroutinefunction(fn), f"{name} must be a sync def"
