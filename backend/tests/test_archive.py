from src import db
from src.schema import ModuleConfig, TextInput


def _cfg(title="T"):
    return ModuleConfig(title=title, components=[TextInput(id="a", label="A")])


def test_archive_hides_from_list_and_restore_brings_back():
    db.init_db()
    sid = db.ensure_session(None)
    m = db.insert_module(sid, _cfg("keep"))
    assert len(db.list_modules(sid)) == 1
    db.set_archived(sid, m.id, True)
    assert db.list_modules(sid) == []
    assert [a.id for a in db.list_archived(sid)] == [m.id]
    db.set_archived(sid, m.id, False)
    assert len(db.list_modules(sid)) == 1
    assert db.list_archived(sid) == []


def test_duplicate_copies_config_with_offset():
    db.init_db()
    sid = db.ensure_session(None)
    m = db.insert_module(sid, _cfg("Original"))
    dup = db.duplicate_module(sid, m.id)
    assert dup is not None and dup.id != m.id
    assert dup.config.title == "Original copy"
    assert dup.config.layout.x == m.config.layout.x + 32
    assert len(db.list_modules(sid)) == 2
