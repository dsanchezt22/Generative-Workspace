# Deploying Trus (R-906)

The MVP is **hosted**: backend container on Fly/Railway/Render (any Docker host
with a persistent volume), frontend on Vercel. This doc uses Fly as the
reference (spec Appendix A) — the env contract is identical elsewhere.

Before inviting anyone, run through **`deploy/PREFLIGHT.md`** — this doc is the
"how," that one is the "did you actually do it" checklist.

- Backend image: `backend/Dockerfile` (Python 3.12-slim, non-root uid 1000, port 8080).
- Fly config: copy `deploy/fly.toml.example`, adjust `app`/region.
- Full env reference (every var, with comments): `.env.example` at the repo root
  — this doc summarizes what matters for a hosted deploy; `.env.example` is the
  source of truth for exact names/defaults.

## 1. Backend environment

The image bakes in the prod security posture; everything else is per-deployment
env or a `fly secrets set` secret. Every var below is one the code actually
reads (verified by grepping `os.environ`/`os.getenv` in `backend/src`) — nothing
here is aspirational.

### Baked into the image (override only if you know why)

| Var | Image default | Meaning |
|---|---|---|
| `TRUS_ENV` | `prod` | Enables the boot guard: refuses the default `SESSION_SECRET` (R-901), and disables `TRUS_ALLOW_URL_IMPORT` unless explicitly re-enabled (SSRF guard). |
| `TRUS_ALLOW_ANON` | `0` | Only invite-claimed users get data access; anonymous requests → 401 (R-901). |
| `TRUS_COOKIE_SECURE` | `1` | Session cookie is `SameSite=None; Secure` — required for the cross-origin Vercel↔backend split. Both flags flip together; there is no valid mixed state. |
| `TRUS_DB_PATH` | `/data/trus.db` | SQLite on the persistent volume (see §2). |

### Required per deployment (plain env — not secret, goes in `fly.toml` `[env]`)

| Var | Example | Meaning |
|---|---|---|
| `TRUS_CORS_ORIGINS` | `https://trus.example.com` | Comma-separated list of allowed browser origins = your Vercel URL(s). No trailing slash. Whitespace/trailing commas are tolerated. |
| `TRUS_PUBLIC_URL` | `https://trus.example.com` | The **frontend** origin, used to build invite claim links (`{TRUS_PUBLIC_URL}/claim?token=…`). Pair it with `TRUS_CORS_ORIGINS` — they normally hold the same value. |

### Secrets (`fly secrets set NAME=value` — never in `fly.toml`, never committed, never baked into the image)

| Secret | Required? | Meaning |
|---|---|---|
| `SESSION_SECRET` | **Required** | Session-cookie signing key. Generate: `python -c "import secrets; print(secrets.token_urlsafe(48))"`. The app refuses to boot in prod with the public default value. |
| `TRUS_OPS_TOKEN` | Required to operate safely | Gates `GET /api/ops/summary?token=…` (generation volume, DAU, per-user cost/token rollup). Unset ⇒ endpoint always 401s — you'd be flying blind. |
| `GEMINI_API_KEY` | Required (or the alternative below) | Google Gemini key — the default LLM provider. |
| *(alternative to `GEMINI_API_KEY`)* `TRUS_LLM_BASE_URL` + `TRUS_LLM_MODEL` (+ optional `TRUS_LLM_API_KEY`) | Required if not using Gemini | Points generation at any OpenAI-compatible endpoint (self-hosted Ollama/vLLM, or a hosted provider like Together/Fireworks). See `.env.example` Options A/B. |
| `TRUS_STT_API_KEY` | Optional | Bearer token for `TRUS_STT_BASE_URL` (voice transcription). Only needed if that endpoint requires auth; local STT servers usually don't. |
| `TRUS_VISION_API_KEY` | Optional | Key for the vision endpoint (Layout Studio screenshot import). Falls back to `TRUS_LLM_API_KEY` if unset. |
| `TRUS_EMBED_API_KEY` | Optional | Key for a hosted embeddings endpoint (semantic cache). Falls back to `TRUS_LLM_API_KEY` if unset; the default embedder needs no key at all. |

