"""R-602 AC (two tabs): a stale writer gets 409 + the current module, never a silent wipe."""

from src import db
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
    import pytest

    c3 = m.config.model_copy(update={"title": "Tab B stale change"})
    with pytest.raises(db.RevConflict) as exc:
        db.update_module(sid, m.id, c3, expected_rev=0)  # tab B still thinks rev 0
    assert exc.value.current.config.title == "Tab A change"
