# Pre-alpha preflight checklist (R-906)

Run through this **after the backend + frontend are deployed** and **before any
invite link goes out**. It's the "did you actually do it" companion to
`deploy/README.md` (the "how"). Each item names the exact command to check it.

Replace `<backend>` with your Fly app's public URL (e.g. `https://trus-backend.fly.dev`)
and `<app>` with your Fly app name throughout.

## 1. Secrets set

```bash
fly secrets list -a <app>
```

- [ ] `SESSION_SECRET` set to a real value (NOT the `.env.example` default —
      the app refuses to boot in prod if it is; if boot succeeds, this is
      already satisfied).
- [ ] `TRUS_OPS_TOKEN` set (needed for step 6 below; unset = permanently 401).
- [ ] `GEMINI_API_KEY` set — **or** `TRUS_LLM_BASE_URL` + `TRUS_LLM_MODEL`
      point at a working OpenAI-compatible endpoint. Confirm which is active:
      ```bash
      curl -s https://<backend>/api/llm/status
      ```
      (In prod this omits `base_url`; you're checking `provider`/`model` are
      what you expect, not "stub".)
- [ ] Voice/vision/embeddings keys set **if those features are enabled**
      (`TRUS_STT_API_KEY`, `TRUS_VISION_API_KEY`, `TRUS_EMBED_API_KEY`) — all
      optional, skip if you're not using them for the alpha.

## 2. `/data` volume mounted + writable as the container uid

The Fly-volume-ownership gotcha (`deploy/README.md` §2): a freshly attached
volume commonly reverts `/data` to `root:root`, shadowing the image's `chown`
to uid 1000. `fly ssh console` typically opens a root shell (separate from the
image's `USER trus`), so a plain `touch` there would succeed via root even if
uid 1000 (the uid the app actually runs as) couldn't write — test as that uid
specifically:

```bash
fly ssh console -C "su trus -c 'touch /data/.write-test && rm /data/.write-test && echo OK'"
```

- [ ] Prints `OK`. If not: `fly ssh console -C "chown -R 1000:1000 /data"`, then
      re-run the check. (If your console session is already uid 1000 rather
      than root, drop the `su trus -c` wrapper and run the `touch`/`rm` directly.)
- [ ] **Exactly ONE machine is running**: `fly scale count 1`, then verify
      `fly scale show` / `fly machines list` reports 1. Fly's HA default of 2
      is split-brain here: SQLite lives on one volume (a 2nd machine gets its
      own empty volume → divergent databases) and the rate limiter is
      in-process (each machine enforces its own copy → every per-owner limit
      silently doubled). Multi-instance is a Stage-5 concern
      (`deploy/README.md` §2).

## 3. WAL active

WAL mode is turned on automatically by the app on every DB connection — this
step just confirms it took (it should always pass; if it doesn't, something is
wrong with the DB file/mount, not the setting). The image has no `sqlite3` CLI
(only Python's stdlib `sqlite3` module), so check via Python:

```bash
fly ssh console -C "python3 -c \"import sqlite3; print(sqlite3.connect('/data/trus.db').execute('PRAGMA journal_mode').fetchone()[0])\""
```

- [ ] Prints `wal`.

## 4. Backups scheduled + one restore drilled

Full drill: `deploy/BACKUP.md` §"Pre-alpha checklist" — do not skip this, a
backup you've never restored is a hope, not a recovery story.

- [ ] A daily backup schedule exists (Fly scheduled machine or an external cron
      hitting `fly ssh console -C "python -m src.backup backup"`) — RPO ≤ 24h.
- [ ] `python -m src.backup backup` run once manually and confirmed in `list`:
      ```bash
      fly ssh console -C "python -m src.backup list"
      ```
- [ ] **One full restore drilled end-to-end** on the real deployment (create a
      marker → backup → change something → restore → restart → marker is
      back; see `deploy/BACKUP.md` for the exact steps).
- [ ] At least one backup pulled off-host and its integrity confirmed:
      ```bash
      fly ssh sftp get /data/backups/trus-<latest>.db ./offsite/
      sqlite3 ./offsite/trus-<latest>.db 'PRAGMA integrity_check;'   # → ok
      ```

## 5. CORS / `TRUS_PUBLIC_URL` correct

All three must match exactly (scheme + host, no trailing slash):

- [ ] Backend `TRUS_CORS_ORIGINS` = your Vercel origin(s).
- [ ] Backend `TRUS_PUBLIC_URL` = the same Vercel origin (invite links build
      from this).
- [ ] Frontend (Vercel) `NEXT_PUBLIC_API_BASE` = the Fly backend origin.
- [ ] `TRUS_COOKIE_SECURE=1` is in effect (baked into the image — confirm you
      didn't override it): without it the cross-origin session cookie is
      silently dropped by the browser.

Quick check — an anonymous request must be refused, and CORS must reflect your
origin:

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://<backend>/api/modules   # → 401
curl -s -I -H "Origin: https://<your-vercel-domain>" https://<backend>/api/health \
  | grep -i access-control-allow-origin                                  # → your origin
```

## 6. Health + ops summary reachable

```bash
curl -s https://<backend>/api/health                              # → {"status":"ok"}
curl -s "https://<backend>/api/ops/summary?token=$TRUS_OPS_TOKEN"  # → stats JSON, not 401
```

- [ ] Both succeed.

## 7. Cost cap + rate limits set to sane values

Defaults (30 generations / 300s per owner, no daily $ cap) are fine for a small
alpha as-is — this step is a **conscious decision**, not necessarily a change.

- [ ] `TRUS_GEN_RATE_MAX` / `TRUS_GEN_RATE_WINDOW` reviewed — default 30/300s
      is reasonable for ~50 students; tighten if you're worried about cost.
- [ ] Decide on `TRUS_DAILY_COST_CAP_USD` + `TRUS_TOKEN_COST_IN`/`TRUS_TOKEN_COST_OUT`:
      leave unset (cap off, tokens still tracked) or set real $/1k-token rates
      for your provider and a per-owner daily ceiling.
- [ ] Confirm the rollup shows what you expect:
      ```bash
      curl -s "https://<backend>/api/ops/summary?token=$TRUS_OPS_TOKEN" | python3 -m json.tool
      ```
      Know the blind spot: STT/transcribe spend is **cap-exempt** (tokens
      logged as `None`, invisible in the cost rollup) — it's bounded only by
      its own 20-calls/5-min per-owner limiter.

## 8. `TRUS_LIVE_DATA` decision

- [ ] Decide `on` (default — components fetch real values, e.g. weather via
      Open-Meteo) vs `off` (honest disabled marker; components fall back to
      manual entry). Either is fine for the alpha; just be intentional.

## 9. Smoke test: invite → entry → generate → reload

Do this from your own machine first (fast iteration), **then repeat it from a
phone on cellular** per `deploy/README.md` §8 (R-906 AC) before the first real
invite goes out:

```bash
fly ssh console -C "python -m src.invites create 'Preflight Test'"
# open the printed {TRUS_PUBLIC_URL}/claim?token=… link
```

- [ ] Claim page previews the name → confirm claim succeeds.
- [ ] Entry: type a goal → interview → proposal → confirm → module appears.
- [ ] **Reload the page** → still signed in, workspace intact (this is the
      real test of `TRUS_COOKIE_SECURE`/CORS being right).
- [ ] Revoke the test invite when done: `python -m src.invites revoke <id>`.

---

All nine boxes checked → you're clear for Task 10 (the operator deploy /
first real invites). Anything unchecked is a reason to hold, not a reason to
proceed "for now."
