# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

A unified client-communication / support-ticketing platform, split into two independently-run apps in this one repo:

- `backend/` — FastAPI + SQLAlchemy 2.0 (async) + Alembic + PostgreSQL (Neon).
- `frontend/` — React 18 + TypeScript + Vite + Tailwind ("Agent Workspace" UI).

This service is one half of a two-service architecture that shares a single Postgres database with independent migration histories: an external **RBAC service** owns `users`/`roles`/permissions; this repo owns `tickets`, `interactions`, `attachments`, and `ticket_audit_logs`, and only *reads* the RBAC tables (via the `shared_models` package) to resolve names and validate that an `agent_name` belongs to an active Staff user. Never write to `users`/`roles`, and never generate a migration that touches them.

## Commands

**Backend** (run from `backend/`):
```bash
python -m venv .venv && .venv\Scripts\activate      # Windows
pip install -r requirements.txt
alembic upgrade head                                  # apply migrations
uvicorn app.main:app --reload                         # http://127.0.0.1:8000, /docs for Swagger
alembic revision --autogenerate -m "message"          # new migration
```
Requires a `.env` in `backend/` (`DATABASE_URL` async + `ALEMBIC_DATABASE_URL` sync, see `backend/.env.example`).

**Frontend** (run from `frontend/`):
```bash
npm install
npm run dev       # vite --host, http://localhost:5173
npm run build     # tsc -b && vite build — this IS the type-check step, there's no separate `tsc --noEmit` script
npm run preview
```
Requires `VITE_API_BASE_URL` in `frontend/.env`.

**Tests**: `backend/tests/*.py` exist but are currently empty placeholders, and `pytest` is not in `requirements.txt` — there is no working automated test suite yet. `backend/test_db.py` is a standalone manual DB-connectivity check (`python test_db.py`), not a pytest test. Verify changes by running the app and exercising the relevant endpoint/page (Swagger UI at `/docs`, or the frontend dev server) rather than assuming a test command exists.

**Local object storage** (optional, avoids needing a real Supabase project): `cd backend && docker compose up -d` starts MinIO; then set `STORAGE_BACKEND=s3` + `STORAGE_ENDPOINT_URL=http://localhost:9000` in `backend/.env`.

## Backend architecture

Strict layering, always in this direction — routers never touch the DB or construct responses directly:

`app/api/*` (routers, one file per resource) → `app/services/*` (business logic, orchestrates repositories) → `app/repositories/*` (the only layer that runs SQLAlchemy queries) → `app/models/*` (ORM) / `app/schemas/*` (Pydantic request/response).

**Adding a new ticket-mutating action** (status/priority change, transfer, resolve, etc.) means touching all of these in the same shape — `InteractionService` in `app/services/interaction_service.py` has one method per action (`change_status`, `change_priority`, `transfer_agent`, `resolve_ticket`) that all follow the identical recipe: fetch-or-404 → resolve the acting agent via `AuditLogService.resolve_agent_actor` → mutate the `Ticket` via `TicketRepository.update` → write an `Interaction` row via the shared `_create_ticket_interaction` helper → write an `AuditLog` row via `AuditLogService.log_event`. Copy the closest existing method rather than inventing a new shape.

**Interaction vs. AuditLog — two deliberately separate logs, not one:**
- `interactions` table (`app/models/interaction.py`) is the business-facing ticket **timeline** agents read day to day (emails, replies, notes, status/priority changes, transfers, attachment uploads). `interaction_type` is a free-form string column, not a DB enum — adding a new interaction type needs no migration. Rows can be soft-deleted (`is_visible=False`) via the hide endpoints, which the audit trail deliberately never reflects.
- `ticket_audit_logs` table (`app/models/audit_log.py`, named to avoid colliding with an unrelated `audit_logs` table already in the shared DB) is an immutable, compliance-grade record with no `update()`/`delete()` in its repository at all. `entity_type`/`event_type`/`actor_role` **are** native Postgres enums (`SQLEnum` in the model). The agent inbox (`GET /agents/{agent_name}/inbox`) is itself just a filtered query over `interactions` (`ticket_id IS NULL`, status pending/assigned) — there's no separate inbox table.

