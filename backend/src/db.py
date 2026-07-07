"""Thin SQLite layer. Stdlib only — no SQLAlchemy until we outgrow this."""

from __future__ import annotations

import json
import logging
import os
import secrets
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, cast

from src.schema import (
    Message,
    ModuleConfig,
    ModuleVersion,
    Page,
    Snapshot,
    StoredModule,
    StructureProposal,
)

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
-- Invite-claimed identities (R-901-905). A user is a data OWNER: their id also
-- gets a sessions row (see create_user) so owner-keyed content satisfies the
-- session_id foreign keys below.
CREATE TABLE IF NOT EXISTS users (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    invite_token TEXT NOT NULL UNIQUE,
    created_at   TEXT NOT NULL,
    revoked_at   TEXT
);
CREATE TABLE IF NOT EXISTS pages (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    icon        TEXT,
    parent_id   TEXT,
    position    INTEGER NOT NULL DEFAULT 0,
    -- R-502/R-504: a CHILD page's placement (world coords) on its PARENT's
    -- canvas as an enterable portal tile. Nullable → auto-placed until dragged.
    portal_x    REAL,
    portal_y    REAL,
    -- R-504 completion: the page's OWN saved viewport (pan offset + zoom), so a
    -- user's view resumes across devices. Nullable → client default until saved.
    view_x      REAL,
    view_y      REAL,
    view_zoom   REAL,
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
    rev         INTEGER NOT NULL DEFAULT 0,
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
-- Live external-data cache (R-701/R-704): per-provider+query (NOT per-owner —
-- weather/nutrition lookups are public data), bounding outbound fetches to the
-- caller-supplied refresh_secs TTL (enforced in services/live_data.py against
-- fetched_at, not stored here). Row count is capped on write (live_cache_set
-- prunes the oldest by fetched_at past TRUS_LIVE_CACHE_MAX, default 5000).
CREATE TABLE IF NOT EXISTS live_cache (
    provider     TEXT NOT NULL,
    query_hash   TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    fetched_at   TEXT NOT NULL,
    PRIMARY KEY (provider, query_hash)
);
-- Evolving user profile store (R-801/R-802): per-owner facts Trus has learned
-- ("remembers you"). owner is the same _owner_id key as every other per-owner
-- store (R-903) — a claimed uid, or (dev only) the anonymous sid.
CREATE TABLE IF NOT EXISTS user_profile (
    id          TEXT PRIMARY KEY,
    owner       TEXT NOT NULL,
    kind        TEXT NOT NULL,       -- goal | preference | pattern | fact
    text        TEXT NOT NULL,
    source      TEXT NOT NULL,       -- interview | prompt | activity | manual
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_user_profile_owner ON user_profile(owner, updated_at);
-- V2 trust spine (DESIGN-RECONCILED rulings 2/5): server-side runtime
-- automations. owner = the _owner_id key (claimed uid, or dev-only anon sid).
-- NOT schema.Automation (the client-side intra-module rule): different concept,
-- different store. All-new tables → no _migrate entries needed.
CREATE TABLE IF NOT EXISTS automations (
    id            TEXT PRIMARY KEY,
    owner         TEXT NOT NULL,
    page_id       TEXT REFERENCES pages(id) ON DELETE CASCADE,  -- the surface it belongs to (nullable)
    name          TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',   -- plain-language "exactly what it does"
    action_type   TEXT NOT NULL,              -- key into services/actions.ACTION_SPECS
    action_json   TEXT NOT NULL,              -- typed AutoAction (discriminated union), quarantined on read
    state_json    TEXT NOT NULL DEFAULT '{}', -- executor scratch (watch edge-trigger 'armed' flag)
    schedule_kind TEXT NOT NULL,              -- 'interval' | 'daily'
    interval_secs INTEGER,                    -- 300..604800 (weekly allowed)
    daily_at      TEXT,                       -- 'HH:MM' UTC
    trust_dial    INTEGER NOT NULL DEFAULT 1, -- 0 ask-always | 1 standard | 2 trusted; PATCH is the ONLY writer
    enabled       INTEGER NOT NULL DEFAULT 1,
    next_run_at   TEXT,                       -- due when <= now; ALSO the CAS claim token
    last_run_at   TEXT,
    last_status   TEXT,                       -- mirror of latest activity kind for cheap list views
    failure_count INTEGER NOT NULL DEFAULT 0, -- consecutive executor EXCEPTIONS; drives backoff
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_automations_due   ON automations(enabled, next_run_at);
CREATE INDEX IF NOT EXISTS idx_automations_owner ON automations(owner, created_at);
-- Parked consequential fires (AUT-2). payload_json is the FROZEN fully-resolved
-- action payload captured at park time — approve executes exactly these bytes,
-- never a re-computation (no preview/execution drift, zero LLM spend on approve).
CREATE TABLE IF NOT EXISTS approvals (
    id            TEXT PRIMARY KEY,
    owner         TEXT NOT NULL,
    automation_id TEXT NOT NULL,
    action_type   TEXT NOT NULL,
    payload_json  TEXT NOT NULL,
    summary       TEXT NOT NULL,             -- template-composed future-tense line, frozen at park
    preview_json  TEXT,                      -- typed PreviewPayload dict or NULL
    status        TEXT NOT NULL DEFAULT 'pending', -- pending|approved|rejected|expired|failed
    expires_at    TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    decided_at    TEXT,
    executed_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_approvals_owner ON approvals(owner, status, created_at);
-- Append-only activity journal (TAP-1). summary composed AT WRITE TIME and
-- stored — history never rewrites when copy templates change. Pruned per owner
-- on write past TRUS_ACTIVITY_MAX (the live_cache cap pattern).
CREATE TABLE IF NOT EXISTS activity (
    id            TEXT PRIMARY KEY,
    owner         TEXT NOT NULL,
    automation_id TEXT,                      -- nullable: rows survive automation deletion
    approval_id   TEXT,
    kind          TEXT NOT NULL,             -- ran|held|approved|rejected|expired|failed|skipped
    summary       TEXT NOT NULL,
    detail_json   TEXT,                      -- small typed dict: {module_id?, page_id?, simulated?, reason?}
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_activity_owner ON activity(owner, created_at);
-- Per-surface read-only share links (SHARE-1..3). ONE ACTIVE link per page,
-- enforced by the partial unique index (DB guarantee) and by share_create's
-- revoke-then-insert transaction. Revoked rows are kept as audit history.
-- owner is the same _owner_id key as everywhere else (claimed uid, or dev-only
-- anon sid). token is secrets.token_urlsafe(32) — 256 bits, unguessable;
-- UNIQUE gives the indexed lookup for the public path.
CREATE TABLE IF NOT EXISTS share_links (
    id          TEXT PRIMARY KEY,
    token       TEXT NOT NULL UNIQUE,
    owner       TEXT NOT NULL,
    page_id     TEXT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL,
    revoked_at  TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_share_links_active
    ON share_links(page_id) WHERE revoked_at IS NULL;
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
    if "rev" not in cols:
        conn.execute("ALTER TABLE modules ADD COLUMN rev INTEGER NOT NULL DEFAULT 0")
    # Create the page index after the column is guaranteed to exist.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_modules_page ON modules(page_id, created_at)")
    pcols = {r[1] for r in conn.execute("PRAGMA table_info(pages)").fetchall()}
    if "icon" not in pcols:
        conn.execute("ALTER TABLE pages ADD COLUMN icon TEXT")
    if "parent_id" not in pcols:
        conn.execute("ALTER TABLE pages ADD COLUMN parent_id TEXT")
    # SURF: an app-surface accent token on a (child) page — additive, nullable.
    if "accent" not in pcols:
        conn.execute("ALTER TABLE pages ADD COLUMN accent TEXT")
    # R-502/R-504: portal placement of a child page on its parent's canvas.
    if "portal_x" not in pcols:
        conn.execute("ALTER TABLE pages ADD COLUMN portal_x REAL")
    if "portal_y" not in pcols:
        conn.execute("ALTER TABLE pages ADD COLUMN portal_y REAL")
    # R-504 completion: the page's own saved viewport (pan/zoom, cross-device).
    if "view_x" not in pcols:
        conn.execute("ALTER TABLE pages ADD COLUMN view_x REAL")
    if "view_y" not in pcols:
        conn.execute("ALTER TABLE pages ADD COLUMN view_y REAL")
    if "view_zoom" not in pcols:
        conn.execute("ALTER TABLE pages ADD COLUMN view_zoom REAL")
    # Screenshot-capture metadata on layout_library (all nullable; image never stored).
    lcols = {r[1] for r in conn.execute("PRAGMA table_info(layout_library)").fetchall()}
    for col, decl in (
        ("capture_meta_json", "TEXT"),
        ("ir_digest_json", "TEXT"),
        ("confidence", "REAL"),
        ("embedding", "TEXT"),
    ):
        if col not in lcols:
            # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query,python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
            conn.execute(f"ALTER TABLE layout_library ADD COLUMN {col} {decl}")
    # Identity (Task 6): link a browser session to a claimed user, and give the
    # shared stores a per-owner key. owner backfills to 'local' so pre-identity
    # rows stay reachable under the library's default owner.
    scols = {r[1] for r in conn.execute("PRAGMA table_info(sessions)").fetchall()}
    if "user_id" not in scols:
        conn.execute("ALTER TABLE sessions ADD COLUMN user_id TEXT")
    gcols = {r[1] for r in conn.execute("PRAGMA table_info(gen_cache)").fetchall()}
    if "owner" not in gcols:
        conn.execute("ALTER TABLE gen_cache ADD COLUMN owner TEXT NOT NULL DEFAULT 'local'")
    if "owner" not in lcols:
        conn.execute("ALTER TABLE layout_library ADD COLUMN owner TEXT NOT NULL DEFAULT 'local'")


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
# Users / identity (R-901-905)
# ---------------------------------------------------------------------------


def create_user(name: str) -> dict:
    """Provision an invite-claimable identity. The double uuid4-hex token is
    unguessable and URL-safe. The user id also gets a sessions row so any
    owner-keyed content (pages/modules/…) satisfies the session_id foreign keys."""
    token = uuid.uuid4().hex + uuid.uuid4().hex
    uid = str(uuid.uuid4())
    now = _now()
    with _conn() as c:
        c.execute(
            "INSERT INTO users (id, name, invite_token, created_at) VALUES (?, ?, ?, ?)",
            (uid, name, token, now),
        )
        c.execute("INSERT OR IGNORE INTO sessions (id, created_at) VALUES (?, ?)", (uid, now))
    return {"id": uid, "name": name, "invite_token": token}


def user_by_token(token: str) -> dict | None:
    with _conn() as c:
        r = c.execute(
            "SELECT id, name, revoked_at FROM users WHERE invite_token = ?", (token,)
        ).fetchone()
    return dict(r) if r else None


def user_by_id(user_id: str) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT id, name, revoked_at FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(r) if r else None


def list_users() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, name, invite_token, created_at, revoked_at FROM users ORDER BY created_at"
        ).fetchall()
    return [dict(r) for r in rows]


def revoke_user(user_id: str) -> bool:
    with _conn() as c:
        cur = c.execute("UPDATE users SET revoked_at = ? WHERE id = ?", (_now(), user_id))
        return cur.rowcount > 0


def adopt_session_data(old_owner: str, user_id: str) -> None:
    """First claim from a device that already has anonymous data: move every
    owner-keyed row from the anonymous session to the user, so pre-claim work
    is preserved (R-902). Covers the session_id-keyed workspace tables plus the
    owner-keyed shared stores (gen_cache, layout_library). gen_events is left
    under the anonymous owner — it is historical telemetry, not user content."""
    if old_owner == user_id:
        return
    with _conn() as c:
        c.execute("UPDATE pages SET session_id = ? WHERE session_id = ?", (user_id, old_owner))
        c.execute("UPDATE modules SET session_id = ? WHERE session_id = ?", (user_id, old_owner))
        c.execute(
            "UPDATE module_versions SET session_id = ? WHERE session_id = ?", (user_id, old_owner)
        )
        c.execute("UPDATE messages SET session_id = ? WHERE session_id = ?", (user_id, old_owner))
        c.execute("UPDATE snapshots SET session_id = ? WHERE session_id = ?", (user_id, old_owner))
        c.execute("UPDATE gen_cache SET owner = ? WHERE owner = ?", (user_id, old_owner))
        c.execute("UPDATE layout_library SET owner = ? WHERE owner = ?", (user_id, old_owner))
        # V2 trust spine (R-902): pre-claim automations/approvals/activity survive
        # an invite claim, re-owned to the user alongside the workspace tables above.
        c.execute("UPDATE automations SET owner = ? WHERE owner = ?", (user_id, old_owner))
        c.execute("UPDATE approvals SET owner = ? WHERE owner = ?", (user_id, old_owner))
        c.execute("UPDATE activity SET owner = ? WHERE owner = ?", (user_id, old_owner))
        # SHARE: without this a pre-claim share link dies on claim AND the still-
        # active orphan row makes the next share_create violate the partial unique
        # index → 500.
        c.execute("UPDATE share_links SET owner = ? WHERE owner = ?", (user_id, old_owner))


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

_PAGE_COLS = (
    "id, name, icon, accent, parent_id, position, "
    "portal_x, portal_y, view_x, view_y, view_zoom, created_at"
)


def _page_from_row(r, session_id: str) -> Page:
    return Page(
        id=r["id"],
        name=r["name"],
        icon=r["icon"],
        accent=r["accent"],
        parent_id=r["parent_id"],
        position=r["position"],
        portal_x=r["portal_x"],
        portal_y=r["portal_y"],
        view_x=r["view_x"],
        view_y=r["view_y"],
        view_zoom=r["view_zoom"],
        session_id=session_id,
        created_at=r["created_at"],
    )


def ensure_default_page(session_id: str) -> Page:
    """Return the first page for a session, creating it if none exist."""
    with _conn() as c:
        row = c.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
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
        rows = c.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
            f"SELECT {_PAGE_COLS} FROM pages WHERE session_id = ? ORDER BY position",
            (session_id,),
        ).fetchall()
    return [_page_from_row(r, session_id) for r in rows]


def page_module_counts(session_id: str) -> dict[str, int]:
    """Live (non-archived) module count per page for this owner — one grouped
    COUNT, so the portal tiles (R-502) can show a cheap "N tools" preview
    WITHOUT loading any child page's module configs. Owner-scoped."""
    with _conn() as c:
        rows = c.execute(
            "SELECT page_id, COUNT(*) AS n FROM modules"
            " WHERE session_id = ? AND archived = 0 AND page_id IS NOT NULL"
            " GROUP BY page_id",
            (session_id,),
        ).fetchall()
    return {r["page_id"]: r["n"] for r in rows}


def create_page(
    session_id: str,
    name: str,
    icon: str | None = None,
    parent_id: str | None = None,
    accent: str | None = None,
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
            "INSERT INTO pages (id, session_id, name, icon, accent, parent_id, position, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (page_id, session_id, name, icon, accent, parent_id, position, now),
        )
    return Page(
        id=page_id,
        name=name,
        icon=icon,
        accent=accent,
        parent_id=parent_id,
        position=position,
        session_id=session_id,
        created_at=now,
    )


_UNSET = object()


def update_page(
    session_id: str,
    page_id: str,
    name=_UNSET,
    icon=_UNSET,
    accent=_UNSET,
    parent_id=_UNSET,
    portal_x=_UNSET,
    portal_y=_UNSET,
    view_x=_UNSET,
    view_y=_UNSET,
    view_zoom=_UNSET,
) -> Page | None:
    sets, params = [], []
    if name is not _UNSET:
        sets.append("name = ?")
        params.append(name)
    if icon is not _UNSET:
        sets.append("icon = ?")
        params.append(icon)
    if accent is not _UNSET:
        sets.append("accent = ?")
        params.append(accent)
    if parent_id is not _UNSET:
        sets.append("parent_id = ?")
        params.append(parent_id)
    # R-504: portal placement persists on the page row (owner-scoped by the WHERE
    # below), so a child's arrangement on its parent's canvas survives across devices.
    if portal_x is not _UNSET:
        sets.append("portal_x = ?")
        params.append(portal_x)
    if portal_y is not _UNSET:
        sets.append("portal_y = ?")
        params.append(portal_y)
    # R-504 completion: the page's own viewport (pan/zoom) — same owner-scoped
    # additive pattern as the portal placement above.
    if view_x is not _UNSET:
        sets.append("view_x = ?")
        params.append(view_x)
    if view_y is not _UNSET:
        sets.append("view_y = ?")
        params.append(view_y)
    if view_zoom is not _UNSET:
        sets.append("view_zoom = ?")
        params.append(view_zoom)
    if not sets:
        return get_page(session_id, page_id)
    params += [page_id, session_id]
    with _conn() as c:
        cur = c.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
            f"UPDATE pages SET {', '.join(sets)} WHERE id = ? AND session_id = ?", params
        )
        if cur.rowcount == 0:
            return None
        row = c.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
            f"SELECT {_PAGE_COLS} FROM pages WHERE id = ?", (page_id,)
        ).fetchone()
    return _page_from_row(row, session_id)


def get_page(session_id: str, page_id: str) -> Page | None:
    with _conn() as c:
        row = c.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
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
    """Delete a page and all its modules. Refuses to delete the last page.

    R-503 (orphan fix): parent_id is a bare column with NO FK cascade, so a
    naive delete would leave this page's direct children pointing at a deleted
    row — the sidebar tree renders from root, so an orphaned child vanishes.
    Before deleting, REPARENT this page's direct children to its OWN parent
    (grandparent, or NULL/root when this page was top-level): children move up
    one level, never disappear. Owner-scoped by every WHERE clause. The child
    pages and their modules are untouched — only this page's own modules cascade.
    """
    with _conn() as c:
        count = c.execute(
            "SELECT COUNT(*) FROM pages WHERE session_id = ?", (session_id,)
        ).fetchone()[0]
        if count <= 1:
            return False
        row = c.execute(
            "SELECT parent_id FROM pages WHERE id = ? AND session_id = ?",
            (page_id, session_id),
        ).fetchone()
        if row is None:
            return False
        grandparent = row["parent_id"]
        c.execute(
            "UPDATE pages SET parent_id = ? WHERE parent_id = ? AND session_id = ?",
            (grandparent, page_id, session_id),
        )
        cur = c.execute("DELETE FROM pages WHERE id = ? AND session_id = ?", (page_id, session_id))
        return cur.rowcount > 0


def insert_structure(
    owner: str, proposal: StructureProposal, parent_page_id: str | None
) -> tuple[list[Page], list[StoredModule]]:
    """Create a whole structure's pages + modules in ONE transaction (SURF/ONB-1).
    Inlines the page/module INSERT SQL (does NOT call create_page/insert_module,
    which each open+commit their own connection) so a mid-insert exception rolls
    the WHOLE thing back — never a partial structure. Automations are composed and
    created AFTER this commits, by the confirm route's shared creation path (a
    failed automation is dropped+reported, never a partial page)."""
    pages_out: list[Page] = []
    modules_out: list[StoredModule] = []
    now = _now()
    with _conn() as c:
        base = c.execute(
            "SELECT COALESCE(MAX(position), -1) FROM pages WHERE session_id = ?", (owner,)
        ).fetchone()[0]
        for i, sp in enumerate(proposal.pages):
            page_id = str(uuid.uuid4())
            position = base + 1 + i
            c.execute(
                "INSERT INTO pages (id, session_id, name, icon, accent, parent_id, position,"
                " created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (page_id, owner, sp.name, sp.icon, sp.accent, parent_page_id, position, now),
            )
            pages_out.append(
                Page(
                    id=page_id,
                    session_id=owner,
                    name=sp.name,
                    icon=sp.icon,
                    accent=sp.accent,
                    parent_id=parent_page_id,
                    position=position,
                    created_at=now,
                )
            )
            for cfg in sp.modules:
                module_id = str(uuid.uuid4())
                config_json = cfg.model_dump_json()
                c.execute(
                    "INSERT INTO modules (id, session_id, page_id, config_json, created_at,"
                    " updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (module_id, owner, page_id, config_json, now, now),
                )
                _record_version(c, module_id, owner, config_json, now)
                modules_out.append(
                    StoredModule(
                        id=module_id, config=cfg, created_at=now, updated_at=now, page_id=page_id
                    )
                )
    return pages_out, modules_out


def page_overview(owner: str) -> dict[str, dict]:
    """Per-page {modules, automations, last_run_at} for the owner — one grouped
    query set (never N+1). module count is non-archived; automation count +
    last_run_at come from the V2 automations table (REAL from day one)."""
    with _conn() as c:
        mod_counts = {
            r["page_id"]: r["n"]
            for r in c.execute(
                "SELECT page_id, COUNT(*) AS n FROM modules"
                " WHERE session_id = ? AND archived = 0 AND page_id IS NOT NULL GROUP BY page_id",
                (owner,),
            ).fetchall()
        }
        auto = {
            r["page_id"]: (r["n"], r["lr"])
            for r in c.execute(
                "SELECT page_id, COUNT(*) AS n, MAX(last_run_at) AS lr FROM automations"
                " WHERE owner = ? AND page_id IS NOT NULL GROUP BY page_id",
                (owner,),
            ).fetchall()
        }
        page_ids = [
            r["id"]
            for r in c.execute("SELECT id FROM pages WHERE session_id = ?", (owner,)).fetchall()
        ]
    out: dict[str, dict] = {}
    for pid in page_ids:
        n_auto, last_run = auto.get(pid, (0, None))
        out[pid] = {
            "modules": mod_counts.get(pid, 0),
            "automations": n_auto,
            "last_run_at": last_run,
        }
    return out


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
            rev=r["rev"],
        )
    except Exception:
        _log.warning("Quarantined unreadable module row %s (R-1105)", r["id"])
        return None


_MOD_COLS = "id, page_id, config_json, created_at, updated_at, archived, rev"


def get_module(session_id: str, module_id: str) -> StoredModule | None:
    with _conn() as c:
        row = c.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
            f"SELECT {_MOD_COLS} FROM modules WHERE id = ? AND session_id = ?",
            (module_id, session_id),
        ).fetchone()
    return _stored_from_row(row) if row else None


