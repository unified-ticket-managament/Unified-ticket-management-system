# Unified Ticket Management System (UTMS)

A combined RBAC (authentication, users, roles, permissions) and support-ticketing platform — one product, built by merging what were originally two independent systems.

## Architecture at a glance

| Directory | What it is | Runs on |
|---|---|---|
| `unified-frontend/` | The shell application — login, RBAC (Users/Roles/Audit Logs/Settings), and an embedded copy of the ticket workspace (Mail, Tickets, Reports, per-role dashboards). Next.js 16. **This is the primary, currently-maintained frontend.** | `:3000` |
| `unified-backend/` | A single FastAPI process serving both the RBAC API (`/api/v1/...`) and the Ticketing API (unprefixed — `/tickets`, `/inbox`, ...). RBAC is the sole issuer of JWTs; Ticketing verifies them. | `:8000` |
| `ticketing-service/` | The standalone Vite/React ticket-workspace app this product started from, with its own login flow. Still runs independently, but `unified-frontend`'s embedded copy has since pulled ahead (see its own `CLAUDE.md`'s "Mail v2" section) and is not kept in sync automatically. Optional — only needed if you're testing this app directly. | `:5173` |
| `shared_models/` | The one real copy of the `User`/`Role` SQLAlchemy models, installed as a local editable package by `unified-backend`. | — |

Both API domains share **one physical PostgreSQL database** (Neon) but keep independent Alembic migration histories (`unified-backend/alembic_rbac/`, `unified-backend/alembic_ticketing/`).

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
