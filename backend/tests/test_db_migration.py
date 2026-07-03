"""F8: PRAGMA order + a race-safe schema migration.

Concurrent first requests against a STALE database (old schema, missing migrated
columns) must not both run ALTER TABLE — the losers used to 500 with
'duplicate column name'. A double-checked module-level lock serializes the
migration body so it runs exactly once.
"""

import sqlite3
import threading
import time

from src import db

# A deliberately-stale schema: the tables exist but LACK the columns _migrate adds
# (modules.page_id/archived, pages.icon/parent_id, layout_library.capture_meta_json…).
_STALE = """
CREATE TABLE sessions (id TEXT PRIMARY KEY, created_at TEXT NOT NULL);
CREATE TABLE pages (
    id TEXT PRIMARY KEY, session_id TEXT NOT NULL, name TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
);
CREATE TABLE modules (
    id TEXT PRIMARY KEY, session_id TEXT NOT NULL, config_json TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE layout_library (
    id TEXT PRIMARY KEY, use_case TEXT NOT NULL, label TEXT NOT NULL,
    inspired_by TEXT, config_json TEXT NOT NULL, created_at TEXT NOT NULL
);
"""


def test_conn_sets_busy_timeout_and_wal(monkeypatch, tmp_path):
    """F8(a): busy_timeout is applied and journal_mode ends up WAL (order safe)."""
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "fresh.db"))
    monkeypatch.setattr(db, "_schema_ready_for", None)
    with db._conn() as c:
        assert c.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        assert str(c.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "wal"


def test_concurrent_migration_on_stale_db_does_not_double_alter(monkeypatch, tmp_path):
    """F8(b): several threads hitting a stale DB at once must not each run ALTER
    TABLE. A widened migration window (sleep) makes the race deterministic."""
    dbfile = tmp_path / "stale.db"
    conn = sqlite3.connect(dbfile)
    conn.executescript(_STALE)
    conn.commit()
    conn.close()

    monkeypatch.setenv("TRUS_DB_PATH", str(dbfile))
    monkeypatch.setattr(db, "_schema_ready_for", None)

    real_migrate = db._migrate

    def slow_migrate(c):
        time.sleep(0.05)  # widen the race window so an unguarded migration collides
        return real_migrate(c)

    monkeypatch.setattr(db, "_migrate", slow_migrate)

    n = 6
    barrier = threading.Barrier(n)
    errors: list[Exception] = []

    def worker():
        try:
            barrier.wait()
            with db._conn() as c:
                c.execute("SELECT 1 FROM sessions LIMIT 1").fetchall()
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"migration race raised: {errors!r}"
    # The migration actually applied: the new column now exists.
    with db._conn() as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(modules)").fetchall()}
    assert "page_id" in cols and "archived" in cols
