# Unified Ticket Management System (UTMS)

A combined **RBAC** (authentication, users, roles, permissions) and **support-ticketing** platform, served as one product from one backend and one frontend.

It gives an organization:

- Role-based login and access control (Super Admin, Site Lead, Account Manager, Team Lead, Staff, Client) with per-user permission overrides.
- A shared support-ticket workspace (Mail/Inbox, Tickets, SLA & escalation tracking, Reports) embedded directly into the same app users log into.
- SLA and escalation automation (First Response / Resolution clocks, breach notifications, auto-escalation) running in-process, no external scheduler required.
- Real-time in-app notifications (Server-Sent Events) and outbound email for business-critical events.
- Optional Microsoft Graph mailbox integration for receiving/sending ticket-related email.

---

## Architecture at a glance

Two processes make up the whole product:

| Component | What it is | Tech | Default port |
|---|---|---|---|
| [`unified-backend/`](unified-backend) | One FastAPI app serving the RBAC API (`/api/v1/...`) and the Ticketing API (unprefixed — `/tickets`, `/inbox`, `/agents`, ...). RBAC issues JWTs; Ticketing verifies them against the same secret. | FastAPI, SQLAlchemy (async), Alembic, PostgreSQL | `:8000` |
| [`unified-frontend/`](unified-frontend) | The web app — login, RBAC administration (Users/Roles/Permissions/Audit Logs), per-role dashboards, and the embedded ticket workspace (Mail, Tickets, Reports, SLA). | Next.js 16, React 18 | `:3000` |
| [`shared_models/`](shared_models) | The single source of truth for the `User`/`Role` SQLAlchemy models, installed by the backend as a local editable package. | SQLAlchemy | — |

