from src import db
from src.schema import ModuleConfig, TextInput


def _sample_config(title: str = "Workout Log") -> ModuleConfig:
    return ModuleConfig(
        title=title,
        components=[TextInput(id="exercise", label="Exercise")],
    )


def test_init_and_ensure_session_creates_new_id():
    db.init_db()
    sid = db.ensure_session(None)
    assert sid and len(sid) >= 32


def test_ensure_session_reuses_existing():
    db.init_db()
    sid = db.ensure_session(None)
    again = db.ensure_session(sid)
    assert again == sid


def test_ensure_session_replaces_unknown_id():
    db.init_db()
    new = db.ensure_session("not-a-real-session")
    assert new != "not-a-real-session"


def test_insert_and_list_modules():
    db.init_db()
    sid = db.ensure_session(None)
    a = db.insert_module(sid, _sample_config("A"))
    b = db.insert_module(sid, _sample_config("B"))
    listed = db.list_modules(sid)
    assert [m.id for m in listed] == [a.id, b.id]
    assert listed[0].config.title == "A"


def test_list_modules_scoped_to_session():
    db.init_db()
    s1 = db.ensure_session(None)
    s2 = db.ensure_session(None)
    db.insert_module(s1, _sample_config("only-s1"))
    assert db.list_modules(s2) == []


def test_update_module_overwrites_config():
    db.init_db()
    sid = db.ensure_session(None)
    stored = db.insert_module(sid, _sample_config("v1"))
    updated = db.update_module(sid, stored.id, _sample_config("v2"))
    assert updated is not None
    assert updated.config.title == "v2"
    assert updated.created_at == stored.created_at
    assert updated.updated_at >= stored.updated_at


def test_update_module_rejects_cross_session():
    db.init_db()
    s1 = db.ensure_session(None)
    s2 = db.ensure_session(None)
    stored = db.insert_module(s1, _sample_config())
    assert db.update_module(s2, stored.id, _sample_config("hacked")) is None
