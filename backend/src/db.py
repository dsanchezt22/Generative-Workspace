"""Thin SQLite layer. Stdlib only — no SQLAlchemy until we outgrow this."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, cast

from src.schema import Message, ModuleConfig, ModuleVersion, Page, Snapshot, StoredModule

_log = logging.getLogger(__name__)

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
    icon        TEXT,
    parent_id   TEXT,
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
    archived    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_modules_session
    ON modules(session_id, created_at);
CREATE TABLE IF NOT EXISTS module_versions (
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,
    module_id   TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    config_json TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_versions_module
    ON module_versions(module_id, seq);
CREATE TABLE IF NOT EXISTS messages (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    page_id     TEXT,
    role        TEXT NOT NULL,
    text        TEXT NOT NULL,
    module_id   TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session
    ON messages(session_id, page_id, created_at);
CREATE TABLE IF NOT EXISTS snapshots (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    page_id     TEXT,
    label       TEXT NOT NULL,
    data_json   TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_session
    ON snapshots(session_id, page_id, created_at);
-- Semantic generation cache / growing template library (see semantic_cache.py).
-- Global (not per-session): every successful generation becomes a reusable template.
CREATE TABLE IF NOT EXISTS gen_cache (
    id           TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,
    prompt       TEXT NOT NULL,
    norm         TEXT NOT NULL,        -- normalised prompt for exact-match reuse
    embedding    TEXT NOT NULL,        -- JSON array of floats (brute-force cosine; small N)
    configs_json TEXT NOT NULL,        -- list[ModuleConfig] dicts
    hits         INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gen_cache_kind ON gen_cache(kind);
-- Layout Studio: a use-case-indexed library of candidate ModuleConfig layouts
-- (each modelled after leading apps in that category). Curatable; promotable into
-- the generation seed pool (gen_cache).
CREATE TABLE IF NOT EXISTS layout_library (
    id           TEXT PRIMARY KEY,
    use_case     TEXT NOT NULL,
    label        TEXT NOT NULL,
    inspired_by  TEXT,
    config_json  TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_layout_use_case ON layout_library(use_case, created_at);
-- Per-generation telemetry (R-1201/R-1202): one row per LLM-backed handler call.
-- owner is the session id for now; Task 6 swaps it to user id transparently.
CREATE TABLE IF NOT EXISTS gen_events (
    id          TEXT PRIMARY KEY,
    owner       TEXT NOT NULL,
    kind        TEXT NOT NULL,      -- generate | preview | file | refine | insights
    outcome     TEXT NOT NULL,      -- ok | degraded | question | refusal | error
    provider    TEXT,
    model       TEXT,
    latency_ms  INTEGER,
    tokens_in   INTEGER,
    tokens_out  INTEGER,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gen_events_owner_day ON gen_events (owner, created_at);
"""

# Tracks which db file has had its schema ensured this process, so we re-run the
# (idempotent) DDL when the path changes — or when the file vanishes underneath
# a running server. Reliability over cleverness (design doc I.3).
_schema_ready_for: str | None = None
# Serializes the migration body: concurrent first requests against a stale DB must
# not both run ALTER TABLE (the losers would 500 with 'duplicate column name').
_schema_lock = threading.Lock()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    global _schema_ready_for
    path = str(_db_path())

    def _ready() -> bool:
        if _schema_ready_for != path:
            return False
        try:  # cheap guard against the file having been deleted mid-run
            conn.execute("SELECT 1 FROM sessions LIMIT 1")
            return True
        except sqlite3.OperationalError:
            return False

    if _ready():
        return
    with _schema_lock:
        # Double-check inside the lock: a racing thread may have finished the
        # migration (and set _schema_ready_for) while we waited for the lock.
        if _ready():
            return
        conn.executescript(_SCHEMA)
        # Additive migrations for existing databases.
        _migrate(conn)
        conn.commit()
        _schema_ready_for = path


