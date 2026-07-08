---
name: run
description: Launch this project's backend (FastAPI/uvicorn) and frontend (Vite) dev servers so a change can be exercised end-to-end in the browser. Use whenever asked to run, start, or preview the app, or to verify a change works live rather than just via type-checking/build.
---

# Running the Ticket Management app locally

This app needs **three** processes running, not two: this service's backend and frontend,
plus the **RBAC service's backend**, since RBAC is the sole issuer of the login tokens this
app's frontend needs. There is no local login without it — Ticketing's own backend only
verifies tokens, it never issues them.

## Prerequisites (check once, skip if already satisfied)

- `backend/.env` exists with `DATABASE_URL` (async, `postgresql+asyncpg://...`),
  `ALEMBIC_DATABASE_URL` (sync, `postgresql+psycopg2://...`), and `JWT_SECRET_KEY` /
  `JWT_ALGORITHM` — see `backend/.env.example`. `JWT_SECRET_KEY` must be byte-identical to
  the value in `../rbac-service/backend/.env`, or every token this service tries to verify
  will 401 as invalid.
- `frontend/.env` exists with `VITE_API_BASE_URL` (this service's own API, typically
  `http://localhost:8000` or `:8001` — see port-conflict note below) and
  `VITE_RBAC_API_BASE_URL` (RBAC's API, e.g. `http://localhost:8000/api/v1` if RBAC runs on
  the default port and this service is moved to `:8001`).
- `../rbac-service/backend/.env` exists and that backend can actually boot — Ticketing's
  frontend calls it directly for login/refresh/`me`.
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
convention in this repo is to move *this* service to `:8001` and leave RBAC on `:8000`.

```bash
cd ../rbac-service/backend && uvicorn app.main:app --reload
```
```bash
cd backend && uvicorn app.main:app --port 8001
```
```bash
cd frontend && npm run dev
```

**Windows gotcha — don't use `--reload` on the Ticketing backend.** uvicorn's WatchFiles-based
reloader has been observed to silently stop picking up code changes on this platform while
still logging `Reloading...` and continuing to serve stale code — which looks exactly like a
bug in whatever you just changed. If a fix doesn't seem to take effect after a save:
1. Confirm by checking the log for a `Started server process` / `Application startup
   complete` pair *after* your edit — if you only see one `Reloading...` line with no
   fresh startup sequence, the reload silently failed.
2. Kill the *whole* process tree, not just the reported uvicorn PID — `--reload` forks a
   child process: `taskkill //F //T //PID <pid>` (Git Bash) or `Stop-Process` (PowerShell).
3. Restart without `--reload`. Repeat the kill+restart after every further backend change
   for the rest of the session — don't trust `--reload` to pick anything up.

**Config changes need a restart, not just a save.** Both backends cache their `Settings` via
`@lru_cache` at startup; `--reload` only restarts on Python file changes, not `.env` edits.
If you change `JWT_SECRET_KEY`, `SUPABASE_*`, or any other env var while a backend is
already running, kill and restart it — otherwise it keeps using the old values and errors
look like a code bug when they're actually just a stale process.

RBAC backend: `http://127.0.0.1:8000` (Swagger at `/docs`). Ticketing backend: whichever
port you chose (Swagger at `/docs` there too). Frontend: `http://localhost:5173` (Vite
auto-increments to 5174+ if taken — check the actual port it prints, and if it's not
5173/5174, add it to `CORS_ORIGINS` in both backends' config/`.env`, or the browser will get
CORS-blocked requests that look like a generic "Network Error").

There is also a second, embedded copy of this frontend inside the RBAC Next.js app, at
`rbac-service/frontend/src/ticket-workspace/` (mounted under `http://localhost:3000/dashboard/*`
once RBAC's frontend is running). It talks to the *same* Ticketing backend. Most real
day-to-day testing in this project happens through that RBAC-embedded copy (since that's
where real users actually log in), not the standalone `:5173` app. If you changed a page or
component under `frontend/src/`, mirror the change into the `ticket-workspace/` copy
(swap `@/` imports for `@tw/`) before considering the change done — see CLAUDE.md's
dual-frontend rule.

## Verifying it's actually up

- `curl http://127.0.0.1:8000/health` (RBAC) and the Ticketing backend's equivalent should
  both return `{"status": "healthy"}`.
- Hitting each backend's `/docs` in a browser (or `curl -s -o /dev/null -w '%{http_code}'`)
  should return 200 once uvicorn has finished starting.
- The frontend dev server prints its bound URL to stdout once ready; a blank page or console
  network errors usually mean one of the backends isn't reachable at `VITE_API_BASE_URL`/
  `VITE_RBAC_API_BASE_URL`, or CORS is blocking it (see above).

## Driving a real workflow to verify a change

1. Log in (via `:5173/login` or the RBAC frontend at `:3000`) as a user with an
   agent-capable role (`Staff`, `Team Lead`, `Account Manager`, `Site Lead`, `Super Admin`
   — never `Viewer`, it's 403'd from every ticketing endpoint). RBAC's own `scripts/seed.py`
   has demo credentials for every role.
2. **Create Dummy Mail** (`/create-mail`) injects an inbound email against a real client's
   `inbox_email` — it lands as a `PENDING` interaction in **that client's owning Account
   Manager's inbox specifically** (routing is 1:1 via `clients.account_manager_id`, never
   round-robin or least-busy-agent), not auto-assigned to any Staff member. This nav item is
   hidden for Staff and Team Lead by design — log in as an Account Manager/Site Lead/Super
   Admin, or use Swagger's `POST /emails/incoming` directly if testing as one of those roles.
3. **Mail** (`/inbox`, nav label "Mail") shows it under the Inbox/Pending view in the left
   sidebar (Account Manager sees only their own clients' mail; Team Lead/Site Lead/Super
   Admin get an "All Inboxes" escape-hatch view). From there: reply directly (no ticket) or
   save the reply as a draft first and send it later, tag it and/or file it into a custom
   folder, snooze it (it disappears from Inbox until the snooze time passes, then
   resurfaces on its own), claim it ("Assign to me"), archive it (Informational/Archive —
   no ticket needed), create a ticket from it, or attach it to an existing ticket. Sent
   replies and saved drafts get their own sidebar views (Sent/Drafts).
4. **Tickets** (`/tickets`) — unclaimed tickets are visible to every agent role and anyone
   can self-claim one (sets `agent_id`, moves it to `IN_PROGRESS`); only Team Lead/Account
   Manager/Site Lead/Super Admin can transfer a ticket to a *different* named agent — Staff
   gets a 403 on that specific action.
5. Reply from the ticket's composer and confirm the new interaction's
   `parent_interaction_id` threads back to the conversation's root (a real bug class here
   — see CLAUDE.md) rather than landing as a disconnected new thread.
6. On a ticket's detail page, use "Related Tickets" to link it to a second ticket and
   confirm the link shows up on **both** tickets' detail pages (it's written symmetrically
   — see CLAUDE.md), then unlink and confirm it disappears from both.
