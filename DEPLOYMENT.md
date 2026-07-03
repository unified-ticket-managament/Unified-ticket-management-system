# Deploying to Render

This monorepo deploys as **4 Render services** (2 backends, 2 frontends),
defined together in [`render.yaml`](./render.yaml) at the repo root. Render
detects this file automatically when you create a **Blueprint**.

This supersedes the earlier `rbac-service/DEPLOYMENT.md`, which only covered
RBAC's two services from before the two services were merged into this
monorepo. The 4 services below are a **fresh deployment** — the previously
live services (on the old, now-abandoned standalone `rbac-service` and
`ticketing-service` repos) are not touched by this and can be suspended once
the new deployment is verified working.

Local development is unaffected by any of this — `render.yaml` and Render's
dashboard env vars are only read by Render, never by `npm run dev` or your
local `.env` files.

## Prerequisites

- This repo pushed to GitHub — `origin` is
  `unified-ticket-managament/Unified-ticket-management-system`.
- A [Render](https://render.com) account connected to that GitHub org/repo.
- The **existing production** Neon Postgres connection strings (async +
  sync/psycopg2 variants) and Supabase Storage credentials — both services
  already share one Neon database and one Supabase project in production;
  this deployment reuses them, it does not provision new ones.
- A freshly generated JWT secret shared by both backends (see Step 3).

## Step 1 — Generate the shared JWT secret

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Keep this value handy — you'll paste the **identical string** into both
`rbac-backend`'s and `ticketing-backend`'s `JWT_SECRET_KEY` in Step 3. Do not
use Render's `generateValue: true` for this — it produces a different random
value per service, and RBAC-issued tokens would fail verification on
ticketing-backend.

## Step 2 — Create the Render Blueprint

1. Render dashboard → **New** → **Blueprint**.
2. Select the `Unified-ticket-management-system` repo, branch `main`.
   Render reads `render.yaml` and shows four services to create:
   `rbac-backend`, `rbac-frontend`, `ticketing-backend`, `ticketing-frontend`.
3. Click **Apply**. Render will ask you to fill in every `sync: false` var
   before it can deploy. For the cross-service URL vars (`CORS_ORIGINS`,
   `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_TICKETING_FRONTEND_URL`,
   `NEXT_PUBLIC_TICKETING_API_URL`, `VITE_API_BASE_URL`,
   `VITE_RBAC_API_BASE_URL`, `VITE_RBAC_FRONTEND_URL`) you don't know the
   real URLs yet — enter any placeholder (e.g. `http://localhost:3000`) for
   now. You'll fix these in Step 4.

## Step 3 — Environment variables to paste during Apply

### `rbac-backend`
| Key | Value |
|---|---|
| `DATABASE_URL` | production Neon connection string (`postgresql+asyncpg://...`) |
| `JWT_SECRET_KEY` | the value generated in Step 1 |
| `CORS_ORIGINS` | placeholder for now (Step 4) |

### `ticketing-backend`
| Key | Value |
|---|---|
| `DATABASE_URL` | same Neon connection string, async form |
| `ALEMBIC_DATABASE_URL` | same Neon database, sync/psycopg2 form (`postgresql+psycopg2://...`) |
| `JWT_SECRET_KEY` | **the same value as rbac-backend's**, from Step 1 |
| `CORS_ORIGINS` | placeholder for now (Step 4) |
| `SUPABASE_URL` | production Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | production Supabase service role key |

### `rbac-frontend` / `ticketing-frontend`
All `sync: false` vars here are cross-service URLs — placeholder for now,
fixed in Step 4.

Everything else (`PYTHON_VERSION`, `APP_ENV`, `JWT_ALGORITHM`,
`STORAGE_BACKEND`, etc.) is fixed directly in `render.yaml` and needs no
action.

## Step 4 — The circular-dependency second pass

Every cross-service URL needs the *other* service's real URL — but none of
those URLs exist until each service has deployed once. This is normal and
only needs doing once:

1. Let all four services finish their first deploy. They'll be reachable but
   unable to fully talk to each other yet (login/API calls across services
   will fail) — that's expected.
2. Note each service's actual URL from the Render dashboard (top of each
   service page, e.g. `https://rbac-backend-xxxx.onrender.com`).