def _migrate(conn: sqlite3.Connection) -> None:
    """Idempotent column/index additions for databases created before a schema change."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(modules)").fetchall()}
    if "page_id" not in cols:
        conn.execute(
            "ALTER TABLE modules ADD COLUMN page_id TEXT REFERENCES pages(id) ON DELETE CASCADE"
        )
    if "archived" not in cols:
        conn.execute("ALTER TABLE modules ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
    # Create the page index after the column is guaranteed to exist.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_modules_page ON modules(page_id, created_at)")
    pcols = {r[1] for r in conn.execute("PRAGMA table_info(pages)").fetchall()}
    if "icon" not in pcols:
        conn.execute("ALTER TABLE pages ADD COLUMN icon TEXT")
    if "parent_id" not in pcols:
        conn.execute("ALTER TABLE pages ADD COLUMN parent_id TEXT")
    # Screenshot-capture metadata on layout_library (all nullable; image never stored).
    lcols = {r[1] for r in conn.execute("PRAGMA table_info(layout_library)").fetchall()}
    for col, decl in (
        ("capture_meta_json", "TEXT"),
        ("ir_digest_json", "TEXT"),
        ("confidence", "REAL"),
        ("embedding", "TEXT"),
    ):
        if col not in lcols:
            conn.execute(f"ALTER TABLE layout_library ADD COLUMN {col} {decl}")


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # busy_timeout BEFORE journal_mode: switching to WAL takes a write lock, and a
    # concurrent connection must wait rather than fail with 'database is locked'.
    conn.execute("PRAGMA busy_timeout = 5000")
    if str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower() != "wal":
        conn.execute("PRAGMA journal_mode = WAL")
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


def _record_version(
    c: sqlite3.Connection, module_id: str, session_id: str, config_json: str, when: str
) -> None:
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

_PAGE_COLS = "id, name, icon, parent_id, position, created_at"


def _page_from_row(r, session_id: str) -> Page:
    return Page(
        id=r["id"],
        name=r["name"],
        icon=r["icon"],
        parent_id=r["parent_id"],
        position=r["position"],
        session_id=session_id,
        created_at=r["created_at"],
    )


def ensure_default_page(session_id: str) -> Page:
    """Return the first page for a session, creating it if none exist."""
    with _conn() as c:
        row = c.execute(
            f"SELECT {_PAGE_COLS} FROM pages WHERE session_id = ? ORDER BY position LIMIT 1",
            (session_id,),
        ).fetchone()
        if row:
            return _page_from_row(row, session_id)
        page_id = str(uuid.uuid4())
        now = _now()
        c.execute(
            "INSERT INTO pages (id, session_id, name, icon, position, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (page_id, session_id, "Main", "🏠", 0, now),
        )
    return Page(
        id=page_id, name="Main", icon="🏠", position=0, session_id=session_id, created_at=now
    )


def list_pages(session_id: str) -> list[Page]:
    with _conn() as c:
        rows = c.execute(
            f"SELECT {_PAGE_COLS} FROM pages WHERE session_id = ? ORDER BY position",
            (session_id,),
        ).fetchall()
    return [_page_from_row(r, session_id) for r in rows]


def create_page(
    session_id: str, name: str, icon: str | None = None, parent_id: str | None = None
) -> Page:
    with _conn() as c:
        max_pos = c.execute(
            "SELECT COALESCE(MAX(position), -1) FROM pages WHERE session_id = ?",
            (session_id,),
        ).fetchone()[0]
        page_id = str(uuid.uuid4())
        now = _now()
        position = max_pos + 1
        c.execute(
            "INSERT INTO pages (id, session_id, name, icon, parent_id, position, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (page_id, session_id, name, icon, parent_id, position, now),
        )
    return Page(
        id=page_id,
        name=name,
        icon=icon,
        parent_id=parent_id,
        position=position,
        session_id=session_id,
        created_at=now,
    )


_UNSET = object()


def update_page(
    session_id: str, page_id: str, name=_UNSET, icon=_UNSET, parent_id=_UNSET
) -> Page | None:
    sets, params = [], []
    if name is not _UNSET:
        sets.append("name = ?")
        params.append(name)
    if icon is not _UNSET:
        sets.append("icon = ?")
        params.append(icon)
    if parent_id is not _UNSET:
        sets.append("parent_id = ?")
        params.append(parent_id)
    if not sets:
        return get_page(session_id, page_id)
    params += [page_id, session_id]
    with _conn() as c:
        cur = c.execute(
            f"UPDATE pages SET {', '.join(sets)} WHERE id = ? AND session_id = ?", params
        )
        if cur.rowcount == 0:
            return None
        row = c.execute(f"SELECT {_PAGE_COLS} FROM pages WHERE id = ?", (page_id,)).fetchone()
    return _page_from_row(row, session_id)


def get_page(session_id: str, page_id: str) -> Page | None:
    with _conn() as c:
        row = c.execute(
            f"SELECT {_PAGE_COLS} FROM pages WHERE id = ? AND session_id = ?", (page_id, session_id)
        ).fetchone()
    return _page_from_row(row, session_id) if row else None


def reorder_pages(session_id: str, ordered_ids: list[str]) -> list[Page]:
    with _conn() as c:
        for i, pid in enumerate(ordered_ids):
            c.execute(
                "UPDATE pages SET position = ? WHERE id = ? AND session_id = ?",
                (i, pid, session_id),
            )
    return list_pages(session_id)


# Back-compat alias.
def rename_page(session_id: str, page_id: str, name: str) -> Page | None:
    return update_page(session_id, page_id, name=name)


def delete_page(session_id: str, page_id: str) -> bool:
    """Delete a page and all its modules. Refuses to delete the last page."""
    with _conn() as c:
        count = c.execute(
            "SELECT COUNT(*) FROM pages WHERE session_id = ?", (session_id,)
        ).fetchone()[0]
        if count <= 1:
            return False
        cur = c.execute("DELETE FROM pages WHERE id = ? AND session_id = ?", (page_id, session_id))
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Modules
# ---------------------------------------------------------------------------


def insert_module(
    session_id: str, config: ModuleConfig, page_id: str | None = None
) -> StoredModule:
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
    return StoredModule(
        id=module_id, config=config, created_at=now, updated_at=now, page_id=page_id
    )


def _stored_from_row(r) -> StoredModule | None:
    """Parse a modules row, or quarantine it (R-1105): an unreadable row must
    degrade only itself, never the caller's whole list/get."""
    try:
        return StoredModule(
            id=r["id"],
            config=ModuleConfig.model_validate_json(r["config_json"]),
            created_at=r["created_at"],
            updated_at=r["updated_at"],
            page_id=r["page_id"],
            archived=bool(r["archived"]),
        )
    except Exception:
        _log.warning("Quarantined unreadable module row %s (R-1105)", r["id"])
        return None


