"""Thin SQLite layer. Stdlib only — no SQLAlchemy until we outgrow this."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from src.schema import ModuleConfig, ModuleVersion, Page, StoredModule

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "trus.db"


def _db_path() -> Path:
    override = os.environ.get("TRUS_DB_PATH")
    return Path(override) if override else DEFAULT_DB_PATH


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pages (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    position    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pages_session
    ON pages(session_id, position);
CREATE TABLE IF NOT EXISTS modules (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    page_id     TEXT REFERENCES pages(id) ON DELETE CASCADE,
    config_json TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_modules_session
    ON modules(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_modules_page
    ON modules(page_id, created_at);
CREATE TABLE IF NOT EXISTS module_versions (
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,
    module_id   TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    config_json TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_versions_module
    ON module_versions(module_id, seq);
"""

# Tracks which db file has had its schema ensured this process, so we re-run the
# (idempotent) DDL when the path changes — or when the file vanishes underneath
# a running server. Reliability over cleverness (design doc I.3).
_schema_ready_for: str | None = None


def _ensure_schema(conn: sqlite3.Connection) -> None:
    global _schema_ready_for
    path = str(_db_path())
    needs = _schema_ready_for != path
    if not needs:
        # Cheap guard against the file having been deleted mid-run.
        try:
            conn.execute("SELECT 1 FROM sessions LIMIT 1")
        except sqlite3.OperationalError:
            needs = True
    if needs:
        conn.executescript(_SCHEMA)
        conn.commit()
        _schema_ready_for = path


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _ensure_schema(conn)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _conn():
        pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record_version(c: sqlite3.Connection, module_id: str, session_id: str, config_json: str, when: str) -> None:
    """Append a history snapshot, skipping no-op duplicates of the latest one."""
    latest = c.execute(
        "SELECT config_json FROM module_versions WHERE module_id = ? ORDER BY seq DESC LIMIT 1",
        (module_id,),
    ).fetchone()
    if latest and latest["config_json"] == config_json:
        return
    c.execute(
        "INSERT INTO module_versions (module_id, session_id, config_json, created_at) VALUES (?, ?, ?, ?)",
        (module_id, session_id, config_json, when),
    )


def ensure_session(session_id: str | None) -> str:
    if session_id:
        with _conn() as c:
            row = c.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if row:
                return session_id
    new_id = str(uuid.uuid4())
    with _conn() as c:
        c.execute("INSERT INTO sessions (id, created_at) VALUES (?, ?)", (new_id, _now()))
    return new_id


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

def ensure_default_page(session_id: str) -> Page:
    """Return the first page for a session, creating it if none exist."""
    with _conn() as c:
        row = c.execute(
            "SELECT id, name, position, created_at FROM pages WHERE session_id = ? ORDER BY position LIMIT 1",
            (session_id,),
        ).fetchone()
        if row:
            return Page(id=row["id"], name=row["name"], position=row["position"],
                        session_id=session_id, created_at=row["created_at"])
        page_id = str(uuid.uuid4())
        now = _now()
        c.execute(
            "INSERT INTO pages (id, session_id, name, position, created_at) VALUES (?, ?, ?, ?, ?)",
            (page_id, session_id, "Main", 0, now),
        )
    return Page(id=page_id, name="Main", position=0, session_id=session_id, created_at=now)


def list_pages(session_id: str) -> list[Page]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, name, position, created_at FROM pages WHERE session_id = ? ORDER BY position",
            (session_id,),
        ).fetchall()
    return [Page(id=r["id"], name=r["name"], position=r["position"],
                 session_id=session_id, created_at=r["created_at"]) for r in rows]


def create_page(session_id: str, name: str) -> Page:
    with _conn() as c:
        max_pos = c.execute(
            "SELECT COALESCE(MAX(position), -1) FROM pages WHERE session_id = ?",
            (session_id,),
        ).fetchone()[0]
        page_id = str(uuid.uuid4())
        now = _now()
        position = max_pos + 1
        c.execute(
            "INSERT INTO pages (id, session_id, name, position, created_at) VALUES (?, ?, ?, ?, ?)",
            (page_id, session_id, name, position, now),
        )
    return Page(id=page_id, name=name, position=position, session_id=session_id, created_at=now)


def rename_page(session_id: str, page_id: str, name: str) -> Page | None:
    with _conn() as c:
        cur = c.execute(
            "UPDATE pages SET name = ? WHERE id = ? AND session_id = ?",
            (name, page_id, session_id),
        )
        if cur.rowcount == 0:
            return None
        row = c.execute(
            "SELECT id, name, position, created_at FROM pages WHERE id = ?", (page_id,)
        ).fetchone()
    return Page(id=row["id"], name=row["name"], position=row["position"],
                session_id=session_id, created_at=row["created_at"])


