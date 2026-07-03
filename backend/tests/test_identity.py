"""R-901-905: gated access, cross-device continuity, per-owner isolation."""

import sys

from fastapi.testclient import TestClient
from src import db
from src.main import app


def _client(tmp_path, monkeypatch, allow_anon="0"):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TRUS_ALLOW_ANON", allow_anon)
    return TestClient(app)


# ---------------------------------------------------------------------------
# R-901: gated access — no reads, writes, or model spend without a claim.
# ---------------------------------------------------------------------------


def test_unclaimed_session_is_401_when_anon_disabled(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        assert client.get("/api/modules").status_code == 401
        assert client.post("/api/modules/preview", json={"prompt": "x"}).status_code == 401


def test_all_data_routers_gate_unclaimed_when_anon_disabled(tmp_path, monkeypatch):
    """Spot-check every data router refuses an unclaimed request (R-901)."""
    with _client(tmp_path, monkeypatch) as client:
        assert client.get("/api/pages").status_code == 401
        assert client.get("/api/conversations").status_code == 401
        assert client.get("/api/studio/use-cases").status_code == 401
        assert client.get("/api/studio/layouts").status_code == 401


# ---------------------------------------------------------------------------
# R-902: claim grants access; a second device on the same link shares the workspace.
# ---------------------------------------------------------------------------


def test_claim_grants_access_and_two_devices_share_a_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TRUS_ALLOW_ANON", "0")
    user = db.create_user("Janus")
    with TestClient(app) as device_a, TestClient(app) as device_b:
        assert device_a.get(f"/api/auth/claim?token={user['invite_token']}").status_code == 200
        created = device_a.post(
            "/api/modules",
            json={
                "configs": [
                    {
                        "title": "Shared",
                        "icon": "activity",
                        "components": [{"id": "n", "type": "number_input", "label": "N"}],
                    }
                ]
            },
        )
        assert created.status_code == 201
        assert device_b.get(f"/api/auth/claim?token={user['invite_token']}").status_code == 200
        titles = [m["config"]["title"] for m in device_b.get("/api/modules").json()]
        assert "Shared" in titles  # R-902 AC: same workspace from a second device


def test_adopt_on_claim_migrates_anonymous_work(tmp_path, monkeypatch):
    """A device that built work anonymously keeps it after claiming (R-902 adopt)."""
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TRUS_ALLOW_ANON", "1")  # start in anonymous dev mode
    user = db.create_user("Mover")
    with TestClient(app) as client:
        created = client.post(
            "/api/modules",
            json={
                "configs": [
                    {
                        "title": "Pre-claim",
                        "icon": "activity",
                        "components": [{"id": "n", "type": "number_input", "label": "N"}],
                    }
                ]
            },
        )
        assert created.status_code == 201
        assert client.get(f"/api/auth/claim?token={user['invite_token']}").status_code == 200
        titles = [m["config"]["title"] for m in client.get("/api/modules").json()]
        assert "Pre-claim" in titles  # anonymous pre-claim work followed the user


def test_adopt_is_a_noop_for_the_same_owner(tmp_path, monkeypatch):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    db.init_db()
    db.adopt_session_data("same-owner", "same-owner")  # must not raise


# ---------------------------------------------------------------------------
# R-905: revocation — a revoked invite can't claim; a revoked user is bounced.
# ---------------------------------------------------------------------------


def test_revoked_invite_cannot_claim(tmp_path, monkeypatch):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    user = db.create_user("Gone")
    db.revoke_user(user["id"])
    with TestClient(app) as client:
        assert client.get(f"/api/auth/claim?token={user['invite_token']}").status_code == 403


def test_revoked_user_session_is_401_on_next_request(tmp_path, monkeypatch):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TRUS_ALLOW_ANON", "0")
    user = db.create_user("Temp")
    with TestClient(app) as client:
        assert client.get(f"/api/auth/claim?token={user['invite_token']}").status_code == 200
        assert client.get("/api/modules").status_code == 200
        db.revoke_user(user["id"])
        assert client.get("/api/modules").status_code == 401  # re-checked → back to gate


def test_unknown_token_claim_is_404(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        assert client.get("/api/auth/claim?token=does-not-exist").status_code == 404


# ---------------------------------------------------------------------------
# /api/auth/me — claim state for the frontend.
# ---------------------------------------------------------------------------


def test_me_reports_claim_state(tmp_path, monkeypatch):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TRUS_ALLOW_ANON", "0")
    user = db.create_user("Named")
    with TestClient(app) as client:
        assert client.get("/api/auth/me").json() == {"claimed": False, "name": None}
        client.get(f"/api/auth/claim?token={user['invite_token']}")
        assert client.get("/api/auth/me").json() == {"claimed": True, "name": "Named"}


def test_me_treats_anonymous_dev_mode_as_claimed(tmp_path, monkeypatch):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TRUS_ALLOW_ANON", "1")
    with TestClient(app) as client:
        assert client.get("/api/auth/me").json()["claimed"] is True


# ---------------------------------------------------------------------------
# R-903/R-1004: per-owner isolation of the shared generation cache.
# ---------------------------------------------------------------------------


def test_semantic_cache_is_owner_scoped(tmp_path, monkeypatch):
    """R-903 AC: user B's similar prompt never receives user A's cached content."""
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TRUS_CACHE", "on")
    from src import semantic_cache

    db.init_db()
    semantic_cache.store(
        "system", "track my secret project", [{"title": "A's tool"}], owner="user-a"
    )
    mode, _cached = semantic_cache.lookup("system", "track my secret project", owner="user-b")
    assert mode != "hit"  # exact same prompt, different owner → no leak
    mode_a, cached_a = semantic_cache.lookup("system", "track my secret project", owner="user-a")
    assert mode_a == "hit" and cached_a == [{"title": "A's tool"}]


# ---------------------------------------------------------------------------
# R-904: the invite provisioning CLI.
# ---------------------------------------------------------------------------


def test_invites_cli_create_list_revoke(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TRUS_PUBLIC_URL", "http://invite.example")
    from src import invites

    monkeypatch.setattr(sys, "argv", ["invites", "create", "Alice"])
    invites.main()
    assert "http://invite.example/claim?token=" in capsys.readouterr().out

    monkeypatch.setattr(sys, "argv", ["invites", "list"])
    invites.main()
    listed = capsys.readouterr().out
    assert "Alice" in listed and "active" in listed

    uid = db.list_users()[0]["id"]
    monkeypatch.setattr(sys, "argv", ["invites", "revoke", uid])
    invites.main()
    assert "revoked" in capsys.readouterr().out

    monkeypatch.setattr(sys, "argv", ["invites", "revoke", "missing-id"])
    invites.main()
    assert "not found" in capsys.readouterr().out