def list_modules(
    session_id: str, page_id: str | None = None, include_archived: bool = False
) -> list[StoredModule]:
    # include_archived is off by default (unchanged behavior); the page-delete
    # confirm passes it True so it can count archived rows the FK cascade also drops.
    archived_clause = "" if include_archived else " AND archived = 0"
    with _conn() as c:
        if page_id:
            rows = c.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
                f"SELECT {_MOD_COLS} FROM modules WHERE session_id = ? AND page_id = ?{archived_clause} ORDER BY created_at",
                (session_id, page_id),
            ).fetchall()
        else:
            rows = c.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
                f"SELECT {_MOD_COLS} FROM modules WHERE session_id = ?{archived_clause} ORDER BY created_at",
                (session_id,),
            ).fetchall()
    return [m for m in (_stored_from_row(r) for r in rows) if m is not None]


def list_archived(session_id: str) -> list[StoredModule]:
    with _conn() as c:
        rows = c.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
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
        row = c.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
            f"SELECT {_MOD_COLS} FROM modules WHERE id = ?", (module_id,)
        ).fetchone()
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


class RevConflict(Exception):
    """Raised when expected_rev no longer matches the stored rev (R-602): another
    writer won the race. Callers surface `current` so the loser can reload
    visibly instead of silently overwriting it."""

    def __init__(self, current: StoredModule) -> None:
        super().__init__(f"rev conflict on module {current.id}")
        self.current = current