_MOD_COLS = "id, page_id, config_json, created_at, updated_at, archived"


def get_module(session_id: str, module_id: str) -> StoredModule | None:
    with _conn() as c:
        row = c.execute(
            f"SELECT {_MOD_COLS} FROM modules WHERE id = ? AND session_id = ?",
            (module_id, session_id),
        ).fetchone()
    return _stored_from_row(row) if row else None


def list_modules(session_id: str, page_id: str | None = None) -> list[StoredModule]:
    with _conn() as c:
        if page_id:
            rows = c.execute(
                f"SELECT {_MOD_COLS} FROM modules WHERE session_id = ? AND page_id = ? AND archived = 0 ORDER BY created_at",
                (session_id, page_id),
            ).fetchall()
        else:
            rows = c.execute(
                f"SELECT {_MOD_COLS} FROM modules WHERE session_id = ? AND archived = 0 ORDER BY created_at",
                (session_id,),
            ).fetchall()
    return [m for m in (_stored_from_row(r) for r in rows) if m is not None]


def list_archived(session_id: str) -> list[StoredModule]:
    with _conn() as c:
        rows = c.execute(
            f"SELECT {_MOD_COLS} FROM modules WHERE session_id = ? AND archived = 1 ORDER BY updated_at DESC",
            (session_id,),
        ).fetchall()
    return [m for m in (_stored_from_row(r) for r in rows) if m is not None]


def set_archived(session_id: str, module_id: str, archived: bool) -> StoredModule | None:
    with _conn() as c:
        cur = c.execute(
            "UPDATE modules SET archived = ?, updated_at = ? WHERE id = ? AND session_id = ?",
            (1 if archived else 0, _now(), module_id, session_id),
        )
        if cur.rowcount == 0:
            return None
        row = c.execute(f"SELECT {_MOD_COLS} FROM modules WHERE id = ?", (module_id,)).fetchone()
    return _stored_from_row(row)


