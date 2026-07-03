---
name: run
description: Launch this project's backend (FastAPI/uvicorn) and frontend (Vite) dev servers so a change can be exercised end-to-end in the browser. Use whenever asked to run, start, or preview the app, or to verify a change works live rather than just via type-checking/build.
---

# Running the Ticket Management app locally

This is a two-process app — both must be running for the UI to work, since the frontend
talks to the backend over HTTP (no built-in mocking).

## Prerequisites (check once, skip if already satisfied)

- `backend/.env` exists with at least `DATABASE_URL` (async, `postgresql+asyncpg://...`) and
  `ALEMBIC_DATABASE_URL` (sync, `postgresql+psycopg2://...`) — see `backend/.env.example`.
- `frontend/.env` exists with `VITE_API_BASE_URL` (typically `http://localhost:8000`).
- Backend Python deps installed (`pip install -r requirements.txt` from `backend/`, into a
  venv — check for `.venv` at repo root first, this repo already has one).
- Frontend deps installed (`npm install` from `frontend/` — check `frontend/node_modules`
  exists first).
- Database migrations applied (`alembic upgrade head` from `backend/`). Skipping this is a
  common source of confusing 500s if a migration landed after the DB was last provisioned.

## Launch

Run both as background processes so you can keep working while they're up:

```bash
cd backend && uvicorn app.main:app --reload
```
```bash
cd frontend && npm run dev
```

Backend: `http://127.0.0.1:8000` (Swagger UI at `/docs`, ReDoc at `/redoc`).
Frontend: `http://localhost:5173` (Vite auto-increments to 5174+ if taken — check the actual
port it prints, and if it's not 5173/5174, add it to `CORS_ORIGINS` in `backend/app/core/config.py`
or `backend/.env` or the browser will get CORS-blocked requests that look like a generic
"Network Error").

## Verifying it's actually up

- `curl http://127.0.0.1:8000/health` should return `{"status": "healthy"}`.
- Hitting `http://127.0.0.1:8000/docs` in a browser (or `curl -s -o /dev/null -w '%{http_code}'`)
  should return 200 once uvicorn has finished starting.
- The frontend dev server prints its bound URL to stdout once ready; a blank page or console
  network errors usually mean the backend isn't reachable at `VITE_API_BASE_URL`, or CORS is
  blocking it (see above).

## Driving a real workflow to verify a change

There's no seed-data script — the demo data path is: open **Create Dummy Mail** in the UI
(`/create-mail`) to inject an inbound email (routes to whichever active Staff agent has the
fewest open tickets), then act on it from the **Inbox** or promote it to a ticket. Use the
agent-name switcher (`WorkflowContext`) to view the workspace as different acting agents, since
ticket/interaction visibility is scoped to the assigned agent.