def update_module(
    session_id: str, module_id: str, config: ModuleConfig, expected_rev: int | None = None
) -> StoredModule | None:
    """Persist `config`. When `expected_rev` is given, the write only applies if
    the stored rev still matches (optimistic concurrency, R-602) — a mismatch
    raises RevConflict with the current row instead of clobbering it. When
    `expected_rev` is None the write is unconditional (internal writers: refine,
    snapshot restore) but still bumps rev, so an open tab still conflict-detects
    against it."""
    now = _now()
    config_json = config.model_dump_json()
    with _conn() as c:
        if expected_rev is None:
            cur = c.execute(
                "UPDATE modules SET config_json = ?, updated_at = ?, rev = rev + 1"
                " WHERE id = ? AND session_id = ?",
                (config_json, now, module_id, session_id),
            )
        else:
            cur = c.execute(
                "UPDATE modules SET config_json = ?, updated_at = ?, rev = rev + 1"
                " WHERE id = ? AND session_id = ? AND rev = ?",
                (config_json, now, module_id, session_id, expected_rev),
            )
        if cur.rowcount == 0:
            row = c.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
                f"SELECT {_MOD_COLS} FROM modules WHERE id = ? AND session_id = ?",
                (module_id, session_id),
            ).fetchone()
            if row is None:
                return None
            current = _stored_from_row(row)
            if current is not None:
                raise RevConflict(current)
            return None
        _record_version(c, module_id, session_id, config_json, now)
        row = c.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
            f"SELECT {_MOD_COLS} FROM modules WHERE id = ?", (module_id,)
        ).fetchone()
    return _stored_from_row(row)


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


