# Backups & restore (R-1106)

Trus stores everything in one SQLite file (`TRUS_DB_PATH`, prod: `/data/trus.db`).
`python -m src.backup` is the zero-dependency backup/restore tool — it checkpoints
the WAL then uses SQLite's online-backup API, so it is safe to run **while the app
is serving** (a raw `cp` of a live WAL database is not: the main file and `-wal`
can tear).

## Commands

```bash
python -m src.backup backup           # snapshot → $TRUS_BACKUP_DIR/trus-YYYYMMDDTHHMMSSZ.db, then prune
python -m src.backup list             # name, size, age of every backup
python -m src.backup restore <file>   # swap a backup in (see "Restoring" — stop the app first)
```

## Environment

| Var | Default | Meaning |
|---|---|---|
| `TRUS_BACKUP_DIR` | `/data/backups` | Where snapshots land. On Fly this sits on the same `/data` volume as the DB — see the caveat below. |
| `TRUS_BACKUP_KEEP` | `7` | Retention: `backup` keeps the newest N `trus-*.db` snapshots and prints what it pruned. `pre-restore-*.db` safety snapshots are never auto-pruned. |
| `TRUS_DB_PATH` | `/data/trus.db` (prod image) | The live database being backed up / restored. |

## Scheduling (RPO ≤ 24h)

The alpha's recovery point objective is **≤ 24 hours of data loss** — one backup
per day meets it. Keep the default retention (7) → a week of daily restore points.

**Cron (any Docker host / VM):**

```cron
# daily at 03:17 UTC, as the app user, inside the app environment
17 3 * * * cd /app && python -m src.backup backup >> /data/backups/backup.log 2>&1
```

**Fly.io** has no in-machine cron; two working options:

1. *Scheduled machine* (runs in the same app, mounts the same volume):

   ```bash
   fly machine run . --schedule daily --region <same-region-as-volume> \
     --volume trus_data:/data --command "python -m src.backup backup"
   ```

2. *External scheduler* (GitHub Actions cron, or your laptop's cron) driving:

   ```bash
   fly ssh console -C "python -m src.backup backup"
   ```

**Caveat — same-volume backups:** `/data/backups` survives deploys and app
crashes, but **not the loss of the volume itself**. Periodically pull a copy
off-host:

```bash
fly ssh sftp get /data/backups/trus-<latest>.db ./offsite/
```

## Restoring

Restore is an **offline** operation — stop the app first so nothing writes to the
DB mid-swap and the restarted app reopens the restored file:

On a VM / plain Docker host: stop the service, run `restore`, start it again.

On Fly (the app machine must be stopped, so run the restore from a one-off
machine attached to the same volume):

```bash
fly machine list                         # find the app machine id
fly machine stop <machine-id>
fly machine run . --region <volume-region> --volume trus_data:/data \
  --command "python -m src.backup list"  # pick a snapshot, then:
fly machine run . --region <volume-region> --volume trus_data:/data \
  --command "python -m src.backup restore /data/backups/trus-20260705T031700Z.db"
# → prints the pre-restore safety snapshot path + what was restored
fly machine start <machine-id>           # bring the app back
```

What `restore` does, in order:

1. **Validates** the file is a readable, intact SQLite DB (`integrity_check`) —
   a bad file is refused with exit 1 and nothing is touched.
2. **Safety-snapshots the current DB** to `$TRUS_BACKUP_DIR/pre-restore-<stamp>.db`
   — a bad restore is itself recoverable (restore the pre-restore snapshot).
3. Removes the live DB **and its `-wal`/`-shm` sidecars** so a stale WAL can't
   shadow the restored data, then copies the backup into place.

Exit codes are honest: `0` success, nonzero with a message on stderr otherwise.

## Pre-alpha checklist (R-1106 AC — do this BEFORE inviting anyone)

Exercise a full restore once, end to end, on the real deployment:

- [ ] `python -m src.backup backup` on the deployed backend → file appears in `list`.
- [ ] Create a marker (e.g. a throwaway module) in the app, take backup B.
- [ ] Change something (archive the marker), then `restore` backup B.
- [ ] Restart the app → the marker is back; the pre-restore snapshot exists.
- [ ] Confirm the daily schedule actually fired once (check `list` the next day).
- [ ] Pull one backup off-host (`fly ssh sftp get …`) and open it locally
      (`sqlite3 file 'PRAGMA integrity_check;'` → `ok`).

If any step surprises you, fix it now — a backup you've never restored is a hope,
not a recovery story.
