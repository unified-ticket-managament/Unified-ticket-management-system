---
name: run
description: Launch this project's backend (FastAPI/uvicorn) and frontend (Vite) dev servers so a change can be exercised end-to-end in the browser. Use whenever asked to run, start, or preview the app, or to verify a change works live rather than just via type-checking/build.
---

# Running the Ticket Management app locally

This is a two-process app — both must be running for the UI to work, since the frontend
talks to the backend over HTTP (no built-in mocking). **Login is real JWT auth issued
solely by the separate RBAC service** (`rbac-service/`), not by this backend and not an
agent-name switcher — you need RBAC's backend running too before you can log in and
exercise anything here. See `rbac-service/CLAUDE.md`/its own `run`-equivalent if it isn't
already up.

## Prerequisites (check once, skip if already satisfied)

- `backend/.env` exists with at least `DATABASE_URL` (async, `postgresql+asyncpg://...`)
  and `JWT_SECRET_KEY`/`JWT_ALGORITHM` — `JWT_SECRET_KEY` must be **byte-for-byte identical**
  to `rbac-service/backend/.env`'s, since this service only verifies RBAC-issued tokens,
  it never issues its own. See `backend/.env.example`.
- `frontend/.env` exists with `VITE_API_BASE_URL` (this backend) and
  `VITE_RBAC_API_BASE_URL` (RBAC's `/api/v1` — login/refresh/`me` go there directly,
  everything else goes to this backend). See `frontend/.env.example`.
- Backend Python deps installed (`pip install -r requirements.txt` from `backend/`, into a
  venv — check for `.venv` at repo root first, this repo already has one).
- Frontend deps installed (`npm install` from `frontend/` — check `frontend/node_modules`
  exists first).
- Database migrations applied (`alembic upgrade head` from `backend/`). Skipping this is a
  common source of confusing 500s if a migration landed after the DB was last provisioned.
- At least one `clients` row exists with a real Account-Manager-role user as its owner, or
  inbound mail has nowhere to route. Seed with `python scripts/seed_clients.py` (from
  `backend/`) — idempotent, safe to re-run.

## Launch

**Port conflict**: this backend and RBAC's backend both default to `:8000`. Running both
at once (the normal case) means putting one of them on `:8001` — the established
convention in this repo is to move *this* service to `:8001` and leave RBAC on `:8000`,
matching `frontend/.env.example`'s comment.

```bash
cd backend && uvicorn app.main:app --port 8001
```
```bash
cd frontend && npm run dev
```

**Windows gotcha — don't use `--reload` here.** uvicorn's WatchFiles-based reloader has
been observed to silently stop picking up code changes on this platform while still
logging `Reloading...` and continuing to serve stale code — which looks exactly like a bug
in whatever you just changed. If a fix doesn't seem to take effect after a save:
1. Confirm by checking the log for a `Started server process` / `Application startup
   complete` pair *after* your edit — if you only see one `Reloading...` line with no
   fresh startup sequence, the reload silently failed.
2. Kill the *whole* process tree, not just the reported uvicorn PID — `--reload` forks a
   child process: `taskkill //F //T //PID <pid>` (Git Bash) or `Stop-Process` (PowerShell).
3. Restart without `--reload`. Repeat the kill+restart after every further backend change
   for the rest of the session — don't trust `--reload` to pick anything up.

Backend: `http://127.0.0.1:8001` (Swagger UI at `/docs`, ReDoc at `/redoc`; adjust the port
in these URLs if you didn't move it).
Frontend: `http://localhost:5173` (Vite auto-increments to 5174+ if taken — check the actual
port it prints, and if it's not already allow-listed, add it to `CORS_ORIGINS` in
`backend/app/core/config.py` or `backend/.env` or the browser will get CORS-blocked requests
that look like a generic "Network Error").

There is also a second, embedded copy of this frontend inside the RBAC Next.js app, at
`rbac-service/frontend/src/ticket-workspace/` (mounted under `http://localhost:3000/dashboard/*`
once RBAC's frontend is running). It talks to the *same* backend on `:8001` — most real
day-to-day testing in this project happens through that RBAC-embedded copy (since that's
where real users actually log in), not the standalone `:5173` app. If you changed a page or
component under `frontend/src/`, mirror the change into the `ticket-workspace/` copy
(swap `@/` imports for `@tw/`) before considering the change done — see CLAUDE.md's
dual-frontend rule.

## Verifying it's actually up

- `curl http://127.0.0.1:8001/health` should return `{"status": "healthy"}`.
- Hitting `http://127.0.0.1:8001/docs` in a browser (or
  `curl -s -o /dev/null -w '%{http_code}'`) should return 200 once uvicorn has finished starting.
- The frontend dev server prints its bound URL to stdout once ready; a blank page or console
  network errors usually mean a backend isn't reachable at `VITE_API_BASE_URL`/
  `VITE_RBAC_API_BASE_URL`, or CORS is blocking it (see above).

## Driving a real workflow to verify a change

1. Log in (via `:5173/login` or the RBAC frontend at `:3000`) as a user with an
   agent-capable role (`Staff`, `Team Lead`, `Account Manager`, `Site Lead`, `Super Admin`
   — never `Viewer`, it's 403'd from every ticketing endpoint).
2. **Create Dummy Mail** (`/create-mail`) injects an inbound email against a real client's
   `inbox_email` — it lands as a `PENDING` interaction in that client's owning Account
   Manager's inbox, not auto-assigned to anyone. (This nav item is hidden for Staff by
   design — log in as an Account Manager or use Swagger's `POST /emails/incoming` directly
   if testing as Staff.)
3. **Inbox** (`/inbox`) shows it under the Pending tab (Account Manager sees only their own
   clients' mail; Site Lead/Super Admin get an "All Inboxes" escape-hatch tab). Reply
   directly (no ticket) or create a ticket from it.
4. **Tickets** (`/tickets`) — unclaimed tickets are visible to every agent role; claim one
   to set yourself as `agent_id` and move it to `IN_PROGRESS`.
5. Reply from the ticket's composer and confirm the new interaction's
   `parent_interaction_id` threads back to the conversation's root (a real bug class here
   — see CLAUDE.md) rather than landing as a disconnected new thread.