def recent_messages(owner: str, page_id: str | None = None, limit: int = 10) -> list[dict]:
    """The owner's most recent messages ON ONE PAGE (R-302 conversation
    context). Pulls the `limit` NEWEST rows, then returns them OLDEST-first so
    callers can render a natural transcript. R-903: scoped to `owner` by WHERE
    clause — another owner's messages can never appear.

    page_id None returns [] — no page context = no conversation context. This
    is deliberate (review fix 2b-4), NOT list_messages' whole-session fallback:
    the routes can receive page_id=None in a real initial-load race window
    (the frontend fires before activePageId resolves), and a session-wide
    fallback would leak cross-page history into that generation."""
    if not page_id:
        return []
    with _conn() as c:
        rows = c.execute(
            "SELECT role, text FROM messages WHERE session_id = ? AND page_id = ? "
            "ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (owner, page_id, limit),
        ).fetchall()
    return [{"role": r["role"], "text": r["text"]} for r in reversed(rows)]


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
    # v2 format: id + config per entry, so restore can preserve module ids and
    # keep cross-module source_module_id bindings intact (R-1102). v1 (a bare
    # config list, no ids) is still readable by restore_snapshot — see there.
    data = json.dumps([{"id": m.id, "config": m.config.model_dump()} for m in mods])
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


def restore_snapshot(session_id: str, snapshot_id: str) -> Literal["ok", "missing", "corrupt"]:
    """Restore a page's modules from a snapshot (R-1102).

    Runs entirely on ONE connection/transaction: the outer try/except wraps the
    whole `with _conn() as c:` block, so an exception raised anywhere inside it
    (including from a helper called mid-loop) propagates PAST `_conn`'s own
    `conn.commit()` — nothing written during this restore is ever committed, and
    a crash mid-restore leaves the page exactly as it was. Deliberately NOT
    calling list_modules/delete_module/insert_module here: each of those opens
    its OWN connection and commits independently, which is exactly the
    atomicity bug this rewrite fixes (a crash between calls used to leave the
    page half-restored).

    Module ids from the snapshot are PRESERVED (v2 format) so cross-module
    source_module_id bindings still resolve after a restore; v1 snapshots (a
    bare config list, no ids — pre-R-1102) are still restorable, just without
    id continuity. rev bumps on every overwritten module so an open tab still
    conflict-detects (R-602); archived is reset to 0 and page_id is corrected
    for a module that had moved elsewhere since the snapshot was taken.
    """
    try:
        with _conn() as c:
            row = c.execute(
                "SELECT page_id, data_json FROM snapshots WHERE id = ? AND session_id = ?",
                (snapshot_id, session_id),
            ).fetchone()
            if row is None:
                return "missing"
            # Parse AND validate every module config up front — before touching
            # any live data. A snapshot with an unreadable row aborts cleanly
            # (R-1105): no partial restore, no modules deleted.
            try:
                raw = json.loads(row["data_json"])
                if not isinstance(raw, list):
                    raise ValueError("snapshot data_json is not a list")
                # v2: {"id":..., "config":{...}}; v1: a bare config dict — id
                # then falls back to None (fresh id minted on restore).
                entries: list[tuple[str | None, ModuleConfig]] = [
                    (e.get("id"), ModuleConfig.model_validate(e.get("config", e))) for e in raw
                ]
            except Exception:
                _log.warning(
                    "Quarantined unreadable snapshot %s (R-1105); restore aborted", snapshot_id
                )
                return "corrupt"

            now = _now()
            page_id = row["page_id"]
            keep_ids = {mod_id for mod_id, _ in entries if mod_id}

            # Delete live (unarchived) modules on this page that the snapshot
            # doesn't keep — mirrors delete_module's own cleanup so history
            # never orphans (module_versions rows go with their module).
            if page_id is not None:
                live_rows = c.execute(
                    "SELECT id FROM modules WHERE session_id = ? AND page_id = ? AND archived = 0",
                    (session_id, page_id),
                ).fetchall()
            else:
                live_rows = c.execute(
                    "SELECT id FROM modules WHERE session_id = ? AND page_id IS NULL AND archived = 0",
                    (session_id,),
                ).fetchall()
            for m_row in live_rows:
                if m_row["id"] not in keep_ids:
                    c.execute(
                        "DELETE FROM modules WHERE id = ? AND session_id = ?",
                        (m_row["id"], session_id),
                    )
                    c.execute("DELETE FROM module_versions WHERE module_id = ?", (m_row["id"],))

            for mod_id, config in entries:
                cfg_json = config.model_dump_json()
                existing = (
                    c.execute(
                        "SELECT 1 FROM modules WHERE id = ? AND session_id = ?",
                        (mod_id, session_id),
                    ).fetchone()
                    if mod_id
                    else None
                )
                if mod_id and existing:
                    c.execute(
                        "UPDATE modules SET config_json = ?, updated_at = ?, rev = rev + 1,"
                        " page_id = ?, archived = 0 WHERE id = ? AND session_id = ?",
                        (cfg_json, now, page_id, mod_id, session_id),
                    )
                    resolved_id = mod_id
                else:
                    resolved_id = mod_id or str(uuid.uuid4())
                    c.execute(
                        "INSERT INTO modules (id, session_id, page_id, config_json,"
                        " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (resolved_id, session_id, page_id, cfg_json, now, now),
                    )
                _record_version(c, resolved_id, session_id, cfg_json, now)
    except Exception:
        _log.warning("Restore of snapshot %s failed mid-transaction; rolled back", snapshot_id)
        return "corrupt"
    return "ok"


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
        # rev bumps like any other write (R-602): a tab holding the pre-undo rev
        # must conflict-detect, and the tab that undid must get the true new rev.
        c.execute(
            "UPDATE modules SET config_json = ?, updated_at = ?, rev = rev + 1"
            " WHERE id = ? AND session_id = ?",
            (previous["config_json"], now, module_id, session_id),
        )
        # Return the true post-write row (never hand-construct a StoredModule
        # here — a hand-built one silently carried the Pydantic rev default).
        row = c.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
            f"SELECT {_MOD_COLS} FROM modules WHERE id = ?", (module_id,)
        ).fetchone()
    return _stored_from_row(row)


# ── Generation cache / template library ──────────────────────────────────────


def cache_rows(kind: str, owner: str = "local", limit: int = 1000) -> list[sqlite3.Row]:
    """Most-recent cache entries for a kind, scoped to one owner (R-903 — a prompt
    is never served across owners). Small N → brute-force cosine upstream."""
    with _conn() as c:
        return c.execute(
            "SELECT id, prompt, norm, embedding, configs_json FROM gen_cache "
            "WHERE kind = ? AND owner = ? ORDER BY created_at DESC LIMIT ?",
            (kind, owner, limit),
        ).fetchall()


