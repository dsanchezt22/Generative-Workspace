"""R-602 AC (two tabs): a stale writer gets 409 + the current module, never a silent wipe."""

import pytest
from fastapi.testclient import TestClient
from src import db
from src.main import app
from src.schema import ModuleConfig
from src.stub_templates import pick_template


def test_stale_rev_raises_conflict(tmp_path, monkeypatch):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    db.init_db()
    sid = db.ensure_session(None)
    m = db.insert_module(sid, ModuleConfig.model_validate(pick_template("track water")))
    assert m.rev == 0
    c2 = m.config.model_copy(update={"title": "Tab A change"})
    updated = db.update_module(sid, m.id, c2, expected_rev=0)
    assert updated.rev == 1

    c3 = m.config.model_copy(update={"title": "Tab B stale change"})
    with pytest.raises(db.RevConflict) as exc:
        db.update_module(sid, m.id, c3, expected_rev=0)  # tab B still thinks rev 0
    assert exc.value.current.config.title == "Tab A change"


def test_undo_bumps_rev_and_returns_true_row(tmp_path, monkeypatch):
    """Single-tab regression: edit -> undo -> edit must not 409. undo's write
    bumps rev like any other write, and the returned StoredModule reflects the
    TRUE post-write row (not a hand-constructed one with the Pydantic rev
    default), so the client's cached rev stays valid for the next edit."""
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    db.init_db()
    sid = db.ensure_session(None)
    m = db.insert_module(sid, ModuleConfig.model_validate(pick_template("track water")))
    c2 = m.config.model_copy(update={"title": "edited"})
    db.update_module(sid, m.id, c2, expected_rev=0)  # rev 0 -> 1

    undone = db.undo_module(sid, m.id)
    assert undone is not None
    stored = db.get_module(sid, m.id)
    assert undone.rev == stored.rev  # returned state matches the row, no stale default
    assert undone.rev == 2  # undo's own write bumped rev (1 -> 2)

    c3 = undone.config.model_copy(update={"title": "edited after undo"})
    updated = db.update_module(sid, m.id, c3, expected_rev=undone.rev)
    assert updated is not None  # no spurious RevConflict
    assert updated.rev == undone.rev + 1


def test_patch_after_undo_with_returned_rev_succeeds():
    """Route-level: PATCH -> undo -> PATCH with the rev from the undo response
    is an ordinary single-tab flow and must return 200, never a 409."""
    with TestClient(app) as client:
        m = client.post("/api/onboarding/seed").json()[0]
        cfg = m["config"]
        cfg["title"] = "edited"
        r1 = client.patch(f"/api/modules/{m['id']}", json={"config": cfg, "rev": m["rev"]})
        assert r1.status_code == 200, r1.text

        undone = client.post(f"/api/modules/{m['id']}/undo")
        assert undone.status_code == 200, undone.text
        u = undone.json()

        cfg2 = u["config"]
        cfg2["title"] = "edited again after undo"
        r2 = client.patch(f"/api/modules/{m['id']}", json={"config": cfg2, "rev": u["rev"]})
        assert r2.status_code == 200, r2.text  # regression: stale cached rev used to 409 here
