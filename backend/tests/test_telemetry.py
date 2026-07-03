"""R-1201/R-1202/R-1203: activity measurable, generations accounted, ops surface gated."""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from src import db
from src.main import app


def test_generation_records_event(tmp_path, monkeypatch):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    with TestClient(app) as client:
        r = client.post("/api/modules/preview", json={"prompt": "track my reading"})
        assert r.status_code == 200
    stats = db.gen_stats(days=1)
    assert stats["total"] == 1
    assert stats["by_outcome"].get("ok") == 1
    assert db.daily_active(days=1)[0]["owners"] >= 1


def test_failed_generation_records_error_outcome(tmp_path, monkeypatch):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    from src.schema import LLMError
    from src.services import orchestrator

    def boom(*a, **k):
        raise LLMError("down")

    monkeypatch.setattr(orchestrator, "generate_modules", boom)
    with TestClient(app) as client:
        r = client.post("/api/modules/preview", json={"prompt": "x y z"})
        assert r.status_code == 503
    assert db.gen_stats(days=1)["by_outcome"].get("error") == 1


def test_ops_summary_is_token_gated(tmp_path, monkeypatch):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TRUS_OPS_TOKEN", "sekrit")
    with TestClient(app) as client:
        assert client.get("/api/ops/summary").status_code == 401
        assert client.get("/api/ops/summary?token=wrong").status_code == 401
        ok = client.get("/api/ops/summary?token=sekrit")
        assert ok.status_code == 200
        assert {"generations", "daily_active", "users"} <= set(ok.json().keys())


# ---------------------------------------------------------------------------
# R-1201: per-user last-seen — "which of the 50 used it yesterday", answerable
# straight from db.last_seen_by_user and the ops summary it feeds.
# ---------------------------------------------------------------------------


def test_last_seen_by_user_only_includes_claimed_users(tmp_path, monkeypatch):
    """gen_events JOIN users excludes anonymous sids by construction — a sid has
    no matching users row, so it never appears in this view."""
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    db.init_db()
    user = db.create_user("Ada")
    db.add_gen_event(user["id"], "generate", "ok", "stub", "stub", 10, None, None)
    db.add_gen_event("anon-sid-xyz", "generate", "ok", "stub", "stub", 10, None, None)

    rows = db.last_seen_by_user(30)

    assert len(rows) == 1
    assert rows[0]["user_id"] == user["id"]
    assert rows[0]["name"] == "Ada"
    assert rows[0]["generations_7d"] == 1
    assert rows[0]["last_seen"]


def test_last_seen_by_user_ordered_by_last_seen_desc(tmp_path, monkeypatch):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    db.init_db()
    older = db.create_user("Older")
    newer = db.create_user("Newer")
    with db._conn() as c:
        c.execute(
            "INSERT INTO gen_events (id, owner, kind, outcome, provider, model,"
            " latency_ms, tokens_in, tokens_out, created_at)"
            " VALUES ('e1', ?, 'generate', 'ok', 'stub', 'stub', 10, NULL, NULL, '2020-01-01T00:00:00+00:00')",
            (older["id"],),
        )
        c.execute(
            "INSERT INTO gen_events (id, owner, kind, outcome, provider, model,"
            " latency_ms, tokens_in, tokens_out, created_at)"
            " VALUES ('e2', ?, 'generate', 'ok', 'stub', 'stub', 10, NULL, NULL, ?)",
            (newer["id"], db._now()),
        )

    rows = db.last_seen_by_user(days=3650)  # wide window so 2020's row still qualifies

    assert [r["user_id"] for r in rows] == [newer["id"], older["id"]]


def test_ops_summary_users_shows_claimed_user_fresh_activity(tmp_path, monkeypatch):
    """Claimed-user generations show up in ops summary's users[] with a fresh
    last_seen and a generations_7d count; anonymous-session generations don't
    show up at all (no user to attribute them to)."""
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TRUS_OPS_TOKEN", "sekrit")
    user = db.create_user("Ada")
    with TestClient(app) as claimed_client, TestClient(app) as anon_client:
        claim = claimed_client.post("/api/auth/claim", json={"token": user["invite_token"]})
        assert claim.status_code == 200
        assert (
            claimed_client.post(
                "/api/modules/preview", json={"prompt": "track my reading"}
            ).status_code
            == 200
        )
        assert (
            anon_client.post(
                "/api/modules/preview", json={"prompt": "track my reading"}
            ).status_code
            == 200
        )

        summary = claimed_client.get("/api/ops/summary?token=sekrit")
        assert summary.status_code == 200
        users = summary.json()["users"]

    assert len(users) == 1  # the anonymous generation isn't attributed to anyone
    entry = users[0]
    assert entry["name"] == "Ada"
    assert entry["user_id"] == user["id"]
    assert entry["generations_7d"] >= 1
    seen = datetime.fromisoformat(entry["last_seen"])
    assert datetime.now(timezone.utc) - seen < timedelta(minutes=5)  # fresh