def cache_add(
    kind: str,
    prompt: str,
    norm: str,
    embedding_json: str,
    configs_json: str,
    owner: str = "local",
) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO gen_cache (id, kind, prompt, norm, embedding, configs_json, hits, owner, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)",
            (uuid.uuid4().hex, kind, prompt, norm, embedding_json, configs_json, owner, _now()),
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


# Defensive scan bound so a heavy owner's suggestion query stays a "fast read"
# (R-104's async route) instead of degrading into an unbounded table scan.
_SUGGESTION_SCAN_CAP = 500

# Stage-2b backlog: moved server-side from frontend/src/lib/suggestions.ts'
# filterSuggestions so ANY consumer of GET /api/suggestions gets clean chips —
# the frontend filter stays in place too (belt-and-braces). Kept in sync with
# that file: a 📎-prefixed file-upload log line, a refine-combined prompt
# (PromptBar joins "original — tweak" with this em-dash), a refine imperative
# ("make it…"), and anything under 3 words are all noise, not build ideas.
_SUGGESTION_REFINE_JOIN = " — "
_SUGGESTION_REFINE_PREFIXES = (
    "make it",
    "make the",
    "change ",
    "turn it",
    "also add",
    "remove the",
    "rename ",
)


def _is_suggestion_noise(text: str) -> bool:
    if text.startswith("📎"):
        return True
    if _SUGGESTION_REFINE_JOIN in text:
        return True
    if len(text.split()) < 3:
        return True
    lower = text.lower()
    return any(lower.startswith(p) for p in _SUGGESTION_REFINE_PREFIXES)


def suggestion_prompts(owner: str, limit: int) -> list[str]:
    """This owner's recent distinct generation prompts, for suggestion chips
    (R-104). R-903: scoped to `owner` by WHERE clause — another owner's prompts
    can never appear. gen_cache first, ordered by hits DESC then created_at DESC
    (favors prompts that actually got reused); if that yields fewer than `limit`,
    tops up from recent user-role `messages` rows for the same owner (page-agnostic
    — messages.session_id doubles as the owner key, same as gen_cache.owner).
    Deduped case-insensitively; blob-like entries (len > 200, template seeds),
    empty/whitespace-only strings, and suggestion noise (see
    _is_suggestion_noise) are excluded; messages never re-add a prompt
    gen_cache already contributed."""
    if limit <= 0:
        return []
    out: list[str] = []
    seen: set[str] = set()

    def _consider(text: str | None) -> None:
        text = (text or "").strip()
        if not text or len(text) > 200 or _is_suggestion_noise(text):
            return
        key = text.lower()
        if key in seen:
            return
        seen.add(key)
        out.append(text)

    with _conn() as c:
        for r in c.execute(
            "SELECT prompt FROM gen_cache WHERE owner = ? "
            "ORDER BY hits DESC, created_at DESC LIMIT ?",
            (owner, _SUGGESTION_SCAN_CAP),
        ).fetchall():
            _consider(r["prompt"])
            if len(out) >= limit:
                break
        if len(out) < limit:
            for r in c.execute(
                "SELECT text FROM messages WHERE session_id = ? AND role = 'user' "
                "ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (owner, _SUGGESTION_SCAN_CAP),
            ).fetchall():
                _consider(r["text"])
                if len(out) >= limit:
                    break
    return out


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
    owner: str = "local",
) -> str:
    """Insert a library layout. The capture_* fields are optional screenshot-capture
    metadata (None for non-vision layouts) — additive, so existing callers are unaffected."""
    lid = uuid.uuid4().hex
    cols = ["id", "use_case", "label", "inspired_by", "config_json", "created_at", "owner"]
    vals: list = [lid, use_case, label, inspired_by, config_json, _now(), owner]
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
        c.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
            f"INSERT INTO layout_library ({', '.join(cols)}) VALUES ({placeholders})",
            tuple(vals),
        )
    return lid


def layout_list(use_case: str | None = None, owner: str = "local") -> list[sqlite3.Row]:
    with _conn() as c:
        if use_case:
            return c.execute(
                f"SELECT {_LAYOUT_COLS} FROM layout_library WHERE use_case = ? AND owner = ? "
                "ORDER BY created_at DESC",
                (use_case, owner),
            ).fetchall()
        return c.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
            f"SELECT {_LAYOUT_COLS} FROM layout_library WHERE owner = ? ORDER BY created_at DESC",
            (owner,),
        ).fetchall()


def layout_get(layout_id: str, owner: str = "local") -> sqlite3.Row | None:
    with _conn() as c:
        row = c.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
            f"SELECT {_LAYOUT_COLS} FROM layout_library WHERE id = ? AND owner = ?",
            (layout_id, owner),
        ).fetchone()
        return cast("sqlite3.Row | None", row)


def layout_delete(layout_id: str, owner: str = "local") -> bool:
    with _conn() as c:
        cur = c.execute("DELETE FROM layout_library WHERE id = ? AND owner = ?", (layout_id, owner))
        return cur.rowcount > 0


def layout_counts(owner: str = "local") -> dict[str, int]:
    with _conn() as c:
        rows = c.execute(
            "SELECT use_case, COUNT(*) AS n FROM layout_library WHERE owner = ? GROUP BY use_case",
            (owner,),
        ).fetchall()
    return {r["use_case"]: r["n"] for r in rows}


# ── Generation telemetry (R-1201/R-1202) ─────────────────────────────────────


def _token_cost_rates() -> tuple[float, float]:
    return (
        float(os.environ.get("TRUS_TOKEN_COST_IN", "0")),
        float(os.environ.get("TRUS_TOKEN_COST_OUT", "0")),
    )


def _cost_usd(tokens_in: int, tokens_out: int) -> float:
    """$ estimate for a token count, per TRUS_TOKEN_COST_IN/OUT (per-1k-token $,
    both default 0). Unset/zero rates → 0 cost while the token counts stay real
    (I-1: never show a fake cost derived from unset pricing)."""
    cost_in, cost_out = _token_cost_rates()
    return (tokens_in * cost_in + tokens_out * cost_out) / 1000


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


def owner_cost_today(owner: str) -> dict:
    """This owner's token usage + cost estimate for the current UTC calendar
    day — feeds the generate routes' optional TRUS_DAILY_COST_CAP_USD gate
    (R-1202 completion). Scoped to `owner` AND today only: a different owner's
    spend, or this owner's spend on a prior day, never counts toward it."""
    day_start = (
        datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    )
    with _conn() as c:
        row = c.execute(
            "SELECT SUM(COALESCE(tokens_in,0)) tin, SUM(COALESCE(tokens_out,0)) tout"
            " FROM gen_events WHERE owner = ? AND created_at >= ?",
            (owner, day_start),
        ).fetchone()
    tokens_in = row["tin"] or 0
    tokens_out = row["tout"] or 0
    return {
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": _cost_usd(tokens_in, tokens_out),
    }


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


# ── Live external-data cache (R-701/R-704) ───────────────────────────────────


def live_cache_get(provider: str, query_hash: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT payload_json, fetched_at FROM live_cache WHERE provider = ? AND query_hash = ?",
            (provider, query_hash),
        ).fetchone()
    if row is None:
        return None
    return {"payload": json.loads(row["payload_json"]), "fetched_at": row["fetched_at"]}


_LIVE_CACHE_MAX_DEFAULT = 5000


def _live_cache_max() -> int:
    """Row cap for the public live_cache table (R-701 hardening). Every distinct
    provider+query is a permanent row, so without a bound the table grows forever.
    Optional TRUS_LIVE_CACHE_MAX overrides the default; unparseable or < 1 falls
    back to the default rather than disabling the bound."""
    raw = os.environ.get("TRUS_LIVE_CACHE_MAX", "").strip()
    try:
        v = int(raw) if raw else _LIVE_CACHE_MAX_DEFAULT
    except ValueError:
        return _LIVE_CACHE_MAX_DEFAULT
    return v if v >= 1 else _LIVE_CACHE_MAX_DEFAULT


