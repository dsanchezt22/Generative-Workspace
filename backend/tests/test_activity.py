"""The activity journal: taxonomy (incl. 'skipped'), keyset pagination, per-owner
prune at TRUS_ACTIVITY_MAX, and sanitized failure summaries.
"""

import itertools
from datetime import datetime, timezone

from src import db
from src.schema import LLMError
from src.services import actions, runtime

NOW = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)

_KINDS = ("ran", "held", "approved", "rejected", "expired", "failed", "skipped")


def _ensure_owner(owner):
    with db._conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO sessions (id, created_at) VALUES (?, ?)", (owner, db._now())
        )
    return owner


def test_taxonomy_all_seven_kinds_persist():
    owner = "o"
    for kind in _KINDS:
        db.activity_add(owner, kind, f"{kind} line")
    got = {e["kind"] for e in db.activity_list(owner, limit=50)}
    assert got == set(_KINDS)


def test_keyset_pagination(monkeypatch):
    owner = "o"
    counter = itertools.count()
    monkeypatch.setattr(db, "_now", lambda: f"2026-07-06T00:00:{next(counter):02d}+00:00")
    for i in range(6):
        db.activity_add(owner, "ran", f"row {i}")
    page1 = db.activity_list(owner, limit=3)
    assert [r["summary"] for r in page1] == ["row 5", "row 4", "row 3"]
    cursor = page1[-1]["created_at"]
    page2 = db.activity_list(owner, limit=3, before=cursor)
    assert [r["summary"] for r in page2] == ["row 2", "row 1", "row 0"]


def test_per_owner_prune(monkeypatch):
    monkeypatch.setenv("TRUS_ACTIVITY_MAX", "3")
    for i in range(5):
        db.activity_add("A", "ran", f"a{i}")
    for i in range(2):
        db.activity_add("B", "ran", f"b{i}")
    a_rows = db.activity_list("A", limit=50)
    assert [r["summary"] for r in a_rows] == ["a4", "a3", "a2"]  # newest 3 kept
    assert len(db.activity_list("B", limit=50)) == 2  # owner B untouched


def test_failure_summary_is_sanitized(monkeypatch):
    owner = _ensure_owner("o")
    auto = db.automation_create(
        owner,
        page_id=None,
        name="Digest",
        description="",
        action_type="summarize",
        action_json='{"type":"summarize","module_id":"m","component_id":"c"}',
        schedule_kind="interval",
        interval_secs=3600,
        daily_at=None,
        trust_dial=1,
        next_run_at="2020-01-01T00:00:00+00:00",
    )

    def boom(owner, payload, ctx):
        raise LLMError("Could not reach the LLM endpoint at http://internal-secret:11434: refused")

    monkeypatch.setitem(
        actions.ACTION_SPECS,
        "summarize",
        actions.ActionSpec("autonomous", False, True, False, boom),
    )
    runtime._runtime_limiter._hits.clear()
    row = db.automation_get(owner, auto["id"])
    runtime.run_once(owner, row, NOW, next_run_at=row["next_run_at"])
    failed = next(e for e in db.activity_list(owner, limit=5) if e["kind"] == "failed")
    assert "http" not in failed["summary"]
    assert "internal-secret" not in failed["summary"]
    assert "11434" not in failed["summary"]