**Postgres-enum migration gotcha**: `AuditEventType` (and `AuditEntityType`, `ActorRole`, `TicketStatus`, `TicketPriority`, etc.) are Python `str, Enum` classes mapped via `SQLEnum(..., name="...")`, which SQLAlchemy renders as a native Postgres `ENUM` type. Adding a new member to the Python enum is **not enough** — the deployed Postgres type must also be widened, or writing that value crashes with `InvalidTextRepresentationError`. Always follow up with an Alembic migration doing `op.execute("ALTER TYPE <enum_name> ADD VALUE IF NOT EXISTS '<VALUE>'")` (downgrade is a no-op — Postgres can't drop enum labels). See `backend/alembic/versions/7a2d4e9f1c3b_add_email_received_audit_event_type.py` and `4e6b8a1d3c5f_add_ticket_resolved_audit_event_type.py` for the pattern. This migration must run standalone (no other DDL in the same transaction) and, if enqueued in the same PR, generally needs to be applied before code that writes the new value goes live.

**Access control, "acting as", and the audit actor model**: there is no real auth layer. Every mutating/reading route takes an optional `agent_name` query param — the "acting as" identity. `app/services/access_control.py` enforces: a ticket assigned to an agent is visible only to that agent; unassigned tickets are visible to everyone; interactions/audit logs inherit their parent ticket's visibility. Separately, `AuditLogService.resolve_agent_actor` (`app/services/audit_log_service.py`) turns that same `agent_name` string into the `(actor_id, actor_name, actor_role)` triple written onto every audit row — `actor_name`/`actor_role` are snapshotted at write time (not joined at read time) so the trail doesn't change retroactively if a user is renamed or removed. An unresolvable/absent `agent_name` becomes `actor_role=SYSTEM`, which should mean "genuinely automatic" (e.g. auto-assignment), not "we forgot to pass a name."

**Storage abstraction**: `app/storage/base.py` defines `StorageService`; `supabase_storage.py` and `s3_storage.py` are the two implementations, selected at runtime by `STORAGE_BACKEND` (`app/storage/__init__.py`). A misconfigured backend raises `StorageConfigurationError`, caught by a global handler in `app/main.py` that returns a clean 503 instead of a raw 500 — don't add another try/except around storage calls, extend that handler if new failure modes need surfacing.

## Frontend architecture

Layering: `pages/*` (routed screens) → `components/{ticket,inbox,layout,common}/*` → `context/*` (global state) → `api/*` (one file per backend resource, thin axios wrappers) → `lib/*` (pure formatting/derivation helpers). `@/` resolves to `frontend/src` (see `vite.config.ts` / `tsconfig.json`) — use it instead of relative `../../` imports.

**Every API call goes through `useApiAction`** (`hooks/useApiAction.ts`), which wraps an `api/*` function with loading state and automatic toast feedback (`context/ToastContext.tsx`) — including guarding against stale responses when the acting agent or route changes mid-request. Don't hand-roll try/catch + loading state around a new API call; wrap it with `useApiAction` and it gets error toasts for free. Backend error `detail` strings are normalized into a single readable `Error` message by an axios response interceptor in `api/client.ts`.

**`WorkflowContext`** (`context/WorkflowContext.tsx`) holds the single agent-identity string (`agentName`, the same "acting as" value the backend expects) plus the currently-open ticket and its timeline, shared across `TicketDetailPage` and its child panels (`TicketHeader`, `TicketTimeline`, `TicketDetails`, `TicketActions`, `TicketAuditLog`) instead of prop-drilling.

**Adding a ticket action tile** (see `components/ticket/TicketActions.tsx`): each action is an `ActionTile` that opens one of a small set of modals, calls its `api/interaction.ts` function through `useApiAction`, then calls the parent's `onActionComplete` to refetch the ticket + timeline + audit log. Any new interaction/audit-event type needs a matching entry in `lib/interactionMeta.ts` (timeline icon/label/summary) and `lib/auditLogMeta.ts` (audit panel icon/label) or it renders with a generic fallback.

**Dashboard stats** (`pages/Dashboard.tsx`) are all derived client-side from the single `listTickets` + `getAgentInbox` fetch in one `useEffect` — there is no dedicated stats endpoint. New KPI cards should generally be a `filter`/`derive` over the already-fetched `tickets` array rather than a new network call.

**Theme**: light/dark is CSS-variable-driven (`src/index.css`) + Tailwind `darkMode: "class"`, toggled in `Topbar` and persisted to `localStorage`; an inline script in `index.html` applies the saved theme before React mounts to avoid a flash of the wrong theme.