def live_cache_set(provider: str, query_hash: str, payload_json: str, fetched_at: str) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO live_cache (provider, query_hash, payload_json, fetched_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (provider, query_hash) DO UPDATE SET"
            " payload_json = excluded.payload_json, fetched_at = excluded.fetched_at",
            (provider, query_hash, payload_json, fetched_at),
        )
        # Bound the table on every write (R-701 hardening): one cheap statement —
        # deletes nothing while under the cap (LIMIT 0), prunes the oldest
        # rows-over-cap by fetched_at once exceeded. max(0, …) matters: a negative
        # LIMIT means "no limit" in SQLite, which would wipe the whole table.
        c.execute(
            "DELETE FROM live_cache WHERE rowid IN ("
            " SELECT rowid FROM live_cache ORDER BY fetched_at ASC, rowid ASC"
            " LIMIT max(0, (SELECT COUNT(*) FROM live_cache) - ?))",
            (_live_cache_max(),),
        )


def last_seen_by_user(days: int = 30) -> list[dict]:
    """Per-claimed-user activity (R-1201: "which of the 50 used it yesterday").

    gen_events.owner is the effective owner id for the request that logged it
    (see routes/deps._owner_id) — a user id once claimed, else the anonymous
    session id. INNER JOINing against users means an anonymous sid (which has
    no matching users row) is silently excluded: this view only ever shows
    activity attributable to a named person, by construction of the JOIN.

    R-1202 completion: also rolls up tokens_in/tokens_out/cost_usd over the
    same `days` window, for /api/ops/summary's per-user cost surface — reuses
    this shape rather than a parallel query (same JOIN, same window).
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    cutoff_7d = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    with _conn() as c:
        rows = c.execute(
            "SELECT u.id AS user_id, u.name AS name, MAX(g.created_at) AS last_seen,"
            " COUNT(CASE WHEN g.created_at >= ? THEN 1 END) AS generations_7d,"
            " SUM(COALESCE(g.tokens_in,0)) AS tokens_in,"
            " SUM(COALESCE(g.tokens_out,0)) AS tokens_out"
            " FROM gen_events g JOIN users u ON g.owner = u.id"
            " WHERE g.created_at >= ?"
            " GROUP BY u.id, u.name"
            " ORDER BY last_seen DESC",
            (cutoff_7d, cutoff),
        ).fetchall()
    return [
        {
            "user_id": r["user_id"],
            "name": r["name"],
            "last_seen": r["last_seen"],
            "generations_7d": r["generations_7d"],
            "tokens_in": r["tokens_in"] or 0,
            "tokens_out": r["tokens_out"] or 0,
            "cost_usd": _cost_usd(r["tokens_in"] or 0, r["tokens_out"] or 0),
        }
        for r in rows
    ]


# ── Evolving user profile store (R-801/R-802) ───────────────────────────────

# ≤50 facts/owner — self-curating: an add past the cap prunes the single
# oldest-by-updated_at row rather than refusing the new (presumably more
# recent/relevant) one.
_PROFILE_CAP = 50
_PROFILE_COLS = "id, owner, kind, text, source, created_at, updated_at"


def _profile_from_row(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"],
        "owner": r["owner"],
        "kind": r["kind"],
        "text": r["text"],
        "source": r["source"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


def profile_list(owner: str) -> list[dict]:
    """This owner's profile facts, most-recently-updated first (R-903: WHERE-scoped
    to `owner` — another owner's facts can never appear)."""
    with _conn() as c:
        rows = c.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
            f"SELECT {_PROFILE_COLS} FROM user_profile WHERE owner = ? ORDER BY updated_at DESC",
            (owner,),
        ).fetchall()
    return [_profile_from_row(r) for r in rows]


def profile_add(owner: str, kind: str, text: str, source: str) -> dict:
    """Add a profile fact (R-801/R-802), owner-scoped.

    Dedup: a case-insensitive exact match of `text` within this owner+kind is
    NOT re-added — the existing row is returned untouched (a repeated
    observation isn't a "new" fact, so updated_at is not bumped).

    Cap: ≤50 facts/owner. On the 51st add, the single OLDEST row (by
    updated_at) for this owner is pruned first, so the profile self-curates
    instead of ever refusing a legitimate new fact.
    """
    with _conn() as c:
        dup = c.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
            f"SELECT {_PROFILE_COLS} FROM user_profile"
            " WHERE owner = ? AND kind = ? AND lower(text) = lower(?)",
            (owner, kind, text),
        ).fetchone()
        if dup:
            return _profile_from_row(dup)
        count = c.execute("SELECT COUNT(*) FROM user_profile WHERE owner = ?", (owner,)).fetchone()[
            0
        ]
        if count >= _PROFILE_CAP:
            oldest = c.execute(
                "SELECT id FROM user_profile WHERE owner = ? ORDER BY updated_at ASC LIMIT 1",
                (owner,),
            ).fetchone()
            if oldest:
                c.execute("DELETE FROM user_profile WHERE id = ?", (oldest["id"],))
        pid = str(uuid.uuid4())
        now = _now()
        c.execute(
            "INSERT INTO user_profile (id, owner, kind, text, source, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (pid, owner, kind, text, source, now, now),
        )
        row = c.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
            f"SELECT {_PROFILE_COLS} FROM user_profile WHERE id = ?", (pid,)
        ).fetchone()
    return _profile_from_row(row)


def profile_update(owner: str, profile_id: str, text: str) -> dict | None:
    with _conn() as c:
        cur = c.execute(
            "UPDATE user_profile SET text = ?, updated_at = ? WHERE id = ? AND owner = ?",
            (text, _now(), profile_id, owner),
        )
        if cur.rowcount == 0:
            return None
        row = c.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
            f"SELECT {_PROFILE_COLS} FROM user_profile WHERE id = ?", (profile_id,)
        ).fetchone()
    return _profile_from_row(row)


def profile_delete(owner: str, profile_id: str) -> bool:
    with _conn() as c:
        cur = c.execute("DELETE FROM user_profile WHERE id = ? AND owner = ?", (profile_id, owner))
        return cur.rowcount > 0


def profile_clear(owner: str) -> int:
    with _conn() as c:
        cur = c.execute("DELETE FROM user_profile WHERE owner = ?", (owner,))
        return cur.rowcount


# ── V2 trust spine: automations / approvals / activity ───────────────────────
# Server-side runtime automation — NOT schema.Automation (a client-side module
# rule). Every SELECT/UPDATE/DELETE carries `AND owner = ?` except the two
# scheduler-only calls marked ⚙ (the scheduler is the one trusted cross-owner
# caller; rows pin their owner). ids uuid4, timestamps _now().

_AUTOMATION_COLS = (
    "id, owner, page_id, name, description, action_type, action_json, state_json, "
    "schedule_kind, interval_secs, daily_at, trust_dial, enabled, next_run_at, "
    "last_run_at, last_status, failure_count, created_at, updated_at"
)


def automation_create(
    owner: str,
    *,
    page_id: str | None,
    name: str,
    description: str,
    action_type: str,
    action_json: str,
    schedule_kind: str,
    interval_secs: int | None,
    daily_at: str | None,
    trust_dial: int,
    next_run_at: str | None,
) -> dict:
    """Insert an automation. AUT-3: trust_dial hard-clamped to <= 1 here — an
    orchestrator/ONB proposal can create at 0 or 1, never 2 (only PATCH lifts to 2)."""
    dial = min(max(trust_dial, 0), 1)
    aid = str(uuid.uuid4())
    now = _now()
    with _conn() as c:
        c.execute(
            "INSERT INTO automations (id, owner, page_id, name, description, action_type,"
            " action_json, state_json, schedule_kind, interval_secs, daily_at, trust_dial,"
            " enabled, next_run_at, last_run_at, last_status, failure_count, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, '{}', ?, ?, ?, ?, 1, ?, NULL, NULL, 0, ?, ?)",
            (
                aid,
                owner,
                page_id,
                name,
                description,
                action_type,
                action_json,
                schedule_kind,
                interval_secs,
                daily_at,
                dial,
                next_run_at,
                now,
                now,
            ),
        )
        row = c.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
            f"SELECT {_AUTOMATION_COLS} FROM automations WHERE id = ?", (aid,)
        ).fetchone()
    return dict(row)


