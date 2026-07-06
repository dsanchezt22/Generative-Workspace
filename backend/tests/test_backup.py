"""R-1106: SQLite backup + restore CLI (python -m src.backup).

Every test runs against the conftest-isolated tmp TRUS_DB_PATH plus a tmp
TRUS_BACKUP_DIR — never the real database. Timestamps are injected (`now=`)
wherever a test needs a deterministic filename.
"""

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from src import backup, db

T0 = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 7, 5, 13, 0, 0, tzinfo=timezone.utc)
T2 = datetime(2026, 7, 5, 14, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def backup_dir(tmp_path, monkeypatch) -> Path:
    d = tmp_path / "backups"
    monkeypatch.setenv("TRUS_BACKUP_DIR", str(d))
    return d


def _user_names(path: Path) -> list[str]:
    """Read the users table straight from an arbitrary SQLite file."""
    conn = sqlite3.connect(path)
    try:
        return [r[0] for r in conn.execute("SELECT name FROM users ORDER BY name")]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# backup
# ---------------------------------------------------------------------------


def test_backup_creates_timestamped_valid_copy(backup_dir):
    db.create_user("Ada Backup")
    dest = backup.create_backup(now=T0)
    assert dest == backup_dir / "trus-20260705T120000Z.db"
    assert dest.is_file()
    # The copy opens as a real SQLite DB and carries the seeded row.
    assert "Ada Backup" in _user_names(dest)
    conn = sqlite3.connect(dest)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()


def test_backup_captures_pending_wal_writes(backup_dir):
    db.init_db()
    live = db._db_path()
    # Write a row in WAL mode and KEEP the connection open: closing the last
    # connection would auto-checkpoint, which is exactly what we must not rely on.
    writer = sqlite3.connect(live)
    try:
        writer.execute("PRAGMA journal_mode = WAL")
        writer.execute(
            "INSERT INTO users (id, name, invite_token, created_at)"
            " VALUES ('u-wal', 'Wal Row', 'tok-wal', '2026-07-05T00:00:00+00:00')"
        )
        writer.commit()
        wal = Path(str(live) + "-wal")
        assert wal.is_file() and wal.stat().st_size > 0  # the row lives in the WAL
        dest = backup.create_backup(now=T0)
        assert "Wal Row" in _user_names(dest)
    finally:
        writer.close()


def test_backup_missing_db_errors(backup_dir, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "nope.db"))
    with pytest.raises(backup.BackupError):
        backup.create_backup(now=T0)
    assert backup.main(["backup"]) == 1
    assert "error" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# retention
# ---------------------------------------------------------------------------


def test_retention_prunes_oldest_keeps_newest(backup_dir):
    db.create_user("Keeper")
    for t in (T0, T1, T2):
        backup.create_backup(now=t)
    pruned = backup.prune(keep=2)
    assert [p.name for p in pruned] == ["trus-20260705T120000Z.db"]
    remaining = sorted(p.name for p in backup_dir.glob("trus-*.db"))
    assert remaining == ["trus-20260705T130000Z.db", "trus-20260705T140000Z.db"]


def test_retention_env_default_and_cli_logs_pruned(backup_dir, monkeypatch, capsys):
    db.create_user("Keeper")
    monkeypatch.setenv("TRUS_BACKUP_KEEP", "1")
    backup.create_backup(now=T0)
    backup.create_backup(now=T1)
    assert backup.main(["backup"]) == 0
    out = capsys.readouterr().out
    assert "pruned" in out
    # keep=1 → only the newest (the CLI's real-clock backup) survives.
    assert len(list(backup_dir.glob("trus-*.db"))) == 1
    assert not (backup_dir / "trus-20260705T120000Z.db").exists()


def test_retention_keep_zero_prunes_all(backup_dir):
    """keep=0 must prune everything, not no-op on the [:-0] == [:0] slice bug."""
    db.create_user("Keeper")
    backup.create_backup(now=T0)
    backup.create_backup(now=T1)
    pruned = backup.prune(keep=0)
    assert len(pruned) == 2
    assert list(backup_dir.glob("trus-*.db")) == []