def duplicate_module(session_id: str, module_id: str) -> StoredModule | None:
    existing = get_module(session_id, module_id)
    if existing is None:
        return None
    cfg = existing.config.model_copy(deep=True)
    cfg.title = f"{cfg.title} copy"
    cfg.layout.x += 32
    cfg.layout.y += 32
    return insert_module(session_id, cfg, page_id=existing.page_id)


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
            "SELECT page_id, created_at, archived FROM modules WHERE id = ?", (module_id,)
        ).fetchone()
    return StoredModule(
        id=module_id,
        config=config,
        created_at=row["created_at"],
        updated_at=now,
        page_id=row["page_id"],
        archived=bool(row["archived"]),
    )


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
    """History for a module. A row with unreadable config_json is quarantined
    (skipped, logged) rather than failing the whole history load (R-1105)."""
    with _conn() as c:
        rows = c.execute(
            "SELECT seq, config_json, created_at FROM module_versions WHERE module_id = ? AND session_id = ? ORDER BY seq",
            (module_id, session_id),
        ).fetchall()
    out = []
    for r in rows:
        try:
            out.append(
                ModuleVersion(
                    config=ModuleConfig.model_validate_json(r["config_json"]),
                    created_at=r["created_at"],
                )
            )
        except Exception:
            _log.warning("Quarantined unreadable module_versions row seq=%s (R-1105)", r["seq"])
    return out


# ---------------------------------------------------------------------------
# Conversation log (the prompts that shaped a page)
# ---------------------------------------------------------------------------


def add_message(
    session_id: str,
    role: Literal["user", "assistant"],
    text: str,
    page_id: str | None = None,
    module_id: str | None = None,
) -> Message:
    message_id = str(uuid.uuid4())
    now = _now()
    with _conn() as c:
        c.execute(
            "INSERT INTO messages (id, session_id, page_id, role, text, module_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (message_id, session_id, page_id, role, text, module_id, now),
        )
    return Message(
        id=message_id, role=role, text=text, module_id=module_id, page_id=page_id, created_at=now
    )