def automation_list(owner: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
            f"SELECT {_AUTOMATION_COLS} FROM automations WHERE owner = ? ORDER BY created_at",
            (owner,),
        ).fetchall()
    return [dict(r) for r in rows]


def automation_get(owner: str, aid: str) -> dict | None:
    with _conn() as c:
        row = c.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
            f"SELECT {_AUTOMATION_COLS} FROM automations WHERE id = ? AND owner = ?", (aid, owner)
        ).fetchone()
    return dict(row) if row else None


def automation_patch(
    owner: str, aid: str, *, name=_UNSET, enabled=_UNSET, trust_dial=_UNSET
) -> dict | None:
    """The ONLY trust_dial writer (AUT-3). Column set {name, enabled, trust_dial,
    updated_at} is disjoint from the scheduler's bookkeeping writer below (except
    the harmless updated_at overlap), so neither clobbers the other."""
    sets, params = [], []
    if name is not _UNSET:
        sets.append("name = ?")
        params.append(name)
    if enabled is not _UNSET:
        sets.append("enabled = ?")
        params.append(1 if enabled else 0)
    if trust_dial is not _UNSET:
        sets.append("trust_dial = ?")
        params.append(min(max(trust_dial, 0), 2))
    sets.append("updated_at = ?")
    params.append(_now())
    params += [aid, owner]
    with _conn() as c:
        cur = c.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
            f"UPDATE automations SET {', '.join(sets)} WHERE id = ? AND owner = ?", params
        )
        if cur.rowcount == 0:
            return None
        row = c.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
            f"SELECT {_AUTOMATION_COLS} FROM automations WHERE id = ?", (aid,)
        ).fetchone()
    return dict(row)


def automation_delete(owner: str, aid: str) -> bool:
    """Delete + cascade-expire this automation's pending approvals, journaling one
    'expired' activity row per swept approval (never an orphaned executable
    approval). All in one connection/transaction."""
    now = _now()
    with _conn() as c:
        pend = c.execute(
            "SELECT id, summary FROM approvals"
            " WHERE automation_id = ? AND owner = ? AND status = 'pending'",
            (aid, owner),
        ).fetchall()
        c.execute(
            "UPDATE approvals SET status = 'expired', decided_at = ?"
            " WHERE automation_id = ? AND owner = ? AND status = 'pending'",
            (now, aid, owner),
        )
        for p in pend:
            c.execute(
                "INSERT INTO activity (id, owner, automation_id, approval_id, kind, summary,"
                " detail_json, created_at) VALUES (?, ?, ?, ?, 'expired', ?, NULL, ?)",
                (
                    str(uuid.uuid4()),
                    owner,
                    aid,
                    p["id"],
                    "Expired unanswered: " + p["summary"],
                    now,
                ),
            )
        cur = c.execute("DELETE FROM automations WHERE id = ? AND owner = ?", (aid, owner))
        return cur.rowcount > 0


# ⚙ scheduler-only (cross-owner): the trusted daemon selects due rows across all
# owners; each row pins its own owner for the per-run owner-scoped writes.
def automations_due(now_iso: str, limit: int) -> list[dict]:
    with _conn() as c:
        rows = c.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
            f"SELECT {_AUTOMATION_COLS} FROM automations"
            " WHERE enabled = 1 AND next_run_at IS NOT NULL AND next_run_at <= ?"
            " ORDER BY next_run_at LIMIT ?",
            (now_iso, limit),
        ).fetchall()
    return [dict(r) for r in rows]


# ⚙ scheduler-only CAS claim: the advance of next_run_at IS the claim. Keyed by
# the unique id + the expected next_run_at token, so a second worker (or a
# restart's catch-up) that reads the same due row loses cleanly (rowcount 0).
def automation_claim(aid: str, expected_next_run: str | None, new_next_run: str) -> bool:
    with _conn() as c:
        cur = c.execute(
            "UPDATE automations SET next_run_at = ?, updated_at = ?"
            " WHERE id = ? AND next_run_at = ? AND enabled = 1",
            (new_next_run, _now(), aid, expected_next_run),
        )
        return cur.rowcount == 1


def automation_mark_run(
    owner: str,
    aid: str,
    *,
    last_run_at: str,
    next_run_at: str | None,
    last_status: str,
    failure_count: int,
    state_json=_UNSET,
    enabled=_UNSET,
) -> None:
    """The scheduler's bookkeeping writer — NEVER writes trust_dial. Column set is
    disjoint from PATCH's (AUT-3). `enabled` is written only on quarantine
    auto-disable; `state_json` only when an executor returns new scratch state."""
    sets = [
        "last_run_at = ?",
        "next_run_at = ?",
        "last_status = ?",
        "failure_count = ?",
        "updated_at = ?",
    ]
    params: list = [last_run_at, next_run_at, last_status, failure_count, _now()]
    if state_json is not _UNSET:
        sets.append("state_json = ?")
        params.append(state_json)
    if enabled is not _UNSET:
        sets.append("enabled = ?")
        params.append(1 if enabled else 0)
    params += [aid, owner]
    with _conn() as c:
        c.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
            f"UPDATE automations SET {', '.join(sets)} WHERE id = ? AND owner = ?", params
        )


_APPROVAL_COLS = (
    "id, owner, automation_id, action_type, payload_json, summary, preview_json, status, "
    "expires_at, created_at, decided_at, executed_at"
)


def approval_pending_for(owner: str, automation_id: str, action_type: str) -> dict | None:
    """The single pending approval for this (owner, automation, action_type), if
    any — park uses it to avoid re-journaling a 'held' row every tick."""
    with _conn() as c:
        row = c.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
            f"SELECT {_APPROVAL_COLS} FROM approvals"
            " WHERE owner = ? AND automation_id = ? AND action_type = ? AND status = 'pending'",
            (owner, automation_id, action_type),
        ).fetchone()
    return dict(row) if row else None


def approval_create(
    owner: str,
    automation_id: str,
    action_type: str,
    payload_json: str,
    summary: str,
    preview_json: str | None,
    expires_at: str,
) -> dict:
    """Insert a pending approval, deduped: an existing pending row for the same
    (owner, automation_id, action_type) is returned unchanged (a dial-0 interval
    automation cannot flood the list)."""
    now = _now()
    with _conn() as c:
        dup = c.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
            f"SELECT {_APPROVAL_COLS} FROM approvals"
            " WHERE owner = ? AND automation_id = ? AND action_type = ? AND status = 'pending'",
            (owner, automation_id, action_type),
        ).fetchone()
        if dup:
            return dict(dup)
        aid = str(uuid.uuid4())
        c.execute(
            "INSERT INTO approvals (id, owner, automation_id, action_type, payload_json, summary,"
            " preview_json, status, expires_at, created_at, decided_at, executed_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, NULL, NULL)",
            (
                aid,
                owner,
                automation_id,
                action_type,
                payload_json,
                summary,
                preview_json,
                expires_at,
                now,
            ),
        )
        row = c.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
            f"SELECT {_APPROVAL_COLS} FROM approvals WHERE id = ?", (aid,)
        ).fetchone()
    return dict(row)


def approval_get(owner: str, approval_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
            f"SELECT {_APPROVAL_COLS} FROM approvals WHERE id = ? AND owner = ?",
            (approval_id, owner),
        ).fetchone()
    return dict(row) if row else None


def approval_list_pending(owner: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
            f"SELECT {_APPROVAL_COLS} FROM approvals"
            " WHERE owner = ? AND status = 'pending' ORDER BY created_at DESC",
            (owner,),
        ).fetchall()
    return [dict(r) for r in rows]


