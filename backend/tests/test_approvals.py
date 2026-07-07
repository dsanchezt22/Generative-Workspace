"""Approvals lifecycle: park → approve the FROZEN payload, CAS races, expiry,
the uses_llm budget gate, dedupe, and corrupt-payload quarantine.

Exercised through the HTTP surface (the approve/reject handlers execute in-request
on the frozen park-time bytes). All time injected where it matters; no sleeps.
"""

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from src import db
from src.main import app
from src.services import actions


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _insert_module(client, components, state=None, title="M"):
    cfg = {"title": title, "components": components, "state": state or {}}
    r = client.post("/api/modules", json={"configs": [cfg]})
    assert r.status_code == 201, r.text
    return r.json()[0]


def _create(client, action, trust_dial=1, name="A"):
    r = client.post(
        "/api/automations",
        json={
            "name": name,
            "action": action,
            "schedule_kind": "interval",
            "interval_secs": 3600,
            "trust_dial": trust_dial,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _run(client, aid):
    r = client.post(f"/api/automations/{aid}/run")
    assert r.status_code == 200, r.text
    return r.json()


def _spy_spec(monkeypatch, action_type, fn):
    orig = actions.ACTION_SPECS[action_type]
    spec = actions.ActionSpec(orig.floor, orig.irreversible, orig.uses_llm, orig.stub, fn)
    monkeypatch.setitem(actions.ACTION_SPECS, action_type, spec)


# ── park → approve executes the FROZEN payload ───────────────────────────────


def test_approve_executes_frozen_payload_bytes(client, monkeypatch):
    m = _insert_module(
        client, [{"id": "body", "type": "note", "label": "B"}], {"body": "VERSION 1"}
    )
    action = {
        "type": "send_email",
        "to": "a@b.co",
        "subject": "S",
        "module_id": m["id"],
        "component_id": "body",
    }
    auto = _create(client, action)
    approval = _run(client, auto["id"])["approval"]  # irreversible → parks
    assert approval is not None and approval["status"] == "pending"

    # Mutate the source note AFTER park — the approval must still send V1.
    m["config"]["state"]["body"] = "VERSION 2"
    pr = client.patch(f"/api/modules/{m['id']}", json={"config": m["config"], "rev": m["rev"]})
    assert pr.status_code == 200, pr.text

    captured: dict = {}

    def spy(owner, payload, ctx):
        captured["payload"] = payload
        return actions.ExecResult({"simulated": True, "to": payload.get("to")})

    _spy_spec(monkeypatch, "send_email", spy)
    ar = client.post(f"/api/approvals/{approval['id']}/approve")
    assert ar.status_code == 200, ar.text
    assert captured["payload"]["body"] == "VERSION 1"  # frozen, not the mutated V2
    body = ar.json()
    assert body["approval"]["status"] == "approved"
    assert body["approval"]["executed_at"] is not None
    assert body["activity"]["kind"] == "approved"
    assert body["activity"]["simulated"] is True


def test_double_approve_409_executes_once(client, monkeypatch):
    auto = _create(client, {"type": "send_email", "to": "a@b.co", "subject": "S"})
    approval = _run(client, auto["id"])["approval"]
    calls = {"n": 0}

    def spy(owner, payload, ctx):
        calls["n"] += 1
        return actions.ExecResult({"simulated": True, "to": payload.get("to")})

    _spy_spec(monkeypatch, "send_email", spy)
    first = client.post(f"/api/approvals/{approval['id']}/approve")
    second = client.post(f"/api/approvals/{approval['id']}/approve")
    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"]["state"] == "approved"
    assert calls["n"] == 1  # executor called at most once, ever


def test_reject_never_executes(client, monkeypatch):
    auto = _create(client, {"type": "send_email", "to": "a@b.co", "subject": "S"})
    approval = _run(client, auto["id"])["approval"]

    def boom(owner, payload, ctx):
        raise AssertionError("executor must never run on reject")

    _spy_spec(monkeypatch, "send_email", boom)
    rr = client.post(f"/api/approvals/{approval['id']}/reject")
    assert rr.status_code == 200
    assert rr.json()["approval"]["status"] == "rejected"
    assert rr.json()["activity"]["kind"] == "rejected"
    # a later approve of a rejected row → 409, still never executes
    ar = client.post(f"/api/approvals/{approval['id']}/approve")
    assert ar.status_code == 409
    assert ar.json()["detail"]["state"] == "rejected"


def test_approval_404_when_missing(client):
    ar = client.post("/api/approvals/nope/approve")
    assert ar.status_code == 404


# ── expiry ───────────────────────────────────────────────────────────────────


def _age_out(approval_id):
    with db._conn() as c:
        c.execute(
            "UPDATE approvals SET expires_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00+00:00", approval_id),
        )


def test_expiry_sweep_marks_and_journals(client):
    auto = _create(client, {"type": "send_email", "to": "a@b.co", "subject": "S"})
    approval = _run(client, auto["id"])["approval"]
    _age_out(approval["id"])
    listed = client.get("/api/approvals")  # GET sweeps expiry first
    assert listed.json()["pending_count"] == 0
    kinds = [e["kind"] for e in client.get("/api/activity").json()["entries"]]
    assert "expired" in kinds


def test_approve_past_expiry_409(client):
    auto = _create(client, {"type": "send_email", "to": "a@b.co", "subject": "S"})
    approval = _run(client, auto["id"])["approval"]
    _age_out(approval["id"])
    ar = client.post(f"/api/approvals/{approval['id']}/approve")
    assert ar.status_code == 409
    assert ar.json()["detail"]["state"] == "expired"


def test_cas_expires_guard_without_sweep():
    # The CAS `AND expires_at > ?` closes the race even if no sweep ran.
    owner = "o"
    auto = db.automation_create(
        owner,
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
    ap = db.approval_create(
        owner, auto["id"], "send_email", "{}", "sum", None, "2000-01-01T00:00:00+00:00"
    )
    # not yet swept (still 'pending' in the row), but expired: claim must fail
    assert db.approval_claim(owner, ap["id"], "approved", "2026-07-06T00:00:00+00:00") is None


# ── uses_llm budget gate on approve (dial-0 hold of an LLM action) ───────────


def test_llm_approve_over_budget_fails_without_spend(client, monkeypatch):
    m = _insert_module(client, [{"id": "note", "type": "note", "label": "N"}], {"note": ""})
    auto = _create(
        client,
        {
            "type": "summarize",
            "module_id": m["id"],
            "component_id": "note",
            "source_module_ids": [m["id"]],
        },
        trust_dial=0,  # dial 0 holds everything, incl. an autonomous LLM action
    )
    approval = _run(client, auto["id"])["approval"]
    assert approval is not None

    monkeypatch.setenv("TRUS_GEN_RATE_MAX", "0")  # exhaust the shared gen budget
    llm_spy = Mock()
    monkeypatch.setattr("src.services.actions.llm.generate", llm_spy)
    ar = client.post(f"/api/approvals/{approval['id']}/approve")
    assert ar.status_code == 200
    assert ar.json()["approval"]["status"] == "failed"
    assert ar.json()["activity"]["kind"] == "failed"
    llm_spy.assert_not_called()  # zero spend


# ── dedupe + corrupt payload ─────────────────────────────────────────────────


def test_park_dedupes_to_one_pending(client):
    auto = _create(client, {"type": "send_email", "to": "a@b.co", "subject": "S"})
    _run(client, auto["id"])
    _run(client, auto["id"])
    assert client.get("/api/approvals").json()["pending_count"] == 1


def test_corrupt_frozen_payload_fails_cleanly(client):
    auto = _create(client, {"type": "send_email", "to": "a@b.co", "subject": "S"})
    approval = _run(client, auto["id"])["approval"]
    with db._conn() as c:
        c.execute("UPDATE approvals SET payload_json = '{bad' WHERE id = ?", (approval["id"],))
    ar = client.post(f"/api/approvals/{approval['id']}/approve")
    assert ar.status_code == 500  # honest, not a crash-loop
    assert client.get("/api/approvals").json()["pending_count"] == 0
    kinds = [e["kind"] for e in client.get("/api/activity").json()["entries"]]
    assert "failed" in kinds