### Optional tuning knobs (all have sane built-in defaults — set only to change behavior)

| Area | Vars | Default |
|---|---|---|
| LLM provider tuning | `TRUS_LLM_PROVIDER`, `TRUS_LLM_MODEL`, `GEMINI_MODEL`, `TRUS_LLM_TIMEOUT`, `TRUS_LLM_MAX_RETRIES`, `TRUS_LLM_MAX_OUTPUT_TOKENS`, `TRUS_LLM_CASCADE`, `TRUS_LLM_JSON_MODE` | auto-detects provider; 60s timeout, 1 retry, cascade-to-Gemini-then-stub on; see `.env.example` for the full walkthrough (Options A/B/C) |
| Generate rate limit (R-1202) | `TRUS_GEN_RATE_MAX`, `TRUS_GEN_RATE_WINDOW` | 30 generations / 300s per owner, shared across generate/preview/generate_from_file/refine/insights |
| Daily cost cap (R-1202) | `TRUS_DAILY_COST_CAP_USD`, `TRUS_TOKEN_COST_IN`, `TRUS_TOKEN_COST_OUT` | cap unset → never blocks; token $ rates default 0 → cost shown as $0, tokens still counted |
| Backups (R-1106) | `TRUS_BACKUP_DIR`, `TRUS_BACKUP_KEEP` | `/data/backups`, keep newest 7 — see `deploy/BACKUP.md` |
| Voice transcription | `TRUS_STT_BASE_URL`, `TRUS_STT_MODEL`, `TRUS_STT_TIMEOUT` | unset ⇒ `/api/transcribe` honestly 422s instead of failing silently |
| Vision (Layout Studio import) | `TRUS_VISION_MODEL`, `TRUS_VISION_BASE_URL`, `TRUS_VISION_TIMEOUT` | unset model ⇒ falls back to Gemini for the screenshot read |
| Semantic cache | `TRUS_CACHE`, `TRUS_CACHE_THRESHOLD`, `TRUS_CACHE_SEED_THRESHOLD`, `TRUS_EMBED_BASE_URL`, `TRUS_EMBED_MODEL` | on by default; dependency-free hashing embedder unless `TRUS_EMBED_BASE_URL` is set |
| Live data widgets | `TRUS_LIVE_DATA`, `TRUS_LIVE_CACHE_MAX` | `on` (real fetch, e.g. weather); cache capped at 5000 rows, oldest pruned on write |
| Screenshot capture engine | `TRUS_CAPTURE_OCR`, `TRUS_CAPTURE_VERIFY`, `TRUS_CAPTURE_CONF_THRESHOLD`, `TRUS_CAPTURE_AUTOPROMOTE` | OCR/verify off by default (optional deps); autopromote on |
| Layout Studio URL import | `TRUS_ALLOW_URL_IMPORT` | `0`; in prod, URL-based image import 422s unless set to `1` (SSRF guard, Stage-1 review) |
| Misc | `TRUS_LOG_LEVEL` | `INFO` |

## 2. Persistent volume (`/data`: DB + backups)

SQLite and its backups must live on a volume or every deploy wipes all user data:

```bash
fly volumes create trus_data --size 1        # matches [mounts] in fly.toml
```

`TRUS_DB_PATH=/data/trus.db` points into that mount; `TRUS_BACKUP_DIR` defaults
to `/data/backups`, a subdirectory of the same mount — no second volume needed.

### Run EXACTLY ONE machine (`fly scale count 1`)

Fly's HA default leans toward **2 machines** — for this app that is split-brain,
not redundancy. Two things pin the deployment to a single machine:

1. **SQLite on one volume.** Volumes attach to one machine; a second machine
   gets its own (empty) volume and a **divergent database** — two users' data
   silently forks depending on which machine served them.
2. **The rate limiter is in-process.** Each machine enforces its own copy of
   the per-owner budgets (generate/transcribe/live), so with 2 machines every
   limit is effectively doubled — the limits are silently halved in strength.

```bash
fly scale count 1        # after first deploy; verify with `fly scale show`
```

Multi-instance needs a shared DB and a shared limiter store — a Stage-5
concern, not a knob to flip here. This is also a `PREFLIGHT.md` checkbox.

### The Fly-volume-ownership gotcha (Stage-1 review)

The image's `Dockerfile` creates `/data` and `chown`s it to the non-root `trus`
user (uid 1000) — but that happens **at image build time**, before any volume
exists. When Fly attaches a freshly-created volume at `/data`, the volume's own
filesystem root is mounted **over** that directory and typically comes back
owned by `root:root`, shadowing the image's `chown`. If the app then can't
write to `/data`, SQLite fails to open and the container crash-loops.

**Verify before you rely on it** (this is also a `PREFLIGHT.md` item):

```bash
fly ssh console -C "su trus -c 'touch /data/.write-test && rm /data/.write-test && echo OK'"
```

If that doesn't print `OK`, fix ownership once (root can always write regardless
of the app's `USER trus`):

```bash
fly ssh console -C "chown -R 1000:1000 /data"
```

Do this **before** scheduling backups or inviting anyone — a volume that isn't
writable as uid 1000 means every generation silently fails to persist.

## 3. Deploy the backend

```bash
cd deploy && cp fly.toml.example fly.toml    # edit app name / region
fly launch --no-deploy                       # first time only; keep our fly.toml
fly secrets set SESSION_SECRET=… TRUS_OPS_TOKEN=… GEMINI_API_KEY=…
fly deploy
curl https://<backend-app>.fly.dev/api/health   # → {"status":"ok"}
```

(Optional) verify the image builds locally first, without deploying:

```bash
docker build -t trus-backend -f backend/Dockerfile backend/
```

## 4. Frontend (Vercel)

- Project root: `frontend/`.
- Env var: `NEXT_PUBLIC_API_BASE` = the backend URL (e.g.
  `https://trus-backend.fly.dev`) — no trailing slash.
- After the first deploy you know the Vercel URL: set the backend's
  `TRUS_CORS_ORIGINS` + `TRUS_PUBLIC_URL` to it and redeploy the backend.
  (Chicken-and-egg is normal: deploy backend → deploy frontend → point the two
  at each other.)

### CORS / `TRUS_PUBLIC_URL` pairing (the hosted split)

The backend (Fly) and frontend (Vercel) are different origins, so three things
must agree exactly (scheme + host, no trailing slash) or auth silently breaks:

1. `TRUS_CORS_ORIGINS` on the backend — the Vercel origin(s) allowed to call the API.
2. `TRUS_PUBLIC_URL` on the backend — the same Vercel origin, used to build invite links.
3. `NEXT_PUBLIC_API_BASE` on the frontend (Vercel) — the Fly backend origin.

`TRUS_COOKIE_SECURE=1` (baked into the image) is what makes the cross-origin
cookie work at all — without it, the browser drops the session cookie on every
cross-origin request and users get silently logged out on reload.

## 5. Provision alpha users (invites)

```bash
fly ssh console -C "python -m src.invites create 'Ada Lovelace'"
# → Ada Lovelace: https://trus.example.com/claim?token=…
fly ssh console -C "python -m src.invites list"
fly ssh console -C "python -m src.invites revoke <user-id>"
```

