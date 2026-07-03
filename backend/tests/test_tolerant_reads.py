"""R-1105 AC: a corrupted row degrades only itself, never the workspace load."""

import json
import sqlite3

from src import db
from src.schema import ModuleConfig
from src.stub_templates import pick_template

_BAD_CONFIG_JSON = '{"not": "a module config"}'


def _corrupt_row(db_path: str, session_id: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO modules (id, session_id, page_id, config_json, created_at, updated_at)"
        " VALUES ('bad-row', ?, NULL, '{\"not\": \"a module config\"}', '2026-01-01', '2026-01-01')",
        (session_id,),
    )
    conn.commit()
    conn.close()


def test_list_modules_survives_corrupt_row(tmp_path, monkeypatch):
    db_path = str(tmp_path / "t.db")
    monkeypatch.setenv("TRUS_DB_PATH", db_path)
    db.init_db()
    sid = db.ensure_session(None)

    good = db.insert_module(sid, ModuleConfig.model_validate(pick_template("track water")))
    _corrupt_row(db_path, sid)
    listed = db.list_modules(sid)
    assert [m.id for m in listed] == [good.id]  # workspace loads; bad row quarantined
    assert db.get_module(sid, "bad-row") is None  # unreadable → treated as absent


def test_undo_skips_corrupt_version_and_falls_through(tmp_path, monkeypatch):
    """A corrupted middle version is quarantined; undo walks back to the next
    older readable version instead of raising."""
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    db.init_db()
    sid = db.ensure_session(None)
    m = db.insert_module(sid, ModuleConfig.model_validate(pick_template("track water")))
    original_title = m.config.title

    v2 = m.config.model_copy(deep=True)
    v2.title = "v2"
    db.update_module(sid, m.id, v2)
    v3 = m.config.model_copy(deep=True)
    v3.title = "v3"
    db.update_module(sid, m.id, v3)

    with db._conn() as c:
        seqs = [
            r["seq"]
            for r in c.execute(
                "SELECT seq FROM module_versions WHERE module_id = ? ORDER BY seq", (m.id,)
            ).fetchall()
        ]
        # Corrupt the middle version (v2) directly.
        c.execute(
            "UPDATE module_versions SET config_json = ? WHERE seq = ?",
            (_BAD_CONFIG_JSON, seqs[1]),
        )

    reverted = db.undo_module(sid, m.id)
    assert reverted is not None
    assert reverted.config.title == original_title  # fell through past corrupt v2 to v1


def test_restore_snapshot_aborts_before_deletion_on_bad_row(tmp_path, monkeypatch):
    """A snapshot containing an unparseable module config aborts the restore
    (returns "corrupt") WITHOUT deleting any of the page's live modules."""
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    db.init_db()
    sid = db.ensure_session(None)
    page = db.ensure_default_page(sid)
    kept = db.insert_module(
        sid, ModuleConfig.model_validate(pick_template("track water")), page_id=page.id
    )

    with db._conn() as c:
        c.execute(
            "INSERT INTO snapshots (id, session_id, page_id, label, data_json, created_at) "
            "VALUES ('bad-snap', ?, ?, 'corrupt', ?, '2026-01-01')",
            (sid, page.id, json.dumps([{"not": "a module config"}])),
        )

    ok = db.restore_snapshot(sid, "bad-snap")
    assert ok == "corrupt"
    assert [m.id for m in db.list_modules(sid, page.id)] == [kept.id]  # nothing deleted
