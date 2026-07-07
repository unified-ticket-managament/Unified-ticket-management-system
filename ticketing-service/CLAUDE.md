# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

A unified client-communication / support-ticketing platform, split into two independently-run apps in this one repo:

- `backend/` — FastAPI + SQLAlchemy 2.0 (async) + Alembic + PostgreSQL (Neon).
- `frontend/` — React 18 + TypeScript + Vite + Tailwind ("Agent Workspace" UI).

This service is one half of a two-service architecture that shares a single Postgres database with independent migration histories: an external **RBAC service** owns `users`/`roles`/permissions; this repo owns `tickets`, `interactions`, `attachments`, `ticket_audit_logs`, and `clients`, and only *reads* the RBAC tables (via the `shared_models` package) to resolve names and roles. Never write to `users`/`roles`, and never generate a migration that touches them.

**There is a second, embedded copy of this frontend** at `rbac-service/frontend/src/ticket-workspace/` (imported via a `@tw/*` alias, mounted inside RBAC's Next.js app under `/dashboard/*`). It is not a build artifact — it's a hand-mirrored copy of `frontend/src/`. **Any change to `frontend/src/` that touches shared behavior (types, API contracts, pages under `pages/`, components under `components/`) must be applied to both copies**, swapping `@/` imports for `@tw/` in the mirrored file. This is the single most common way to introduce a "works in one app, broken in the other" bug in this codebase — always grep the other tree for the same filename before considering a frontend change done.

## The domain model (client → interaction → ticket)

- **Clients** (`app/models/client.py`) are companies, not individual people — each one is onboarded with a dedicated shared inbox address (`inbox_email`, e.g. `abc@probeps.com`) and an owning **Account Manager** (`account_manager_id`, FK → `users`). Inbound email is resolved by matching `to_email` against `clients.inbox_email`, never by who sent it.
- **Every inbound email becomes an `Interaction` first** (`interaction_type="EMAIL"`, `ticket_id=NULL`, `status=PENDING`) — landing in the owning Account Manager's inbox, not auto-assigned to any Staff agent (auto-assignment was removed; there is no "least-loaded agent" logic anywhere in this service anymore). Only when an agent decides it's an actionable issue does it get promoted to a `Ticket`.
- **Threading** is real columns on `interactions`, not payload JSON, because inbox queries filter on them directly: `client_id`, `parent_interaction_id` (self-FK — `NULL` means "this row is a thread root"; set means "this row replies under that root"), `received_at` (mailbox arrival time reported by the transport layer — the SLA clock start, distinct from `created_at` which is just when our backend happened to persist the row; see `app/models/interaction.py`'s column comments for why the distinction matters).
- **Every code path that creates a reply-type interaction must set `parent_interaction_id` to the conversation's thread root**, resolved via `existing_interaction.parent_interaction_id or existing_interaction.interaction_id` (walk up once — roots never chain). Forgetting this is a real bug class here: it happened in `InteractionService.add_reply` (ticket-level replies) and in `EmailService.receive_email`'s "already ticketed" branch, both fixed by threading through the resolved root before creating the row. If you add a new interaction-creating method that represents a reply/follow-up in an email conversation, thread it the same way — `_create_ticket_interaction`'s `parent_interaction_id` param exists for exactly this, and defaults to `None` for the other interaction types (notes, status/priority changes, transfers, claims) that aren't part of the client email thread.
- **Tickets** carry both `client_id` (legacy FK → `users`, nullable, only ever set on tickets created before the client-company model — do not write to it going forward) and `client_company_id` (FK → `clients`, the current one). `ticket_type` is the ticket's category — a plain `String(50)` column, but request schemas (`TicketCreate`, `TicketFromInteractionCreate`) constrain it to the fixed `TicketCategory` enum (`app/enums/ticket_enums.py`: `TECHNICAL`, `BILLING`, `HIRING`, `GENERAL`) — **this is a Pydantic-only enum, deliberately not a Postgres enum** (unlike `TicketStatus`/`TicketPriority`), so extending the category list needs no migration. `TicketResponse.ticket_type` stays plain `str` so older free-text rows (pre-dating the fixed list) still deserialize.
- **Outbound replies build a real envelope** (`app/services/email_envelope.py`'s `build_reply_envelope`): From = the client's shared inbox, To = the original sender, `Re:`-prefixed subject (no double-prefixing), a generated `message_id`, References chaining, and the Account Manager auto-CC'd. Stored as `payload.envelope` + `payload.dispatch_status` (`QUEUED`/`NO_RECIPIENT`) on the `REPLY` interaction, then handed to `app/services/outbound_dispatcher.py`'s `OutboundDispatcher` — currently a logging no-op; whichever task owns the actual transport/webhook layer replaces this, not the call sites.

## Roles

RBAC's actual roles are **Super Admin, Site Lead, Account Manager, Team Lead, Staff, Viewer** — there is no role literally named `"Manager"` (an older draft of this system assumed one; if you see `"Manager"` hardcoded anywhere as a role-name string, it's dead/wrong, not a role to design around). `app/services/access_control.py` is the source of truth:
- `AGENT_ROLE_NAMES` — every role except Viewer; who can authenticate as an agent at all (`get_current_agent` 403s anyone else). Site Lead and Account Manager were both missing from this set at points during development, which silently 403'd every ticketing endpoint for real users holding those roles — if a role can't do anything in Ticketing, check this set first.
- `SUPERVISOR_ROLE_NAMES` — who bypasses ownership scoping (see current file for the exact set; it has shifted more than once as the org-hierarchy model was refined, so don't assume a value from memory — re-read it).
- `ACCOUNT_MANAGER_ROLE_NAME` — the literal role string (`"Account Manager"`) that `clients.account_manager_id` must point at; `ClientService.create` validates against it, and `TicketService._resolve_owned_client_ids` uses it to decide whether the caller's ticket list/detail access is scoped to only their own clients.
- Category-based ticket routing for Team Lead/Staff (each owning a slice of the shared pool by ticket category, plus Team Lead monitoring their direct reports via the existing `teamlead_id` column on `User`) is a known, explicitly-deferred gap — not implemented. Don't assume it exists.

## Commands

**Backend** (run from `backend/`):
```bash
python -m venv .venv && .venv\Scripts\activate      # Windows
pip install -r requirements.txt
alembic upgrade head                                  # apply migrations
uvicorn app.main:app --reload                         # http://127.0.0.1:8000, /docs for Swagger
uvicorn app.main:app --port 8001                      # when RBAC's backend is also running (it defaults to 8000 too)
alembic revision --autogenerate -m "message"          # new migration
```
Requires a `.env` in `backend/` (`DATABASE_URL` async, `JWT_SECRET_KEY`/`JWT_ALGORITHM` — must be byte-for-byte identical to RBAC's, see `backend/.env.example`).

**Windows gotcha — `--reload` is unreliable in this dev environment**: uvicorn's WatchFiles-based reloader has silently failed to pick up code changes more than once during development here — it logs `Reloading...` and keeps serving stale code, which reads exactly like a bug in the changed code itself. If a fix "isn't taking effect" after a save, don't trust `--reload` — kill the whole process tree (`taskkill //F //T //PID <pid>`, not just the reported uvicorn PID, since `--reload` forks a child) and restart without `--reload`.

**Frontend** (run from `frontend/`):
```bash
npm install
npm run dev       # vite --host, http://localhost:5173
npm run build     # tsc -b && vite build — this IS the type-check step, there's no separate `tsc --noEmit` script
npm run preview
```
Requires `VITE_API_BASE_URL` (this service, typically `:8000` or `:8001`) and `VITE_RBAC_API_BASE_URL` (RBAC's `/api/v1`, typically `:8000/api/v1`) in `frontend/.env` — see `frontend/.env.example`. Login/refresh/`me` are RBAC's alone; this frontend calls RBAC directly for those and this backend for everything else.

**Tests**: `backend/tests/*.py` exist but are currently empty placeholders, and `pytest` is not in `requirements.txt` — there is no working automated test suite yet. `backend/test_db.py` is a standalone manual DB-connectivity check (`python test_db.py`), not a pytest test. Verify changes by running the app and exercising the relevant endpoint/page (Swagger UI at `/docs`, or the frontend dev server) rather than assuming a test command exists.

**Local object storage** (optional, avoids needing a real Supabase project): `cd backend && docker compose up -d` starts MinIO; then set `STORAGE_BACKEND=s3` + `STORAGE_ENDPOINT_URL=http://localhost:9000` in `backend/.env`.

**Demo data**: `python scripts/seed_clients.py` (from `backend/`, venv active) onboards a few demo client companies against real active Account-Manager-role users already in the shared `users` table — idempotent, safe to re-run. Seed at least one Account Manager in RBAC first if it reports finding none.

## Backend architecture

Strict layering, always in this direction — routers never touch the DB or construct responses directly:

`app/api/*` (routers, one file per resource: `email`, `agent`, `client`, `inbox`, `ticket`, `interaction`, `attachment` — all registered in `app/main.py`) → `app/services/*` (business logic, orchestrates repositories) → `app/repositories/*` (the only layer that runs SQLAlchemy queries) → `app/models/*` (ORM) / `app/schemas/*` (Pydantic request/response).

**Auth is real JWT, not a query param.** `app/dependencies/auth.py`'s `get_current_user` decodes an RBAC-issued access token (`app/auth/jwt.py`, decode-only — this service never issues tokens, don't add `create_access_token` here) and re-resolves the user from the shared `users` table on every request (so a deactivated account is caught immediately, not just at next login); `get_current_agent` additionally requires `role.name in AGENT_ROLE_NAMES`. There is no more `agent_name` query-param "acting as" model — if you see that pattern referenced anywhere (old comments, stale skill docs), it predates the real-auth migration and no longer applies.

**Adding a new ticket-mutating action** (status/priority change, transfer, resolve, etc.) means touching all of these in the same shape — `InteractionService` in `app/services/interaction_service.py` has one method per action (`change_status`, `change_priority`, `transfer_agent`, `add_reply`, `claim_ticket`) that all follow the identical recipe: fetch-or-404 → resolve the acting agent via `AuditLogService.resolve_agent_actor(current_user)` → mutate the `Ticket` via `TicketRepository.update` (or a dedicated conditional-update method, e.g. `claim`'s race guard) → write an `Interaction` row via the shared `_create_ticket_interaction` helper → write an `AuditLog` row via `AuditLogService.log_event`. Copy the closest existing method rather than inventing a new shape. See the `add-ticket-action` skill.

**Interaction vs. AuditLog — two deliberately separate logs, not one:**
- `interactions` table (`app/models/interaction.py`) is the business-facing ticket **timeline** agents read day to day (emails, replies, notes, status/priority changes, transfers, claims, attachment uploads). `interaction_type` is a free-form string column, not a DB enum — adding a new interaction type needs no migration. Rows can be soft-deleted (`is_visible=False`) via the hide endpoints, which the audit trail deliberately never reflects.
- `ticket_audit_logs` table (`app/models/audit_log.py`, named to avoid colliding with an unrelated `audit_logs` table already in the shared DB) is an immutable, compliance-grade record with no `update()`/`delete()` in its repository at all. `entity_type`/`event_type`/`actor_role` **are** native Postgres enums (`SQLEnum` in the model).
- The Account Manager inbox (`GET /inbox`) is itself just a filtered query over `interactions` (`app/repositories/interaction_repository.py`'s `list_inbox`: thread roots only — `parent_interaction_id IS NULL`, `interaction_type == "EMAIL"` — filtered by `view` (`pending`/`replied`/`ticketed`/`all`) and optionally scoped to one Account Manager via a join against `clients.account_manager_id`) — there's no separate inbox table.

**Postgres-enum migration gotcha**: `AuditEventType` (and `AuditEntityType`, `ActorRole`, `TicketStatus`, `TicketPriority`, `InteractionStatus`, `InteractionDirection`) are Python `str, Enum` classes mapped via `SQLEnum(..., name="...")`, which SQLAlchemy renders as a native Postgres `ENUM` type. Adding a new member to the Python enum is **not enough** — the deployed Postgres type must also be widened, or writing that value crashes with `InvalidTextRepresentationError`. Always follow up with an Alembic migration doing `op.execute("ALTER TYPE <enum_name> ADD VALUE IF NOT EXISTS '<VALUE>'")` (downgrade is a no-op — Postgres can't drop enum labels). See the **add-postgres-enum-value** skill. `TicketCategory` (`app/enums/ticket_enums.py`) is the counter-example: it's a plain Python enum used only for Pydantic request validation, deliberately *not* wired into `Ticket.ticket_type`'s column type — don't "fix" it into a `SQLEnum` without a reason, that would turn a migration-free constant list into one that needs a migration every time it changes.

**Storage abstraction**: `app/storage/base.py` defines `StorageService`; `supabase_storage.py` and `s3_storage.py` are the two implementations, selected at runtime by `STORAGE_BACKEND` (`app/storage/__init__.py`). A misconfigured backend raises `StorageConfigurationError`, caught by a global handler in `app/main.py` that returns a clean 503 instead of a raw 500 — don't add another try/except around storage calls, extend that handler if new failure modes need surfacing.

## Frontend architecture

Layering: `pages/*` (routed screens) → `components/{ticket,inbox,layout,common}/*` → `context/*` (global state) → `api/*` (one file per backend resource, thin axios wrappers) → `lib/*` (pure formatting/derivation helpers). `@/` resolves to `frontend/src` (`@tw/` to the same tree inside the RBAC-embedded copy) — use it instead of relative `../../` imports. Remember the dual-copy rule from the top of this file.

**Every API call goes through `useApiAction`** (`hooks/useApiAction.ts`), which wraps an `api/*` function with loading state and automatic toast feedback (`context/ToastContext.tsx`) — including guarding against stale responses when the route changes mid-request. Don't hand-roll try/catch + loading state around a new API call; wrap it with `useApiAction` and it gets error toasts for free. Backend error `detail` strings are normalized into a single readable `Error` message by an axios response interceptor in `api/client.ts`.

**`AuthContext`** (`context/AuthContext.tsx`) is the real identity now — login/logout against RBAC, `currentUser` (with `.role`) resolved from `/me`. There is no agent-name switcher anymore. **`WorkflowContext`** (`context/WorkflowContext.tsx`) holds the currently-open ticket, its timeline, and the selected inbox email/thread, shared across `TicketDetailPage`/`InboxPage` and their child panels instead of prop-drilling.

**Role-gated nav/UI**: `AgentInbox.tsx`'s `SUPERVISOR_ROLES` constant (mirroring the backend's `SUPERVISOR_ROLE_NAMES`) decides who gets the "All Inboxes" escape-hatch tab vs. the AM-scoped Pending/Replied/Ticketed tabs. `Sidebar.tsx`'s nav items can be role-conditional (e.g. `hideForStaff` — "Create Dummy Mail" is hidden for Staff) — check both role-name sets against `access_control.py` before assuming they're in sync; they've drifted from each other before.

**Adding a ticket action tile** (see `components/ticket/TicketActions.tsx`): each action is an `ActionTile` that opens one of a small set of modals, calls its `api/interaction.ts` function through `useApiAction`, then calls the parent's `onActionComplete` to refetch the ticket + timeline + audit log. Any new interaction/audit-event type needs a matching entry in `lib/interactionMeta.ts` (timeline icon/label/summary) and `lib/auditLogMeta.ts` (audit panel icon/label) or it renders with a generic fallback.

**Dashboard stats** (`pages/Dashboard.tsx`) are derived client-side from `listTickets` + `getInbox` fetched once in a `useEffect` — there is no dedicated stats endpoint. New KPI cards should generally be a `filter`/`derive` over the already-fetched `tickets` array rather than a new network call.

**Theme**: light/dark is CSS-variable-driven (`src/index.css`) + Tailwind `darkMode: "class"`, toggled in `Topbar` and persisted to `localStorage`; an inline script in `index.html` applies the saved theme before React mounts to avoid a flash of the wrong theme. Inside the RBAC-embedded copy, `.tm-scope` (RBAC's `globals.css`) remaps this multi-hue palette onto RBAC's own monochrome one instead.