3. On **`rbac-backend`** → Environment → set `CORS_ORIGINS` to
   `<rbac-frontend URL>,<ticketing-frontend URL>` (comma-separated, no
   trailing slashes). Save — triggers an automatic restart (no rebuild
   needed, read at request time).
4. On **`ticketing-backend`** → Environment → same `CORS_ORIGINS` value as
   above (both frontends need to reach it).
5. On **`rbac-frontend`** → Environment → set:
   - `NEXT_PUBLIC_API_URL` = `<rbac-backend URL>/api/v1`
   - `NEXT_PUBLIC_TICKETING_FRONTEND_URL` = `<ticketing-frontend URL>`
   - `NEXT_PUBLIC_TICKETING_API_URL` = `<ticketing-backend URL>`

   Then **Manual Deploy → Deploy latest commit** — `NEXT_PUBLIC_*` vars are
   inlined into the JS bundle at *build* time, saving the env var alone does
   nothing.
6. On **`ticketing-frontend`** → Environment → set:
   - `VITE_API_BASE_URL` = `<ticketing-backend URL>`
   - `VITE_RBAC_API_BASE_URL` = `<rbac-backend URL>/api/v1`
   - `VITE_RBAC_FRONTEND_URL` = `<rbac-frontend URL>`

   Then **Manual Deploy → Deploy latest commit** (same build-time-baking
   reason as Step 5).

## Step 5 — Verify

1. `https://<rbac-backend>.onrender.com/health` and `/docs`.
2. `https://<ticketing-backend>.onrender.com/health` and `/docs`.
3. Open `https://<rbac-frontend>.onrender.com/login`, log in, confirm the
   dashboard loads, then open the embedded **Ticket Workspace** from the
   sidebar and confirm tickets load (this round-trips a JWT from
   rbac-frontend through rbac-backend-issued auth into ticketing-backend —
   the main thing this whole second pass exists to make work).
4. Open `https://<ticketing-frontend>.onrender.com` standalone, confirm its
   own login flow (against rbac-backend) and ticket views work too.

Migrations (`alembic upgrade head`) run automatically as part of each
backend's `startCommand` on every deploy. Both services' migration history
is already at head against this production database, so this is a no-op
safety net, not a fresh schema creation.

## Step 6 — Decommission the old deployments

Once the above is verified working, suspend (don't immediately delete) the
4 old services still connected to the abandoned standalone `rbac-service`
and `ticketing-service` repos, to avoid confusion about which URLs are
current. Delete them for good after a confidence period.

## Notes / things worth knowing

- **Free plan cold starts**: Render's free tier spins services down after 15
  minutes of inactivity. First request after idle can take 30–60s, on top of
  Neon's own free-tier cold start. Don't be alarmed by slow first logins.
- **`shared_models` dependency**: both backends install it as a local
  editable path (`-e ../../shared_models` from rbac-backend,
  `-e ../shared_models` from ticketing-backend) now that it lives in this
  monorepo — no external git dependency, no pinned-commit reproducibility
  concern like the old standalone-repo setup had. A change to
  `shared_models/` ships atomically with whichever service's deploy picks it
  up next.
- **`ticketing-backend`'s build command** installs from
  `../requirements.txt`, not `requirements.txt` — that file lives at
  `ticketing-service/requirements.txt`, one level above `backend/`. This is
  a real gotcha, not a typo.
- **This is a live production system used by other people** (RBAC and
  Ticketing are both already in active use on the old deployments). Do this
  during a low-traffic window, and don't delete the old services until the
  new ones are confirmed fully working end-to-end.
