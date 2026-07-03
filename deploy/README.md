# Deploying Trus (R-906)

The MVP is **hosted**: backend container on Fly/Railway/Render (any Docker host
with a persistent volume), frontend on Vercel. This doc uses Fly as the
reference (spec Appendix A) — the env contract is identical elsewhere.

- Backend image: `backend/Dockerfile` (Python 3.12-slim, non-root, port 8080).
- Fly config: copy `deploy/fly.toml.example`, adjust `app`/region.

## 1. Backend environment

The image bakes in the prod posture; the rest is per-deployment.

### Baked into the image (override only if you know why)

| Var | Image default | Meaning |
|---|---|---|
| `TRUS_ENV` | `prod` | Enables the boot guard: refuses the default `SESSION_SECRET` (R-901). |
| `TRUS_ALLOW_ANON` | `0` | Only invite-claimed users get data access; anonymous requests → 401 (R-901). |
| `TRUS_COOKIE_SECURE` | `1` | Session cookie is `SameSite=None; Secure` — required for the cross-origin Vercel↔backend split. Both flags flip together; there is no valid mixed state. |
| `TRUS_DB_PATH` | `/data/trus.db` | SQLite on the persistent volume (see §2). |

### Set per deployment (plain env)

| Var | Example | Meaning |
|---|---|---|
| `TRUS_CORS_ORIGINS` | `https://trus.example.com` | Comma-separated list of allowed browser origins = your Vercel URL(s). No trailing slash. Whitespace/trailing commas are tolerated. |
| `TRUS_PUBLIC_URL` | `https://trus.example.com` | The **frontend** origin, used to build invite claim links (`{TRUS_PUBLIC_URL}/claim?token=…`). Pair it with `TRUS_CORS_ORIGINS` — they normally hold the same value. |

### Secrets (set via `fly secrets set NAME=value` — never in fly.toml, never committed)

| Secret | Meaning |
|---|---|
| `SESSION_SECRET` | Session-cookie signing key. Generate: `python -c "import secrets; print(secrets.token_urlsafe(48))"`. **The app refuses to boot in prod with the default value.** |
| `TRUS_OPS_TOKEN` | Gates `GET /api/ops/summary?token=…` (generation volume + DAU). Unset ⇒ endpoint always 401s. |
| `GEMINI_API_KEY` | LLM provider key (or configure an OpenAI-compatible endpoint via `TRUS_LLM_*`; see `.env.example`). |

## 2. Persistent volume

SQLite must live on a volume or every deploy wipes all user data:

```bash
fly volumes create trus_data --size 1        # matches [mounts] in fly.toml
```

`TRUS_DB_PATH=/data/trus.db` points into that mount. The image's non-root user
owns `/data`.

## 3. Deploy the backend

```bash
cd deploy && cp fly.toml.example fly.toml    # edit app name / region
fly launch --no-deploy                       # first time only; keep our fly.toml
fly secrets set SESSION_SECRET=… TRUS_OPS_TOKEN=… GEMINI_API_KEY=…
fly deploy
curl https://<backend-app>.fly.dev/api/health   # → {"status":"ok"}
```

## 4. Frontend (Vercel)

- Project root: `frontend/`.
- Env var: `NEXT_PUBLIC_API_BASE` = the backend URL (e.g.
  `https://trus-backend.fly.dev`) — no trailing slash.
- After the first deploy you know the Vercel URL: set the backend's
  `TRUS_CORS_ORIGINS` + `TRUS_PUBLIC_URL` to it and redeploy the backend.
  (Chicken-and-egg is normal: deploy backend → deploy frontend → point the two
  at each other.)

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

## 6. Post-deploy smoke test (R-906 AC)

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