The printed URL targets the **frontend** `/claim` page (that's why
`TRUS_PUBLIC_URL` must be the Vercel origin). The claim flow is two-step by
design: the page loads → `GET /api/auth/claim?token=…` (read-only validity
preview, mutates nothing) → the user confirms → `POST /api/auth/claim` performs
the claim, adopting any pre-claim anonymous work. A session already claimed by
a *different* user gets `409 {rebind}` and must explicitly confirm the switch.

## 6. Backups + restore (R-1106)

Full runbook: **`deploy/BACKUP.md`** (commands, scheduling options for Fly vs a
plain Docker host, the restore procedure, and the pre-alpha restore-drill
checklist). Summary: `python -m src.backup backup` snapshots
`TRUS_DB_PATH` to `TRUS_BACKUP_DIR` (default `/data/backups`, keeping the newest
`TRUS_BACKUP_KEEP` = 7); schedule it daily (RPO ≤ 24h) via a Fly scheduled
machine or an external cron hitting `fly ssh console`. **Exercise one restore
before inviting anyone** — `deploy/BACKUP.md` has the exact drill; it's also a
`PREFLIGHT.md` item.

## 7. Cost cap + rate-limit knobs (R-1202)

Every LLM-backed route (generate/preview/generate_from_file/refine/insights)
shares one per-owner rate limiter: `TRUS_GEN_RATE_MAX` calls per
`TRUS_GEN_RATE_WINDOW` seconds (default 30/300) → 429 past that. Optionally cap
spend: set `TRUS_DAILY_COST_CAP_USD` plus `TRUS_TOKEN_COST_IN`/`TRUS_TOKEN_COST_OUT`
(the $ per 1,000 input/output tokens for your provider) and an owner over their
daily cap also gets a 429 with an honest "today's usage budget" message. Leave
the cap unset for the alpha if you'd rather rely on the rate limit alone — token
counts still show in `/api/ops/summary` either way (cost is $0 if the rates are
unset).

Note: voice transcription (`/api/transcribe`) is **exempt from the cost cap** —
STT calls log no token counts (tokens recorded as `None`), so their spend never
appears in the cost rollup and is bounded only by transcription's own
20-calls/5-min per-owner rate limiter.

Public share links (`/api/share/{token}`, SHARE-1..3): the read path is
sessionless and revocation is checked on every resolve, so **do not let any CDN
or reverse proxy cache `/api/share/*` responses** — a cached page would keep
serving after a revoke/rotate. That path is rate-limited **per client IP**
(`TRUS_SHARE_RATE_MAX`/`TRUS_SHARE_RATE_WINDOW`, default 60/60s); behind a
reverse proxy you MUST run `uvicorn --proxy-headers` (and trust the proxy) so
`request.client.host` is the real viewer IP, otherwise every viewer shares one
bucket keyed to the proxy.

## 8. Post-deploy smoke test (R-906 AC)

From a **phone on cellular** (not your wifi — that's the point), as a
provisioned user:

1. Open the invite link → the claim page previews your name → confirm claim.
2. Entry: type a messy goal on the canvas entry surface.
3. Interview: answer the clarifying question(s).
4. Proposal: a module proposal renders.
5. Confirm it → the module appears on the canvas.
6. **Reload the page** → still signed in (cookie survived), workspace intact.

Also verify the gates hold:

```bash
curl -s -o /dev/null -w '%{http_code}' https://<backend>/api/modules   # → 401 (anon refused)
curl -s https://<backend>/api/ops/summary?token=$TRUS_OPS_TOKEN        # → stats JSON
```

If step 6 loses the session: `TRUS_COOKIE_SECURE` isn't `1`, or the frontend
isn't calling over HTTPS, or `TRUS_CORS_ORIGINS` doesn't exactly match the
Vercel origin (scheme + host, no trailing slash).

## 9. Before you invite anyone

Run through **`deploy/PREFLIGHT.md`** — it's the operator checklist version of
everything above (secrets, volume, WAL, backups + restore drill, CORS, cost
cap/rate limits, health/ops reachability, the smoke test) with exact commands.
