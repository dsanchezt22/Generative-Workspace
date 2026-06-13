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

from src.schema import ModuleConfig, StoredModule

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "trus.db"


def _db_path() -> Path:
    override = os.environ.get("TRUS_DB_PATH")
    return Path(override) if override else DEFAULT_DB_PATH


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id          TEXT PRIMARY KEY,
                created_at  TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS modules (
                id          TEXT PRIMARY KEY,
                session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                config_json TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_modules_session
                ON modules(session_id, created_at);
            """
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def insert_module(session_id: str, config: ModuleConfig) -> StoredModule:
    module_id = str(uuid.uuid4())
    now = _now()
    with _conn() as c:
        c.execute(
            "INSERT INTO modules (id, session_id, config_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (module_id, session_id, config.model_dump_json(), now, now),
        )
    return StoredModule(id=module_id, config=config, created_at=now, updated_at=now)


def list_modules(session_id: str) -> list[StoredModule]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, config_json, created_at, updated_at FROM modules WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        ).fetchall()
    return [
        StoredModule(
            id=r["id"],
            config=ModuleConfig.model_validate_json(r["config_json"]),
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )
        for r in rows
    ]


def update_module(session_id: str, module_id: str, config: ModuleConfig) -> StoredModule | None:
    now = _now()
    with _conn() as c:
        cur = c.execute(
            "UPDATE modules SET config_json = ?, updated_at = ? WHERE id = ? AND session_id = ?",
            (config.model_dump_json(), now, module_id, session_id),
        )
        if cur.rowcount == 0:
            return None
        row = c.execute(
            "SELECT created_at FROM modules WHERE id = ?", (module_id,)
        ).fetchone()
    return StoredModule(id=module_id, config=config, created_at=row["created_at"], updated_at=now)
