# Deploying to Render

This repo deploys as **two separate Render Web Services** (backend + frontend),
defined together in [`render.yaml`](./render.yaml) at the repo root. Render
detects this file automatically when you create a **Blueprint**.

Local development is unaffected by any of this — `render.yaml` and Render's
dashboard env vars are only read by Render, never by `npm run dev` or your
local `backend/.env`.

## Prerequisites

- This repo pushed to GitHub (already done — `origin` is
  `unified-ticket-managament/rbac-project`).
- A [Render](https://render.com) account connected to that GitHub org/repo.
- A **separate Neon project** for production, distinct from your local dev
  database. Local dev and production should never share a database.

## Step 1 — Create the production Neon database

1. In the [Neon console](https://console.neon.tech), create a **new project**
   (e.g. `rbac-production`) — don't reuse your local dev project/branch.
2. Once created, go to **Connect** and copy the connection string. It will
   look like:
   ```
   postgresql://neondb_owner:AbC123xyz@ep-something-12345.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require
   ```
3. Keep this handy — you'll paste it into Render in Step 3. You don't need to
   modify it in any way; the backend normalizes the scheme (`postgres://` /
   `postgresql://` → `postgresql+asyncpg://`) and strips/translates
   `sslmode`/`channel_binding` automatically
   (`backend/app/core/config.py`, `normalize_database_url`).

## Step 2 — Create the Render Blueprint

1. Render dashboard → **New** → **Blueprint**.
2. Select the `rbac-project` repo. Render reads `render.yaml` and shows two
   services to create: `rbac-backend` and `rbac-frontend`.
3. Click **Apply**. Render will ask you to fill in the `sync: false` vars
   listed below before it can deploy — for `CORS_ORIGINS` and
   `NEXT_PUBLIC_API_URL` you can enter placeholder values for now (e.g.
   `http://localhost:3000` and `http://localhost:8000/api/v1`) since you
   don't know the real URLs yet. You'll fix these in Step 4.

## Step 3 — Environment variables

### `rbac-backend`

| Key | Value | Set by |
|---|---|---|
| `PYTHON_VERSION` | `3.12.5` | render.yaml (fixed) |
| `APP_ENV` | `production` | render.yaml (fixed) |
| `DEBUG` | `false` | render.yaml (fixed) |
| `SECURE_COOKIES` | `true` | render.yaml (fixed) |
| `LOG_LEVEL` | `INFO` | render.yaml (fixed) |
| `DATABASE_URL` | *your Neon connection string from Step 1* | **you paste this manually** |
| `JWT_SECRET_KEY` | *(auto-generated, random)* | Render (`generateValue: true`) — no action needed |
| `JWT_ALGORITHM` | `HS256` | render.yaml (fixed) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | render.yaml (fixed) |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | render.yaml (fixed) |
| `CORS_ORIGINS` | *your frontend's Render URL, e.g.* `https://rbac-frontend.onrender.com` | **you paste this manually (Step 4)** |

### `rbac-frontend`

| Key | Value | Set by |
|---|---|---|
| `NODE_VERSION` | `20.18.0` | render.yaml (fixed) |
| `NEXT_PUBLIC_API_URL` | *your backend's Render URL + `/api/v1`, e.g.* `https://rbac-backend.onrender.com/api/v1` | **you paste this manually (Step 4)** |

## Step 4 — The circular-dependency second pass

`CORS_ORIGINS` needs the frontend's URL, and `NEXT_PUBLIC_API_URL` needs the
backend's URL — but neither URL exists until each service has deployed once.
This is normal and only needs doing once:

1. Let both services finish their first deploy (they'll be reachable but
   unable to talk to each other yet — login will fail with a CORS or network
   error, that's expected).
2. Note each service's actual URL from the Render dashboard (top of each
   service page, e.g. `https://rbac-backend-xxxx.onrender.com`).
3. On `rbac-backend` → **Environment** → set `CORS_ORIGINS` to the frontend's
   URL (no trailing slash). Save — this triggers an automatic redeploy
   (restart only, no rebuild needed, since it's read at request time).
4. On `rbac-frontend` → **Environment** → set `NEXT_PUBLIC_API_URL` to the
   backend's URL + `/api/v1`. Save.
   **Important**: `NEXT_PUBLIC_*` variables are inlined into the JavaScript
   bundle at *build* time, not read at runtime. Saving the env var alone is
   not enough — go to **Manual Deploy** → **Deploy latest commit** (or **Clear
   build cache & deploy** if it seems stale) to force a real rebuild.

## Step 5 — Verify

1. Backend health check: `https://<your-backend>.onrender.com/health` →
   should return `{"status": "healthy", ...}`.
2. Backend API docs: `https://<your-backend>.onrender.com/docs` (Swagger UI).
3. Frontend: open `https://<your-frontend>.onrender.com/login` — should
   render the login page with no console errors.
4. Log in (see Step 6 for credentials) and confirm the dashboard loads.

Migrations (`alembic upgrade head`) run automatically as part of the
backend's `startCommand` on every deploy, before the server starts — the
schema is created fresh from `backend/alembic/versions/9cadc1a089a3_initial_rbac_schema.py`
(creates `permissions`, `roles`, `role_permissions`, `users`, `audit_logs` —
no other services need to run first against this database).

## Step 6 — Seed demo data

Render dashboard → `rbac-backend` service → **Shell** tab → run:

```bash
python scripts/seed.py
```

This is idempotent (safe to re-run) and creates the same demo
roles/permissions/users as local dev, including `admin@rbac.com` /
`Admin@123456`.

**Heads up**: the script prints every seeded email/password pair to stdout,
which lands in Render's deploy/shell logs, and the passwords are the same
well-known ones used in local dev. This is fine for a demo/staging
environment but if this ever becomes a real production environment with real
users, change the Super Admin password immediately after first login (via
Settings → Change Password) and avoid re-running the seed script publicly.

## Notes / things worth knowing

- **Free plan cold starts**: Render's free tier spins services down after 15
  minutes of inactivity. First request after idle can take 30–60s. This is
  separate from (and stacks with) Neon's own free-tier cold-start latency —
  don't be alarmed by slow first logins.
- **`shared_models` dependency**: `backend/requirements.txt` installs it via
  `git+https://github.com/unified-ticket-managament/shared_models.git` (public
  repo, no auth needed for Render's build) with no pinned commit/tag, so
  every fresh build re-resolves to that repo's current
  `main` branch tip. This matches how it's already used locally, so it's not
  a blocker — but if that upstream repo changes in a way incompatible with
  this backend's models/migrations, a future deploy could break without any
  change on your side. Pinning to a specific commit (currently resolves to
  `289598a0d1de27107d31d532133de8eff0824aa7` in the local `.venv`) would make
  builds fully reproducible; ask if you'd like this applied.
- **Local setup is untouched**: nothing in `backend/.env`, `frontend/`'s
  local behavior, or the dev scripts changed. `render.yaml` is only read by
  Render.