def list_messages(session_id: str, page_id: str | None = None) -> list[Message]:
    with _conn() as c:
        if page_id:
            rows = c.execute(
                "SELECT id, page_id, role, text, module_id, created_at FROM messages "
                "WHERE session_id = ? AND page_id = ? ORDER BY created_at, rowid",
                (session_id, page_id),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT id, page_id, role, text, module_id, created_at FROM messages "
                "WHERE session_id = ? ORDER BY created_at, rowid",
                (session_id,),
            ).fetchall()
    return [
        Message(
            id=r["id"],
            page_id=r["page_id"],
            role=r["role"],
            text=r["text"],
            module_id=r["module_id"],
            created_at=r["created_at"],
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Snapshots (point-in-time capture of a page)
# ---------------------------------------------------------------------------


def create_snapshot(session_id: str, page_id: str | None, label: str) -> Snapshot:
    mods = list_modules(session_id, page_id)
    data = json.dumps([m.config.model_dump() for m in mods])
    snap_id = str(uuid.uuid4())
    now = _now()
    with _conn() as c:
        c.execute(
            "INSERT INTO snapshots (id, session_id, page_id, label, data_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (snap_id, session_id, page_id, label, data, now),
        )
    return Snapshot(
        id=snap_id, page_id=page_id, label=label, module_count=len(mods), created_at=now
    )


def list_snapshots(session_id: str, page_id: str | None = None) -> list[Snapshot]:
    with _conn() as c:
        if page_id:
            rows = c.execute(
                "SELECT id, page_id, label, data_json, created_at FROM snapshots WHERE session_id = ? AND page_id = ? ORDER BY created_at DESC",
                (session_id, page_id),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT id, page_id, label, data_json, created_at FROM snapshots WHERE session_id = ? ORDER BY created_at DESC",
                (session_id,),
            ).fetchall()
    out = []
    for r in rows:
        try:
            count = len(json.loads(r["data_json"]))
        except Exception:
            count = 0
        out.append(
            Snapshot(
                id=r["id"],
                page_id=r["page_id"],
                label=r["label"],
                module_count=count,
                created_at=r["created_at"],
            )
        )
    return out


def restore_snapshot(session_id: str, snapshot_id: str) -> bool:
    with _conn() as c:
        row = c.execute(
            "SELECT page_id, data_json FROM snapshots WHERE id = ? AND session_id = ?",
            (snapshot_id, session_id),
        ).fetchone()
    if row is None:
        return False
    page_id = row["page_id"]
    # Parse AND validate every module config up front — before touching any live
    # data. A snapshot with an unreadable row aborts cleanly (R-1105): no partial
    # restore, no modules deleted.
    try:
        raw_configs = json.loads(row["data_json"])
        configs = [ModuleConfig.model_validate(cfg) for cfg in raw_configs]
    except Exception:
        _log.warning("Quarantined unreadable snapshot %s (R-1105); restore aborted", snapshot_id)
        return False
    # Replace the page's live modules with the snapshot's.
    for m in list_modules(session_id, page_id):
        delete_module(session_id, m.id)
    for cfg in configs:
        insert_module(session_id, cfg, page_id=page_id)
    return True


def delete_snapshot(session_id: str, snapshot_id: str) -> bool:
    with _conn() as c:
        cur = c.execute(
            "DELETE FROM snapshots WHERE id = ? AND session_id = ?", (snapshot_id, session_id)
        )
        return cur.rowcount > 0


def clear_messages(session_id: str, page_id: str | None = None) -> int:
    with _conn() as c:
        if page_id:
            cur = c.execute(
                "DELETE FROM messages WHERE session_id = ? AND page_id = ?",
                (session_id, page_id),
            )
        else:
            cur = c.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        return cur.rowcount


def undo_module(session_id: str, module_id: str) -> StoredModule | None:
    """Revert a module to its previous version. Returns None when there is
    nothing to undo (unknown module, wrong session, or no older readable
    version). A corrupt version row is quarantined (logged, skipped) and undo
    falls through to the next older version (R-1105)."""
    now = _now()
    with _conn() as c:
        rows = c.execute(
            "SELECT seq, config_json FROM module_versions WHERE module_id = ? AND session_id = ? ORDER BY seq DESC",
            (module_id, session_id),
        ).fetchall()
        if len(rows) < 2:
            return None
        current = rows[0]
        previous = None
        previous_config: ModuleConfig | None = None
        for candidate in rows[1:]:
            try:
                previous_config = ModuleConfig.model_validate_json(candidate["config_json"])
            except Exception:
                _log.warning(
                    "Quarantined unreadable module_versions row seq=%s (R-1105)",
                    candidate["seq"],
                )
                continue
            previous = candidate
            break
        if previous is None or previous_config is None:
            return None
        c.execute("DELETE FROM module_versions WHERE seq = ?", (current["seq"],))
        c.execute(
            "UPDATE modules SET config_json = ?, updated_at = ? WHERE id = ? AND session_id = ?",
            (previous["config_json"], now, module_id, session_id),
        )
        row = c.execute(
            "SELECT created_at, page_id, archived FROM modules WHERE id = ?", (module_id,)
        ).fetchone()
    return StoredModule(
        id=module_id,
        config=previous_config,
        created_at=row["created_at"],
        updated_at=now,
        page_id=row["page_id"],
        archived=bool(row["archived"]),
    )


# ── Generation cache / template library ──────────────────────────────────────


def cache_rows(kind: str, limit: int = 1000) -> list[sqlite3.Row]:
    """Most-recent cache entries for a kind (small N → brute-force cosine upstream)."""
    with _conn() as c:
        return c.execute(
            "SELECT id, prompt, norm, embedding, configs_json FROM gen_cache "
            "WHERE kind = ? ORDER BY created_at DESC LIMIT ?",
            (kind, limit),
        ).fetchall()


def cache_add(kind: str, prompt: str, norm: str, embedding_json: str, configs_json: str) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO gen_cache (id, kind, prompt, norm, embedding, configs_json, hits, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
            (uuid.uuid4().hex, kind, prompt, norm, embedding_json, configs_json, _now()),
        )


def cache_hit(entry_id: str) -> None:
    with _conn() as c:
        c.execute("UPDATE gen_cache SET hits = hits + 1 WHERE id = ?", (entry_id,))


def cache_stats() -> dict:
    with _conn() as c:
        row = c.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(hits), 0) AS hits FROM gen_cache"
        ).fetchone()
    return {"entries": row["n"], "hits": row["hits"]}


# ── Layout Studio library ────────────────────────────────────────────────────

