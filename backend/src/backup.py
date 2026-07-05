"""SQLite backup + restore for the hosted alpha (R-1106). Zero-dep stdlib CLI.

    python -m src.backup backup            # snapshot → $TRUS_BACKUP_DIR, prune to keep-N
    python -m src.backup list              # show existing backups (name, size, age)
    python -m src.backup restore <file>    # swap a backup in (safety-snapshots current first)

Snapshots use `PRAGMA wal_checkpoint(TRUNCATE)` + the sqlite3 online-backup API
(`Connection.backup`) — the safe way to copy an in-use database. A raw file copy
of a live WAL database can tear (main file and -wal captured at different moments).
Runbook: deploy/BACKUP.md. Env: TRUS_BACKUP_DIR (default /data/backups),
TRUS_BACKUP_KEEP (default 7).
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from src import db

DEFAULT_BACKUP_DIR = "/data/backups"
DEFAULT_KEEP = 7


class BackupError(RuntimeError):
    """Operator-facing failure; the CLI prints it and exits nonzero."""


def _backup_dir() -> Path:
    return Path(os.environ.get("TRUS_BACKUP_DIR") or DEFAULT_BACKUP_DIR)


def _keep_n() -> int:
    try:
        n = int(os.environ.get("TRUS_BACKUP_KEEP", ""))
    except ValueError:
        return DEFAULT_KEEP
    return n if n >= 1 else DEFAULT_KEEP


def _stamp(now: datetime | None) -> str:
    """UTC timestamp for filenames. `now` is injectable so tests are deterministic;
    the CLI path passes None → system clock."""
    moment = now or datetime.now(timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _snapshot(src: Path, dest: Path) -> None:
    """Checkpoint src's WAL into the main file, then write a consistent copy to
    dest via the online-backup API (safe while other connections are live)."""
    src_conn = sqlite3.connect(src)
    try:
        src_conn.execute("PRAGMA busy_timeout = 5000")
        # Fold pending WAL frames into the main file first; on a rollback-journal
        # DB this is a harmless no-op. The backup API would capture WAL content
        # anyway — checkpointing keeps the snapshot self-contained and sidecar-free.
        src_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        dest_conn = sqlite3.connect(dest)
        try:
            src_conn.backup(dest_conn)
        finally:
            dest_conn.close()
    finally:
        src_conn.close()


def _validate_sqlite(path: Path) -> None:
    """Refuse anything that isn't a readable, intact SQLite database."""
    if not path.is_file():
        raise BackupError(f"not a file: {path}")
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            conn.execute("PRAGMA schema_version").fetchone()
            verdict = conn.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise BackupError(f"not a readable SQLite database: {path} ({exc})") from exc
    if str(verdict).lower() != "ok":
        raise BackupError(f"integrity check failed for {path}: {verdict}")


def create_backup(now: datetime | None = None) -> Path:
    """Checkpoint + snapshot the live DB to <TRUS_BACKUP_DIR>/trus-<stamp>.db."""
    src = db._db_path()
    if not src.is_file():
        raise BackupError(f"database not found: {src}")
    backup_dir = _backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = backup_dir / f"trus-{_stamp(now)}.db"
    _snapshot(src, dest)
    return dest


def prune(keep: int | None = None) -> list[Path]:
    """Delete all but the newest `keep` backups; returns what was pruned.

    Only `trus-*.db` snapshots are candidates — `pre-restore-*.db` safety
    snapshots are never auto-pruned. Filenames embed UTC timestamps, so
    lexicographic order == chronological order.
    """
    n = _keep_n() if keep is None else keep
    backups = sorted(_backup_dir().glob("trus-*.db"))
    doomed = backups[:-n] if n < len(backups) else []
    for path in doomed:
        path.unlink()
    return doomed


def restore(backup_file: Path, now: datetime | None = None) -> Path | None:
    """Replace the live DB with `backup_file`. Returns the safety snapshot taken
    of the pre-restore state (None if there was no live DB to snapshot).

    Order matters: validate first (a bad file must leave everything untouched),
    then safety-snapshot the current DB (a bad restore is itself recoverable),
    then remove the live DB *and its -wal/-shm sidecars* (a stale WAL must not
    shadow the restored data), then copy the backup into place — a plain file
    copy is safe here because the backup file is cold. Run this with the app
    stopped; see deploy/BACKUP.md.
    """
    backup_file = Path(backup_file)
    _validate_sqlite(backup_file)
    live = db._db_path()
    if live.exists() and backup_file.resolve() == live.resolve():
        raise BackupError("refusing to restore the live database onto itself")

    safety: Path | None = None
    if live.is_file():
        backup_dir = _backup_dir()
        backup_dir.mkdir(parents=True, exist_ok=True)
        safety = backup_dir / f"pre-restore-{_stamp(now)}.db"
        _snapshot(live, safety)

    for suffix in ("", "-wal", "-shm"):
        Path(str(live) + suffix).unlink(missing_ok=True)
    shutil.copy2(backup_file, live)
    return safety


def _age(seconds: float) -> str:
    seconds = max(0.0, seconds)
    if seconds >= 86400:
        return f"{seconds / 86400:.1f}d"
    if seconds >= 3600:
        return f"{seconds / 3600:.1f}h"
    return f"{seconds / 60:.0f}m"


def _cmd_backup() -> None:
    dest = create_backup()
    print(f"backup written: {dest} ({dest.stat().st_size} bytes)")
    for path in prune():
        print(f"pruned (keeping newest {_keep_n()}): {path.name}")


def _cmd_list() -> None:
    backup_dir = _backup_dir()
    entries = sorted(backup_dir.glob("*.db"), reverse=True)
    if not entries:
        print(f"no backups in {backup_dir}")
        return
    now = time.time()
    for path in entries:
        stat = path.stat()
        print(f"{path.name}  {stat.st_size} bytes  {_age(now - stat.st_mtime)} old")


def _cmd_restore(file: str) -> None:
    safety = restore(Path(file))
    if safety is not None:
        print(f"safety snapshot of pre-restore state: {safety}")
    print(f"restored {Path(file).name} -> {db._db_path()}")
    print("restart the app so it reopens the database file")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.backup",
        description="SQLite backup/restore for Trus (R-1106). See deploy/BACKUP.md.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("backup", help="snapshot the live DB to TRUS_BACKUP_DIR, prune to keep-N")
    sub.add_parser("list", help="list existing backups (name, size, age)")
    p_restore = sub.add_parser("restore", help="swap a backup in (safety-snapshots current first)")
    p_restore.add_argument("file", help="backup file to restore from")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "backup":
            _cmd_backup()
        elif args.cmd == "restore":
            _cmd_restore(args.file)
        else:
            _cmd_list()
    except BackupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