def test_retention_ignores_pre_restore_snapshots(backup_dir):
    db.create_user("Keeper")
    backup.create_backup(now=T0)
    safety = backup_dir / "pre-restore-20260705T110000Z.db"
    safety.write_bytes((backup_dir / "trus-20260705T120000Z.db").read_bytes())
    assert backup.prune(keep=1) == []  # the safety snapshot is not a prune candidate
    assert safety.is_file()


# ---------------------------------------------------------------------------
# restore
# ---------------------------------------------------------------------------


def test_restore_swaps_db_and_keeps_safety_snapshot(backup_dir):
    db.create_user("Backup Era")
    snap = backup.create_backup(now=T0)
    db.create_user("Current Era")  # only in the live db, not in the backup

    safety = backup.restore(snap, now=T1)

    live = db._db_path()
    assert _user_names(live) == ["Backup Era"]  # backup's row; "Current Era" gone
    assert safety == backup_dir / "pre-restore-20260705T130000Z.db"
    assert safety is not None and safety.is_file()
    # A bad restore is itself recoverable: the pre-restore state is intact.
    assert _user_names(safety) == ["Backup Era", "Current Era"]


def test_restore_clears_stale_wal_sidecars(backup_dir):
    db.create_user("Backup Era")
    snap = backup.create_backup(now=T0)
    live = db._db_path()
    # Stale sidecars next to the live db must not shadow the restored data.
    Path(str(live) + "-wal").write_bytes(b"stale wal garbage")
    Path(str(live) + "-shm").write_bytes(b"stale shm garbage")

    backup.restore(snap, now=T1)

    assert not Path(str(live) + "-wal").exists()
    assert not Path(str(live) + "-shm").exists()
    assert _user_names(live) == ["Backup Era"]


def test_restore_swap_is_atomic_via_os_replace(backup_dir, monkeypatch):
    """The swap must be crash-safe: copy to a temp in the live dir, then os.replace
    (atomic on the same fs). If os.replace never runs, the live db must be intact."""
    db.create_user("Backup Era")
    snap = backup.create_backup(now=T0)
    db.create_user("Current Era")
    live = db._db_path()
    before = live.read_bytes()

    calls: list[tuple[str, str]] = []

    def _boom(src, dst, *a, **k):
        calls.append((str(src), str(dst)))
        raise OSError("simulated crash before replace")

    monkeypatch.setattr(os, "replace", _boom)
    with pytest.raises(OSError):
        backup.restore(snap, now=T1)

    assert calls and calls[0][1] == str(live)  # the swap targeted the live path via os.replace
    assert live.read_bytes() == before  # crash before replace → live db untouched
    assert not list(live.parent.glob(f"{live.name}.restore-*"))  # temp cleaned up


def test_restore_refuses_non_sqlite_file(backup_dir, tmp_path, capsys):
    db.create_user("Untouched")
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"this is not a sqlite database at all, honest")

    rc = backup.main(["restore", str(junk)])

    assert rc == 1
    assert "error" in capsys.readouterr().err
    assert _user_names(db._db_path()) == ["Untouched"]  # live db untouched
    assert list(backup_dir.glob("pre-restore-*.db")) == []  # refused BEFORE snapshotting


def test_restore_aborts_when_db_is_in_use(backup_dir, capsys):
    """Final Stage-4 review: unlinking sidecars + os.replace under a RUNNING app
    risks silent loss/corruption — restore must refuse while another connection
    holds a write lock, nonzero exit, live db untouched, no safety snapshot."""
    db.create_user("Backup Era")
    snap = backup.create_backup(now=T0)
    db.create_user("Current Era")
    live = db._db_path()

    holder = sqlite3.connect(live)
    try:
        holder.execute("BEGIN IMMEDIATE")  # a running app mid-write
        with pytest.raises(backup.BackupError, match="in use"):
            backup.restore(snap, now=T1)
        rc = backup.main(["restore", str(snap)])  # the CLI path exits nonzero too
        assert rc == 1
        assert "stop the app" in capsys.readouterr().err
    finally:
        holder.rollback()
        holder.close()

    assert _user_names(live) == ["Backup Era", "Current Era"]  # live db untouched
    assert list(backup_dir.glob("pre-restore-*.db")) == []  # aborted BEFORE snapshotting


