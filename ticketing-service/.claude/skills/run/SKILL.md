---
name: run
description: Launch this project's backend (FastAPI/uvicorn) and frontend (Vite) dev servers so a change can be exercised end-to-end in the browser. Use whenever asked to run, start, or preview the app, or to verify a change works live rather than just via type-checking/build.
---

# Running the Ticket Management app locally

**This repo's own `backend/` is now an empty shell** — `rbac-service/backend` and
`ticketing-service/backend` were merged into one FastAPI process, `unified-backend/`
(sibling directory at the monorepo root), with `app/rbac/` and `app/ticketing/` as its two
subpackages. Every `backend/...` path below should be read as `unified-backend/app/ticketing/...`
(or `unified-backend/alembic_ticketing/...` for migrations) — see the root `CLAUDE.md`'s
"Backend unification" section for the full story. This app needs **two** processes now, not
three: the one unified backend, and this frontend.

## Prerequisites (check once, skip if already satisfied)

- `unified-backend/.env` exists with at least `DATABASE_URL` (async, `postgresql+asyncpg://...`),
  `ALEMBIC_DATABASE_URL` (sync, `postgresql+psycopg2://...`), and `JWT_SECRET_KEY`/`JWT_ALGORITHM`
  — this is the one shared config for both domains now, not a separate `.env` per backend.
- `frontend/.env` exists with `VITE_API_BASE_URL` and `VITE_RBAC_API_BASE_URL` **both pointed at
  the same unified backend** (e.g. both `http://localhost:8000`, one with `/api/v1` and one
  without) — not two different ports like before the merge.
- Backend Python deps installed (`pip install -r requirements.txt` from `unified-backend/`, into
  a venv — check for `.venv` at the monorepo root first, it already exists).
- Frontend deps installed (`npm install` from `frontend/` — check `frontend/node_modules`
  exists first).
- Database migrations applied for **both** chains: `alembic -c alembic_rbac/alembic.ini upgrade head`
  and `alembic -c alembic_ticketing/alembic.ini upgrade head`, both from `unified-backend/`.
  Skipping this is a common source of confusing 500s if a migration landed after the DB was
  last provisioned.
- At least one `clients` row exists with a real Account-Manager-role user as its owner, or
  inbound mail has nowhere to route. Seed with `python -m scripts.ticketing_seed.seed_clients`
  (from `unified-backend/`) — idempotent, safe to re-run.

## Launch

```bash
cd unified-backend && bash scripts/start.sh
```
(or, run the pieces individually: both `alembic upgrade head` invocations above, then
`uvicorn app.main:app --reload --port 8000` from `unified-backend/`)
```bash
cd frontend && npm run dev
```

Backend: `http://127.0.0.1:8000` — one port now, serving both RBAC (`/api/v1/...`) and
Ticketing (unprefixed — `/tickets`, `/inbox`, ...) routes from the same process. There is no
more `:8001` — if you still have `VITE_API_BASE_URL`/`NEXT_PUBLIC_TICKETING_API_URL` pointed at
8001 anywhere, that's a stale pre-merge config (see the matching Known Issues entry in
`unified-frontend/CLAUDE.md`), not a real second backend.
Frontend: `http://localhost:5173` (Vite auto-increments to 5174+ if taken — check the actual
port it prints, and if it's not 5173/5174, add it to `CORS_ORIGINS` in `unified-backend/app/core/config.py`
or `unified-backend/.env` or the browser will get CORS-blocked requests that look like a generic
"Network Error").

## Verifying it's actually up

- `curl http://127.0.0.1:8000/health` should return `{"status": "healthy"}`.
- Hitting `http://127.0.0.1:8000/docs` in a browser (or `curl -s -o /dev/null -w '%{http_code}'`)
  should return 200 once uvicorn has finished starting — this one Swagger UI now covers both
  RBAC and Ticketing routes.
- The frontend dev server prints its bound URL to stdout once ready; a blank page or console
  network errors usually mean the backend isn't reachable at `VITE_API_BASE_URL`/
  `VITE_RBAC_API_BASE_URL` (double-check both really point at the same unified backend), or
  CORS is blocking it (see above).

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
7. **Edit Access** (the "Edit Access" panel on a ticket's detail page): log in as `Staff`
   on a ticket *not* assigned to them and confirm "Request Edit Access" is the only option
   (replying/note-adding/priority-changing 403s until access is granted). Submit a request
   with a reason, then log in as `Account Manager`/`Site Lead`/`Super Admin` (any role
   holding `ticket:editother_ticket` by default — Team Lead too, if its own category matches
   the ticket's) and approve or reject it from the same panel. Confirm an approval lets the
   Staff member act on the ticket (log back in as them, or just re-check via Swagger with
   their token) and that both the ticket's own Timeline and its Audit Trail show
   `EDIT_ACCESS_REQUESTED`/`EDIT_ACCESS_APPROVED` (or `_REJECTED`) — see CLAUDE.md's "Edit
   access requests" section. A rejected request should leave the requester exactly as
   restricted as before. This is a different, deliberately separate mechanism from
   `rbac-service`'s ticket-*scoped* Permission Request flow (`ticket:editother_ticket`
   granted for one specific ticket via an rbac-owned override) — see CLAUDE.md's note on how
   the two coexist.