Both API domains share **one PostgreSQL database** (hosted on [Neon](https://neon.tech)) but keep independent Alembic migration histories (`unified-backend/alembic_rbac/`, `unified-backend/alembic_ticketing/`), since they were originally two separate services merged into one process.

> **Note:** this repo previously also contained a standalone, independently-deployable ticket-workspace frontend under `ticketing-service/`. It is not part of the current build or deployment — `unified-frontend`'s embedded ticket workspace is the maintained, up-to-date experience. Only `unified-backend/`, `unified-frontend/`, and `shared_models/` are needed to run or deploy the product.

---

## Tech stack

**Backend** — FastAPI · SQLAlchemy 2 (async, `asyncpg`) · Alembic · Pydantic v2 · PostgreSQL (Neon) · JWT (`python-jose`) · APScheduler (in-process SLA sweep) · Supabase Storage / S3-compatible storage for attachments · Microsoft Graph API (optional mail integration) · SMTP (optional outbound email)

**Frontend** — Next.js 16 · React 18 · TypeScript · TanStack Query · React Hook Form + Zod · Radix UI · Tailwind

**Infra** — Render.com (web services), Neon (Postgres), Supabase (object storage)

---

## Prerequisites

- **Python** 3.12+
- **Node.js** 20+ and npm
- A **PostgreSQL** database (a free [Neon](https://neon.tech) project works well — both an async and a sync connection string are needed, see below)
- (Optional) A **Supabase** project or S3-compatible endpoint, if you want attachment uploads to work
- (Optional) A **Microsoft Entra ID (Azure AD)** app registration, if you want real Graph mailbox integration instead of the built-in mock mail provider

---

## Getting started (local development)

### 1. Clone the repository

```bash
git clone https://github.com/unified-ticket-managament/Unified-ticket-management-system.git
cd Unified-ticket-management-system
```

### 2. Backend setup

```bash
cd unified-backend
python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
```

Create `unified-backend/.env`:

```env
APP_NAME=Unified Backend
APP_ENV=development
DEBUG=true

# Async connection string (asyncpg) — the app's own runtime connection
DATABASE_URL=postgresql+asyncpg://user:password@host/dbname

# Sync connection string (psycopg2) — used only by the ticketing Alembic chain
ALEMBIC_DATABASE_URL=postgresql+psycopg2://user:password@host/dbname

# Must be identical across both migration chains and every process reading it —
# generate with: python -c "import secrets; print(secrets.token_urlsafe(64))"
JWT_SECRET_KEY=<generate-a-random-secret>
JWT_ALGORITHM=HS256

# Any random string — protects the manual SLA-sweep trigger endpoint
SLA_SWEEP_SHARED_SECRET=<generate-a-random-secret>

CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000

# Attachment storage — "supabase" (default) or "s3"
STORAGE_BACKEND=supabase
STORAGE_BUCKET=communication-attachments
SUPABASE_URL=<your-supabase-project-url>
SUPABASE_SERVICE_ROLE_KEY=<your-supabase-service-role-key>
```

See [`unified-backend/app/core/config.py`](unified-backend/app/core/config.py)'s `Settings` class for the full, always-current list of environment variables — including the optional SMTP and Microsoft Graph mail settings, both of which safely no-op/mock when left unset.

Run both independent migration chains, then start the API:

```bash
alembic -c alembic_rbac/alembic.ini upgrade head
alembic -c alembic_ticketing/alembic.ini upgrade head

uvicorn app.main:app --reload --port 8000
```

Or use the bundled script, which does all three steps in order (Git Bash / WSL / macOS / Linux):

```bash
bash scripts/start.sh
```

The API is now available at `http://localhost:8000` — interactive docs at `/docs`, ReDoc at `/redoc`, health check at `/health`.

### 3. Frontend setup

In a separate terminal:

```bash
cd unified-frontend
npm install
```

Create `unified-frontend/.env.local`:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
NEXT_PUBLIC_TICKETING_API_URL=http://localhost:8000
```

Then run:

```bash
npm run dev
```

The app is now available at `http://localhost:3000`. `NEXT_PUBLIC_*` variables are baked in at build/start time — restart `npm run dev` after changing `.env.local`.

### 4. Log in

Seed data (via `unified-backend/scripts/rbac_seed/` and `scripts/ticketing_seed/`, run automatically by the migrations above) provisions a default Super Admin account — check those seed scripts for current credentials.

---

## Running tests

```bash
cd unified-backend
pytest
```

Pure-logic tests run safely together. A handful of database-touching test files are known to hang if run in the same pytest process as each other (a pre-existing `pytest-asyncio` event-loop issue) — run those files individually if you hit that.

---

## Deploying to production

This repo deploys as a [Render Blueprint](https://render.com/docs/blueprint-spec) defined in [`render.yaml`](render.yaml) — two Render Web Services:

- **`unified-backend`** (Python, rootDir `unified-backend`) — runs both Alembic chains then `uvicorn`, per `scripts/start.sh`.
- **`unified-frontend`** (Node, rootDir `unified-frontend`) — `npm ci && npm run build`, then `npm run start`.

Both point at the same production Neon database and Supabase storage project used in development.

See **[`DEPLOYMENT.md`](DEPLOYMENT.md)** for the full step-by-step runbook (generating the shared JWT secret, filling in Render's environment variables, and the first-deploy CORS/API-URL circular-dependency sequence).

> Rotating `JWT_SECRET_KEY` in production immediately invalidates every issued token (forces a global logout) — treat it as a deliberate, scheduled action, not a routine config change.

---

## Repository layout

```
unified-backend/     FastAPI app — app/rbac/ (auth, users, roles) + app/ticketing/ (tickets, mail, SLA) + app/notifications/
unified-frontend/     Next.js app — shell (auth, RBAC admin) + embedded ticket workspace
shared_models/        Shared SQLAlchemy models (User, Role, ...) — single source of truth
render.yaml           Render.com deployment blueprint
DEPLOYMENT.md         Step-by-step Render deployment runbook
CLAUDE.md             Deep technical reference: architecture history, cross-service auth, feature-by-feature design notes
```

## Where to look next

- **[`CLAUDE.md`](CLAUDE.md)** — the deep technical reference: how the RBAC and Ticketing services were merged, cross-service authentication, the permission-caching model, and a dated log of every major feature built on top (SLA & escalation, notifications, organization structure, etc.). Written for AI-assisted development, but equally useful for a human getting oriented on *why* the system is built the way it is.
- **[`unified-frontend/CLAUDE.md`](unified-frontend/CLAUDE.md)** — frontend-specific architecture, conventions, and known issues.
- **[`DEPLOYMENT.md`](DEPLOYMENT.md)** / **[`render.yaml`](render.yaml)** — production deployment.