def test_restore_succeeds_after_the_lock_is_released(backup_dir):
    """The in-use guard must not leave its own lock behind — an idle db restores."""
    db.create_user("Backup Era")
    snap = backup.create_backup(now=T0)
    holder = sqlite3.connect(db._db_path())
    holder.execute("BEGIN IMMEDIATE")
    holder.rollback()
    holder.close()  # app stopped

    assert backup.restore(snap, now=T1) is not None
    assert _user_names(db._db_path()) == ["Backup Era"]


def test_restore_refuses_missing_file(backup_dir, tmp_path):
    with pytest.raises(backup.BackupError):
        backup.restore(tmp_path / "does-not-exist.db")


def test_restore_refuses_live_db_onto_itself(backup_dir):
    db.create_user("Self")
    with pytest.raises(backup.BackupError, match="itself"):
        backup.restore(db._db_path())


def test_restore_refuses_zero_byte_file(backup_dir, tmp_path, capsys):
    """A 0-byte file IS a valid *empty* SQLite DB (schema_version 0, integrity ok).
    Restoring it must NOT wipe the live db — refuse, nonzero exit, db byte-identical."""
    db.create_user("Untouched")
    live = db._db_path()
    before = live.read_bytes()
    empty = tmp_path / "zero.db"
    empty.touch()
    assert empty.stat().st_size == 0

    rc = backup.main(["restore", str(empty)])

    assert rc == 1
    assert "error" in capsys.readouterr().err
    assert live.read_bytes() == before  # byte-identical: not wiped, not touched
    assert list(backup_dir.glob("pre-restore-*.db")) == []  # refused BEFORE snapshotting


def test_restore_refuses_valid_sqlite_that_isnt_trus(backup_dir, tmp_path):
    """A perfectly valid SQLite DB with a foreign schema is not a Trus backup —
    restoring it would swap in a structurally-wrong db. Refuse it."""
    db.create_user("Untouched")
    live = db._db_path()
    before = live.read_bytes()
    foreign = tmp_path / "other.db"
    conn = sqlite3.connect(foreign)
    conn.execute("CREATE TABLE widgets (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

    with pytest.raises(backup.BackupError, match="Trus"):
        backup.restore(foreign)
    assert live.read_bytes() == before  # untouched


# ---------------------------------------------------------------------------
# list + CLI surface
# ---------------------------------------------------------------------------


def test_list_shows_backups_name_size_age(backup_dir, capsys):
    db.create_user("Lister")
    backup.create_backup(now=T0)
    backup.create_backup(now=T1)
    assert backup.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "trus-20260705T120000Z.db" in out
    assert "trus-20260705T130000Z.db" in out


def test_list_empty_dir_is_honest(backup_dir, capsys):
    assert backup.main(["list"]) == 0
    assert "no backups" in capsys.readouterr().out.lower()


def test_cli_backup_uses_system_clock_and_prints_path(backup_dir, capsys):
    db.create_user("Clock")
    assert backup.main(["backup"]) == 0
    out = capsys.readouterr().out
    files = list(backup_dir.glob("trus-*.db"))
    assert len(files) == 1
    assert files[0].name in out
    # Real-clock filename still matches the trus-YYYYMMDDTHHMMSSZ.db shape.
    import re

    assert re.fullmatch(r"trus-\d{8}T\d{6}Z\.db", files[0].name)


def test_cli_restore_prints_what_it_did(backup_dir, capsys):
    db.create_user("Backup Era")
    snap = backup.create_backup(now=T0)
    db.create_user("Current Era")
    assert backup.main(["restore", str(snap)]) == 0
    out = capsys.readouterr().out
    assert "pre-restore-" in out  # names the safety snapshot
    assert snap.name in out  # names what was restored


def test_cli_requires_a_subcommand():
    with pytest.raises(SystemExit):
        backup.main([])