def delete_page(session_id: str, page_id: str) -> bool:
    """Delete a page and all its modules. Refuses to delete the last page."""
    with _conn() as c:
        count = c.execute(
            "SELECT COUNT(*) FROM pages WHERE session_id = ?", (session_id,)
        ).fetchone()[0]
        if count <= 1:
            return False
        cur = c.execute(
            "DELETE FROM pages WHERE id = ? AND session_id = ?", (page_id, session_id)
        )
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Modules
# ---------------------------------------------------------------------------

def insert_module(session_id: str, config: ModuleConfig, page_id: str | None = None) -> StoredModule:
    module_id = str(uuid.uuid4())
    now = _now()
    config_json = config.model_dump_json()
    # Resolve page_id: use provided, or fall back to the session's default page.
    if page_id is None:
        page_id = ensure_default_page(session_id).id
    with _conn() as c:
        c.execute(
            "INSERT INTO modules (id, session_id, page_id, config_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (module_id, session_id, page_id, config_json, now, now),
        )
        _record_version(c, module_id, session_id, config_json, now)
    return StoredModule(id=module_id, config=config, created_at=now, updated_at=now, page_id=page_id)


def get_module(session_id: str, module_id: str) -> StoredModule | None:
    with _conn() as c:
        row = c.execute(
            "SELECT id, page_id, config_json, created_at, updated_at FROM modules WHERE id = ? AND session_id = ?",
            (module_id, session_id),
        ).fetchone()
    if row is None:
        return None
    return StoredModule(
        id=row["id"],
        config=ModuleConfig.model_validate_json(row["config_json"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        page_id=row["page_id"],
    )


def list_modules(session_id: str, page_id: str | None = None) -> list[StoredModule]:
    with _conn() as c:
        if page_id:
            rows = c.execute(
                "SELECT id, page_id, config_json, created_at, updated_at FROM modules WHERE session_id = ? AND page_id = ? ORDER BY created_at",
                (session_id, page_id),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT id, page_id, config_json, created_at, updated_at FROM modules WHERE session_id = ? ORDER BY created_at",
                (session_id,),
            ).fetchall()
    return [
        StoredModule(
            id=r["id"],
            config=ModuleConfig.model_validate_json(r["config_json"]),
            created_at=r["created_at"],
            updated_at=r["updated_at"],
            page_id=r["page_id"],
        )
        for r in rows
    ]


def update_module(session_id: str, module_id: str, config: ModuleConfig) -> StoredModule | None:
    now = _now()
    config_json = config.model_dump_json()
    with _conn() as c:
        cur = c.execute(
            "UPDATE modules SET config_json = ?, updated_at = ? WHERE id = ? AND session_id = ?",
            (config_json, now, module_id, session_id),
        )
        if cur.rowcount == 0:
            return None
        _record_version(c, module_id, session_id, config_json, now)
        row = c.execute(
            "SELECT page_id, created_at FROM modules WHERE id = ?", (module_id,)
        ).fetchone()
    return StoredModule(id=module_id, config=config, created_at=row["created_at"], updated_at=now,
                        page_id=row["page_id"])


def delete_module(session_id: str, module_id: str) -> bool:
    with _conn() as c:
        cur = c.execute(
            "DELETE FROM modules WHERE id = ? AND session_id = ?",
            (module_id, session_id),
        )
        if cur.rowcount == 0:
            return False
        c.execute("DELETE FROM module_versions WHERE module_id = ?", (module_id,))
        return True


def list_versions(session_id: str, module_id: str) -> list[ModuleVersion]:
    with _conn() as c:
        rows = c.execute(
            "SELECT config_json, created_at FROM module_versions WHERE module_id = ? AND session_id = ? ORDER BY seq",
            (module_id, session_id),
        ).fetchall()
    return [
        ModuleVersion(
            config=ModuleConfig.model_validate_json(r["config_json"]),
            created_at=r["created_at"],
        )
        for r in rows
    ]


def undo_module(session_id: str, module_id: str) -> StoredModule | None:
    """Revert a module to its previous version. Returns None when there is
    nothing to undo (unknown module, wrong session, or only one version)."""
    now = _now()
    with _conn() as c:
        rows = c.execute(
            "SELECT seq, config_json FROM module_versions WHERE module_id = ? AND session_id = ? ORDER BY seq DESC LIMIT 2",
            (module_id, session_id),
        ).fetchall()
        if len(rows) < 2:
            return None
        current, previous = rows[0], rows[1]
        c.execute("DELETE FROM module_versions WHERE seq = ?", (current["seq"],))
        c.execute(
            "UPDATE modules SET config_json = ?, updated_at = ? WHERE id = ? AND session_id = ?",
            (previous["config_json"], now, module_id, session_id),
        )
        row = c.execute(
            "SELECT created_at, page_id FROM modules WHERE id = ?", (module_id,)
        ).fetchone()
    return StoredModule(
        id=module_id,
        config=ModuleConfig.model_validate_json(previous["config_json"]),
        created_at=row["created_at"],
        updated_at=now,
        page_id=row["page_id"],
    )