_LAYOUT_COLS = "id, use_case, label, inspired_by, config_json, created_at, capture_meta_json"


def layout_add(
    use_case: str,
    label: str,
    inspired_by: str | None,
    config_json: str,
    *,
    capture_meta_json: str | None = None,
    ir_digest_json: str | None = None,
    confidence: float | None = None,
    embedding: str | None = None,
) -> str:
    """Insert a library layout. The capture_* fields are optional screenshot-capture
    metadata (None for non-vision layouts) — additive, so existing callers are unaffected."""
    lid = uuid.uuid4().hex
    cols = ["id", "use_case", "label", "inspired_by", "config_json", "created_at"]
    vals: list = [lid, use_case, label, inspired_by, config_json, _now()]
    for name, value in (
        ("capture_meta_json", capture_meta_json),
        ("ir_digest_json", ir_digest_json),
        ("confidence", confidence),
        ("embedding", embedding),
    ):
        if value is not None:
            cols.append(name)
            vals.append(value)
    placeholders = ", ".join("?" for _ in cols)
    with _conn() as c:
        c.execute(
            f"INSERT INTO layout_library ({', '.join(cols)}) VALUES ({placeholders})",
            tuple(vals),
        )
    return lid


def layout_list(use_case: str | None = None) -> list[sqlite3.Row]:
    with _conn() as c:
        if use_case:
            return c.execute(
                f"SELECT {_LAYOUT_COLS} FROM layout_library WHERE use_case = ? ORDER BY created_at DESC",
                (use_case,),
            ).fetchall()
        return c.execute(
            f"SELECT {_LAYOUT_COLS} FROM layout_library ORDER BY created_at DESC"
        ).fetchall()


def layout_get(layout_id: str) -> sqlite3.Row | None:
    with _conn() as c:
        row = c.execute(
            f"SELECT {_LAYOUT_COLS} FROM layout_library WHERE id = ?", (layout_id,)
        ).fetchone()
        return cast("sqlite3.Row | None", row)


def layout_delete(layout_id: str) -> bool:
    with _conn() as c:
        return c.execute("DELETE FROM layout_library WHERE id = ?", (layout_id,)).rowcount > 0


def layout_counts() -> dict[str, int]:
    with _conn() as c:
        rows = c.execute(
            "SELECT use_case, COUNT(*) AS n FROM layout_library GROUP BY use_case"
        ).fetchall()
    return {r["use_case"]: r["n"] for r in rows}


# ── Generation telemetry (R-1201/R-1202) ─────────────────────────────────────


def add_gen_event(
    owner: str,
    kind: str,
    outcome: str,
    provider: str | None,
    model: str | None,
    latency_ms: int,
    tokens_in: int | None,
    tokens_out: int | None,
) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO gen_events (id, owner, kind, outcome, provider, model,"
            " latency_ms, tokens_in, tokens_out, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                owner,
                kind,
                outcome,
                provider,
                model,
                latency_ms,
                tokens_in,
                tokens_out,
                _now(),
            ),
        )


def gen_stats(days: int = 7) -> dict:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _conn() as c:
        rows = c.execute(
            "SELECT outcome, COUNT(*) n, SUM(COALESCE(tokens_in,0)) tin,"
            " SUM(COALESCE(tokens_out,0)) tout, AVG(latency_ms) lat"
            " FROM gen_events WHERE created_at >= ? GROUP BY outcome",
            (cutoff,),
        ).fetchall()
    return {
        "total": sum(r["n"] for r in rows),
        "by_outcome": {r["outcome"]: r["n"] for r in rows},
        "tokens_in": sum(r["tin"] or 0 for r in rows),
        "tokens_out": sum(r["tout"] or 0 for r in rows),
        "avg_latency_ms": round(
            sum((r["lat"] or 0) * r["n"] for r in rows) / max(1, sum(r["n"] for r in rows))
        ),
    }


def daily_active(days: int = 14) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _conn() as c:
        rows = c.execute(
            "SELECT substr(created_at, 1, 10) day, COUNT(DISTINCT owner) owners"
            " FROM gen_events WHERE created_at >= ? GROUP BY day ORDER BY day DESC",
            (cutoff,),
        ).fetchall()
    return [{"day": r["day"], "owners": r["owners"]} for r in rows]