def approval_pending_count(owner: str) -> int:
    with _conn() as c:
        row = c.execute(
            "SELECT COUNT(*) AS n FROM approvals WHERE owner = ? AND status = 'pending'",
            (owner,),
        ).fetchone()
    return int(row["n"])


def approval_claim(owner: str, approval_id: str, new_status: str, now: str) -> dict | None:
    """The CAS gate into execution: flip a pending, non-expired approval to
    new_status. `AND expires_at > ?` closes the approve-past-expiry race even if
    no sweep ran. rowcount 0 → None (caller re-reads to tell 404 from 409)."""
    with _conn() as c:
        cur = c.execute(
            "UPDATE approvals SET status = ?, decided_at = ?"
            " WHERE id = ? AND owner = ? AND status = 'pending' AND expires_at > ?",
            (new_status, now, approval_id, owner, now),
        )
        if cur.rowcount == 0:
            return None
        row = c.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
            f"SELECT {_APPROVAL_COLS} FROM approvals WHERE id = ?", (approval_id,)
        ).fetchone()
    return dict(row)


def approval_set_failed(owner: str, approval_id: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE approvals SET status = 'failed' WHERE id = ? AND owner = ?",
            (approval_id, owner),
        )


def approval_set_executed(owner: str, approval_id: str, executed_at: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE approvals SET executed_at = ? WHERE id = ? AND owner = ?",
            (executed_at, approval_id, owner),
        )


def approval_sweep_expired(owner: str, now: str) -> list[dict]:
    """Flip this owner's overdue pendings to 'expired'; return the swept rows so
    the caller journals them."""
    with _conn() as c:
        rows = c.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
            f"SELECT {_APPROVAL_COLS} FROM approvals"
            " WHERE owner = ? AND status = 'pending' AND expires_at <= ?",
            (owner, now),
        ).fetchall()
        swept = [dict(r) for r in rows]
        if swept:
            c.execute(
                "UPDATE approvals SET status = 'expired', decided_at = ?"
                " WHERE owner = ? AND status = 'pending' AND expires_at <= ?",
                (now, owner, now),
            )
    return swept


def approval_sweep_expired_global(now: str) -> list[dict]:
    """⚙ scheduler-only: the per-tick cross-owner expiry pass. Returns swept rows
    (each pinning its owner) so the runtime journals one 'expired' row apiece."""
    with _conn() as c:
        rows = c.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
            f"SELECT {_APPROVAL_COLS} FROM approvals WHERE status = 'pending' AND expires_at <= ?",
            (now,),
        ).fetchall()
        swept = [dict(r) for r in rows]
        if swept:
            c.execute(
                "UPDATE approvals SET status = 'expired', decided_at = ?"
                " WHERE status = 'pending' AND expires_at <= ?",
                (now, now),
            )
    return swept


_ACTIVITY_COLS = "id, owner, automation_id, approval_id, kind, summary, detail_json, created_at"


def _activity_max() -> int:
    return int(os.environ.get("TRUS_ACTIVITY_MAX", "2000"))


def activity_add(
    owner: str,
    kind: str,
    summary: str,
    *,
    automation_id: str | None = None,
    approval_id: str | None = None,
    detail_json: str | None = None,
) -> dict:
    """Append an activity row, then prune this owner's oldest rows past
    TRUS_ACTIVITY_MAX (the live_cache_set LIMIT max(0, COUNT-cap) pattern — owner
    B's rows are untouched)."""
    rid = str(uuid.uuid4())
    now = _now()
    with _conn() as c:
        c.execute(
            "INSERT INTO activity (id, owner, automation_id, approval_id, kind, summary,"
            " detail_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (rid, owner, automation_id, approval_id, kind, summary, detail_json, now),
        )
        c.execute(
            "DELETE FROM activity WHERE owner = ? AND id IN ("
            " SELECT id FROM activity WHERE owner = ? ORDER BY created_at ASC, rowid ASC"
            " LIMIT max(0, (SELECT COUNT(*) FROM activity WHERE owner = ?) - ?))",
            (owner, owner, owner, _activity_max()),
        )
        row = c.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
            f"SELECT {_ACTIVITY_COLS} FROM activity WHERE id = ?", (rid,)
        ).fetchone()
    return dict(row)


def activity_list(owner: str, limit: int = 50, before: str | None = None) -> list[dict]:
    """Newest first, keyset pagination on created_at (pass the oldest row's
    created_at as `before` to page back)."""
    with _conn() as c:
        if before:
            rows = c.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
                f"SELECT {_ACTIVITY_COLS} FROM activity WHERE owner = ? AND created_at < ?"
                " ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (owner, before, limit),
            ).fetchall()
        else:
            rows = c.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
                f"SELECT {_ACTIVITY_COLS} FROM activity WHERE owner = ?"
                " ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (owner, limit),
            ).fetchall()
    return [dict(r) for r in rows]


def recent_user_messages(owner: str, since_iso: str, limit: int = 50) -> list[str]:
    """This owner's recent user-role message texts since `since_iso` (newest
    first) — the `learn` executor's mining source. Owner-scoped (R-903)."""
    with _conn() as c:
        rows = c.execute(
            "SELECT text FROM messages WHERE session_id = ? AND role = 'user'"
            " AND created_at >= ? ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (owner, since_iso, limit),
        ).fetchall()
    return [r["text"] for r in rows]


# ---------------------------------------------------------------------------
# Share links (SHARE-1..3)
# ---------------------------------------------------------------------------


def share_create(owner: str, page_id: str) -> dict | None:
    """Create-or-rotate: revokes any active link for this page, mints a new one,
    all in ONE transaction (the partial unique index never trips mid-rotate).
    Returns None when the page isn't this owner's — indistinguishable from
    nonexistent, matching the _require_own_parent stance."""
    with _conn() as c:
        if not c.execute(
            "SELECT 1 FROM pages WHERE id = ? AND session_id = ?", (page_id, owner)
        ).fetchone():
            return None
        now = _now()
        c.execute(
            "UPDATE share_links SET revoked_at = ? WHERE page_id = ? AND owner = ? AND revoked_at IS NULL",
            (now, page_id, owner),
        )
        token = secrets.token_urlsafe(32)
        c.execute(
            "INSERT INTO share_links (id, token, owner, page_id, created_at) VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), token, owner, page_id, now),
        )
    return {"token": token, "created_at": now}


def share_status(owner: str, page_id: str) -> dict | None:
    with _conn() as c:
        r = c.execute(
            "SELECT token, created_at FROM share_links"
            " WHERE page_id = ? AND owner = ? AND revoked_at IS NULL",
            (page_id, owner),
        ).fetchone()
    return dict(r) if r else None


def share_revoke(owner: str, page_id: str) -> bool:
    with _conn() as c:
        cur = c.execute(
            "UPDATE share_links SET revoked_at = ? WHERE page_id = ? AND owner = ? AND revoked_at IS NULL",
            (_now(), page_id, owner),
        )
        return cur.rowcount > 0


def share_resolve(token: str) -> dict | None:
    """Public-path lookup — the ONLY function that reads a token; its ONLY
    caller is GET /api/share/{token}. Joins pages (name/icon in one query) and
    LEFT JOINs users so a REVOKED owner's shares die with them (R-905 — the
    public path bypasses _owner_id's per-request revocation check, so it must
    re-check here). Anon (dev) owners have no users row → LEFT JOIN passes.
    None for unknown token, revoked link, cascade-deleted page, or revoked
    owner — one indistinguishable outcome."""
    with _conn() as c:
        r = c.execute(
            "SELECT s.owner, s.page_id, p.name, p.icon, u.revoked_at AS user_revoked"
            " FROM share_links s JOIN pages p ON p.id = s.page_id"
            " LEFT JOIN users u ON u.id = s.owner"
            " WHERE s.token = ? AND s.revoked_at IS NULL",
            (token,),
        ).fetchone()
    if r is None or r["user_revoked"]:
        return None
    return {"owner": r["owner"], "page_id": r["page_id"], "name": r["name"], "icon": r["icon"]}
