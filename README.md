# Unified Ticket Management System (UTMS)

A combined RBAC (authentication, users, roles, permissions) and support-ticketing platform — one product, built by merging what were originally two independent systems.

## Architecture at a glance

| Directory | What it is | Runs on |
|---|---|--|
| `unified-frontend/` | The shell application — login, RBAC (Users/Roles/Audit Logs/Settings), and an embedded copy of the ticket workspace (Mail, Tickets, Reports, per-role dashboards). Next.js 16. **This is the primary, currently-maintained frontend.** | `:3000` |
| `unified-backend/` | A single FastAPI process serving both the RBAC API (`/api/v1/...`) and the Ticketing API (unprefixed — `/tickets`, `/inbox`, ...). RBAC is the sole issuer of JWTs; Ticketing verifies them. | `:8000` |
| `ticketing-service/` | The standalone Vite/React ticket-workspace app this product started from, with its own login flow. Still runs independently, but `unified-frontend`'s embedded copy has since pulled ahead (see its own `CLAUDE.md`'s "Mail v2" section) and is not kept in sync automatically. Optional — only needed if you're testing this app directly. | `:5173` |
| `shared_models/` | The one real copy of the `User`/`Role` SQLAlchemy models, installed as a local editable package by `unified-backend`. | — |

Both API domains share **one physical PostgreSQL database** (Neon) but keep independent Alembic migration histories (`unified-backend/alembic_rbac/`, `unified-backend/alembic_ticketing/`).
# Clone Repository

```bash
git clone <repository-url>
```

Example

```bash
git clone https://github.com/unified-ticket-managament/Phase_1.git
```

Move into the project

```bash
cd Phase_1
```

---

# Backend Setup

## Create Virtual Environment

Windows

```bash
python -m venv .venv
.venv\Scripts\activate
```

Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
```

## Install Dependencies

```bash
pip install -r requirements.txt
```

## Configure Environment Variables

Create a `.env` file inside the `backend/` folder.

Example

```env
APP_NAME=Ticket Management System
APP_ENV=development
DEBUG=True

DATABASE_URL=<your_async_database_url>

ALEMBIC_DATABASE_URL=<your_psycopg2_database_url>

LOG_LEVEL=INFO

CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173

# Object storage for attachments — STORAGE_BACKEND=supabase (default) or "s3"
STORAGE_BACKEND=supabase
STORAGE_BUCKET=communication-attachments
STORAGE_URL_EXPIRY_SECONDS=3600

# Required when STORAGE_BACKEND=supabase
SUPABASE_URL=<your_supabase_project_url>
SUPABASE_SERVICE_ROLE_KEY=<your_supabase_service_role_key>

# Required when STORAGE_BACKEND=s3 (e.g. local MinIO, see below)
STORAGE_ENDPOINT_URL=http://localhost:9000
STORAGE_ACCESS_KEY=<key>
STORAGE_SECRET_KEY=<secret>
STORAGE_REGION=us-east-1
STORAGE_USE_SSL=False
```

See `backend/.env.example` for the full, always-current list.

## Run Database Migrations

```bash
cd backend
alembic upgrade head
```

## Run the Backend

```bash
uvicorn app.main:app --reload
```

Runs on port 8000, not uvicorn's default 8000, since the RBAC service's own backend
(`rbac-service/backend`) already defaults to 8000 and both are commonly run at the same time.

Server runs at `http://127.0.0.1:8000`

Swagger UI: `http://127.0.0.1:8000/docs`

ReDoc: `http://127.0.0.1:8000/redoc`

---

# Frontend Setup

```bash
cd frontend
npm install
```

Create a `.env` file (copy `.env.example`):

```env
VITE_API_BASE_URL=http://localhost:3000
```

Then run:

```bash
npm run dev
```

App runs at `http://localhost:5173` and talks to the backend at
`VITE_API_BASE_URL` (see `src/api/client.ts`) — make sure the backend from
the previous section is running first.

Other scripts:

```bash
npm run build     # tsc -b && vite build — type-checks then produces dist/
npm run preview    # preview the production build locally
```


## Quick start (local development)

Two processes cover normal end-to-end testing:

```bash
# Terminal 1 — backend (runs both Alembic chains, then starts uvicorn)
cd unified-backend
bash scripts/start.sh          # http://127.0.0.1:8000, docs at /docs

# Terminal 2 — frontend
cd unified-frontend
npm install
npm run dev                    # http://localhost:3000
```

`unified-backend/.env` needs `DATABASE_URL`, `ALEMBIC_DATABASE_URL`, `JWT_SECRET_KEY`, `JWT_ALGORITHM`, plus the Supabase storage variables — see `unified-backend/app/core/config.py`'s `Settings` for the full list. `unified-frontend/.env.local` needs `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_TICKETING_API_URL` (both pointed at the backend above — see that project's own `CLAUDE.md` Known Issues if ticket/mail requests network-error while everything else works).

Only start `ticketing-service/frontend` (`npm install && npm run dev`, port 5173) if you specifically need to exercise the standalone app rather than the embedded copy.

## Where to look next

- **`CLAUDE.md`** (this directory) — the deep technical reference: repo history, the backend/frontend consolidations, cross-service auth, and pointers into each service's own `CLAUDE.md`. Written for AI-assisted development, but equally useful for a human getting oriented.
- **`unified-frontend/CLAUDE.md`**, **`ticketing-service/CLAUDE.md`** — architecture, conventions, and known issues specific to each service.
- **`DEPLOYMENT.md`** — the Render.com deployment runbook (Neon setup, environment variables, the CORS/API-URL first-deploy sequence).
- **`render.yaml`** — the actual Render Blueprint: one `unified-backend` Web Service, one `rbac-frontend` Web Service (`unified-frontend`'s deployed name), one `ticketing-frontend` static site.

## Repo layout

```
unified-backend/       # FastAPI — app/rbac/ + app/ticketing/ + app/notifications/
unified-frontend/       # Next.js — the shell app + embedded ticket workspace
ticketing-service/
└── frontend/           # Standalone Vite ticket-workspace app (optional)
shared_models/          # Shared SQLAlchemy models (User, Role, ...)
render.yaml             # Render.com deployment blueprint
DEPLOYMENT.md           # Deployment runbook
CLAUDE.md               # Deep technical reference
```
