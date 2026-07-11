# Ticket Management System

## Overview

The Ticket Management System is a unified client communication and support
ticketing platform. It has two parts:

- **Backend** (`backend/`) — a FastAPI service that manages tickets,
  interactions, attachments, and agent-inbox routing.
- **Frontend** (`frontend/`) — a React + TypeScript "Agent Workspace" that
  support agents use to triage inbound email, create/manage tickets, and
  audit activity.

This project is part of a microservice architecture where:

- **RBAC Service** manages authentication, users, roles, and permissions.
- **Ticket Management Service** (this repo) manages tickets, interactions,
  and attachments, and serves the agent-facing UI.

Both services share the same PostgreSQL database while maintaining
independent migration histories.

---

# Project Objective

The objective of this service is to:

- Create support tickets
- Assign / transfer tickets between staff, with full ownership handoff
- Track ticket interactions (emails, replies, notes, attachments, status
  and priority changes)
- Scope ticket and interaction visibility to the assigned agent only
- Store ticket attachments
- Support soft-delete ("hide") of interactions without destroying the
  audit trail
- Integrate with the RBAC service using shared models
- Provide a production-quality, accessible, responsive UI for day-to-day
  agent use

---

# Project Structure

```
Phase_1/
│
├── backend/
│   ├── alembic/                 # Database migrations
│   │   ├── versions/
│   │   └── env.py
│   │
│   ├── app/
│   │   ├── api/                 # API routes (email, agent, ticket, interaction, attachment)
│   │   ├── core/                # Configuration, logging, security
│   │   ├── database/            # Database connection / session
│   │   ├── enums/                # Ticket, interaction & audit enums (incl. ActorRole)
│   │   ├── middleware/           # Logging & security headers
│   │   ├── models/               # SQLAlchemy models (incl. AuditLog)
│   │   ├── repositories/         # Database operations
│   │   ├── schemas/              # Pydantic schemas
│   │   ├── services/             # Business logic (access_control, audit_log_service, ...)
│   │   ├── storage/               # Object storage backends (Supabase / S3-compatible)
│   │   └── main.py               # FastAPI entry point
│   │
│   ├── .env
│   ├── alembic.ini
│   ├── docker-compose.yml        # Local MinIO for STORAGE_BACKEND=s3
│   └── requirements.txt          # (mirrors ../requirements.txt)
│
├── frontend/
│   ├── src/
│   │   ├── api/                  # Axios calls per resource (ticket, agent, interaction, email, auditLog)
│   │   ├── components/
│   │   │   ├── common/            # Button, Card, Badge, Modal, FormField, Skeleton, ToastViewport...
│   │   │   ├── layout/            # Sidebar, Topbar, AppLayout
│   │   │   ├── inbox/             # AgentInbox, EmailDetails, InboxActionsPanel
│   │   │   └── ticket/            # TicketHeader, TicketTimeline, TicketComposer, TicketDetails, TicketActions, TicketAuditLog
│   │   ├── context/               # WorkflowContext, ToastContext, ThemeContext (light/dark)
│   │   ├── hooks/                 # useApiAction, useDebouncedValue
│   │   ├── lib/                   # format, ticketTone, interactionMeta, auditLogMeta, agents
│   │   ├── pages/                 # Dashboard, CreateMailPage, InboxPage, InteractionsPage, TicketsListPage, TicketDetailPage, AuditLogPage
│   │   └── types/                 # Shared TypeScript types mirroring backend schemas
│   ├── index.html
│   ├── package.json
│   ├── tailwind.config.js
│   └── vite.config.ts
│
└── requirements.txt
```

---

# Technologies Used

**Backend**
- Python 3.12+
- FastAPI
- SQLAlchemy 2.0 (async)
- Alembic
- PostgreSQL (Neon)
- Pydantic v2

**Frontend**
- React 18 + TypeScript
- Vite
- Tailwind CSS (CSS-variable-driven light/dark theme)
- React Router v6
- Axios
- lucide-react (icons)

**Storage**
- Supabase Storage (default), or any S3-compatible bucket (MinIO locally,
  Cloudflare R2 / AWS S3 in production)

---

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

---

# Local Object Storage (optional)

To test attachments without a Supabase project, run a local S3-compatible
bucket via MinIO:

```bash
cd backend
docker compose up -d
```

This starts MinIO on `http://localhost:9000` (console on `:9001`, login
`minioadmin` / `minioadmin`) and creates the `communication-attachments`
bucket automatically. Then set in `backend/.env`:

```env
STORAGE_BACKEND=s3
STORAGE_ENDPOINT_URL=http://localhost:9000
STORAGE_ACCESS_KEY=minioadmin
STORAGE_SECRET_KEY=minioadmin
```

---

# Database

This service uses a shared PostgreSQL database.

Ticket Management owns the following tables:

- tickets
- interactions
- attachments

User-related tables (users, roles) are managed by the RBAC service through
shared models, and are read (not written) by this service — e.g. to resolve
`client_id` / `agent_id` to display names, and to validate that an agent
name/id belongs to an active Staff user.

---

# Migrations

Initial migration is created manually.

Future schema changes should use:

```bash
alembic revision --autogenerate -m "migration_message"
alembic upgrade head
```

---

# Shared Models

This project imports shared models from the `shared_models` package.

Shared models include:

- User
- Role
- Base
- TimestampMixin

These models are maintained by the RBAC team.

---

# API Reference

All routes are mounted with no `/api` prefix (see `app/main.py`).

## Emails

| Method | Path | Description |
|---|---|---|
| POST | `/emails/incoming` | Simulates a client email arriving; routes it to an agent's inbox (least-loaded active Staff member). |

## Agents

| Method | Path | Description |
|---|---|---|
| GET | `/agents` | Lists every active Staff user (used to populate real agent pickers, e.g. Transfer Agent). |
| GET | `/agents/{agent_name}/inbox` | Lists pending (ticketless) emails routed to this agent. |
| GET | `/agents/{agent_name}/inbox/{interaction_id}` | Full detail of one pending inbox email. |

## Tickets

Every mutating route below accepts an `agent_name` query (or form, for the
multipart attachment upload) parameter — the "acting as" agent, used both
for access-control checks and to attribute the change on the audit trail
(see [Audit Trail & Actor Model](#audit-trail--actor-model)).

| Method | Path | Description |
|---|---|---|
| POST | `/tickets/from-interaction` | Creates a ticket from a pending inbox interaction. |
| POST | `/tickets/{ticket_id}/attach-interaction` | Attaches a pending interaction to an existing ticket. |
| GET | `/tickets` | Lists tickets, most recent first. Optional `agent_name` query param scopes results to that agent's assignments plus unassigned tickets. |
| GET | `/tickets/{ticket_id}` | Ticket detail. Optional `agent_name` — returns `403` if the ticket is assigned to someone else. |
| GET | `/tickets/{ticket_id}/interactions` | Ticket timeline. Optional `agent_name` — same `403` rule as above, so a ticket's interactions can't be viewed by bypassing the ticket-level check. |
| GET | `/tickets/{ticket_id}/audit-logs` | Full immutable audit trail for the ticket, newest first. Same `agent_name` visibility rule as the timeline. |
| POST | `/tickets/{ticket_id}/notes` | Adds an internal note (recorded as an interaction). |
| POST | `/tickets/{ticket_id}/reply` | Sends a reply to the client (recorded as an OUTBOUND interaction). |
| POST | `/tickets/{ticket_id}/status` | Changes ticket status; recorded on the timeline. |
| POST | `/tickets/{ticket_id}/priority` | Changes ticket priority; recorded on the timeline. |
| POST | `/tickets/{ticket_id}/attachments` | Uploads one or more files to the ticket; recorded on the timeline. |
| POST | `/tickets/{ticket_id}/interactions/{interaction_id}/hide` | Soft-deletes ("hides") one interaction on this ticket. Never physically deletes the row. |
| POST | `/tickets/{ticket_id}/transfer` | Transfers full ownership to another active Staff member. The previous agent immediately loses access; the change is recorded as an `AGENT_TRANSFER` interaction. |
| PATCH | `/tickets/{ticket_id}` | Direct field update (title, ticket_type, custom_fields, closed_at). Prefer the dedicated `/status`, `/priority`, `/transfer` routes so the change lands on the timeline too. |

## Interactions

| Method | Path | Description |
|---|---|---|
| POST | `/interactions/{interaction_id}/hide` | Ticket-agnostic soft-delete — also works for pending (pre-ticket) inbox emails, which `POST /tickets/{id}/interactions/{id}/hide` can't reach. |

## Attachments

| Method | Path | Description |
|---|---|---|
| GET | `/attachments/{attachment_id}` | File metadata (filename, size, mime type, signed URLs). |
| GET | `/attachments/{attachment_id}/download` | 307-redirects to a short-lived signed download URL. |
| DELETE | `/attachments/{attachment_id}` | Deletes the file from storage and its metadata row. |

---

# Access Control Model

There is no JWT/session auth layer yet — the frontend passes an explicit
`agent_name` ("acting as") value on every ticket/interaction read, mirroring
the existing `agent_name` path param already used by the inbox routes. The
rule, enforced in `app/services/access_control.py` and shared by both
`TicketService` and `InteractionService`:

- A ticket assigned to an agent is visible **only** to that agent.
- An unassigned ticket remains visible to everyone (so nothing is
  permanently orphaned).
- Interactions inherit their parent ticket's visibility — you cannot read
  a ticket's timeline directly if you couldn't read the ticket itself.
- Transferring a ticket moves `agent_id` outright; the previous agent has
  no residual access from that moment on.

---

# Audit Trail & Actor Model

Every meaningful change is written to an immutable, append-only
`ticket_audit_logs` table (`app/models/audit_log.py`) — separate from the
`interactions` timeline agents read day to day. Audit rows are never
updated or deleted.

Each row stores the actor **at write time**, not resolved via a join at
read time, so the trail keeps saying who did something even if that
person's name changes later:

| Column | Meaning |
|---|---|
| `actor_id` | The real `users.user_id`, if the actor is a known agent or client. `NULL` for system events. |
| `actor_name` | Display name captured at write time. |
| `actor_role` | `AGENT`, `CLIENT`, or `SYSTEM`. |
| `event_type`, `entity_type`, `entity_id` | What happened, and to which row. |
| `old_values` / `new_values` | Before/after snapshot (JSONB). |

Resolution rules (`AuditLogService.resolve_agent_actor`):

- **Agent actions** (reply, note, status/priority change, transfer,
  attachment upload, direct ticket update) — the `agent_name` passed on the
  request is looked up against the real `users` table; if it resolves to an
  active Staff member, that user is the actor (`AGENT`).
- **Client actions** (an inbound email) — the sending client is the actor
  (`CLIENT`).
- **System** — only when no agent could be resolved (e.g. no `agent_name`
  given), covering genuinely automatic actions like auto-assignment.

The frontend's Ticket Detail page ("Audit Trail" panel) and the global
**Audit Log** page both render `actor_name` + `actor_role` directly — there
is no hardcoded "System" fallback.

---

# Theme (Light / Dark)

The frontend ships a light and dark theme, toggled from the top bar and
persisted to `localStorage`. Colors are defined once as CSS variables
(`src/index.css`) and consumed through Tailwind's `darkMode: "class"` config
(`tailwind.config.js`) — every existing `bg-slate-*` / `text-slate-*` /
`border-slate-*` usage is theme-aware with no per-component changes. An
inline script in `index.html` applies the saved theme before React mounts,
so there's no flash of the wrong theme on load.

---

# Phase 1 Features

- Ticket creation from inbound (dummy) email
- Attach an inbound email to an existing ticket
- Ticket assignment via least-loaded active Staff routing
- **Agent-to-agent ticket transfer** with full ownership handoff and an
  auditable `AGENT_TRANSFER` interaction
- **Ticket & interaction visibility scoped to the assigned agent**
  (unassigned tickets stay visible to all)
- Ticket interactions: replies, internal notes, status/priority changes,
  attachments
- **Soft delete ("hide") of interactions**, including pending pre-ticket
  emails, without destroying the audit trail
- Client-name / agent-name enrichment on tickets (no more raw UUIDs in
  the UI) and client-name search on both the Tickets and Interactions pages
- Shared RBAC integration (real Staff/Viewer users, no dummy data)
- PostgreSQL database integration
- Alembic migrations
- A full "Agent Workspace" frontend: Dashboard (KPIs incl. Critical
  Tickets and a derived SLA-risk indicator), Create Dummy Mail, Inbox
  (3-column triage view), Interactions (activity explorer with per-ticket
  filtering), Tickets (sortable/filterable table), and a two-column Ticket
  Detail workspace (timeline, composer, properties/actions)
- Enterprise-grade UI polish: consistent design system (spacing, typography,
  color, shadows), skeleton loading states, empty states, responsive layout
  down to mobile (collapsible sidebar drawer), and accessibility basics
  (keyboard-navigable tables/lists, focus states, aria-labels)

---

# Phase 2 Features

- **File attachments** on tickets and inbound emails, backed by Supabase
  Storage or any S3-compatible bucket, with signed download/preview URLs
- **Immutable audit trail** (`ticket_audit_logs`) with real actor
  attribution — see [Audit Trail & Actor Model](#audit-trail--actor-model)
  — surfaced both per-ticket (Audit Trail panel) and globally (Audit Log
  page, with filters, pagination, and auto-refresh)
- **Light / dark theme**, persisted and flash-free — see
  [Theme](#theme-light--dark)
- Ticket Detail layout: timeline on the left, ticket properties + actions +
  audit trail sticky on the right so it stays visible while a long timeline
  scrolls; stacks vertically on mobile
- Performance: debounced search inputs, client-side pagination on the
  Tickets/Interactions/Audit Log pages, and a stale-response guard on every
  API call so switching the acting agent mid-request can no longer show a
  stale or mismatched result

---

# Team Architecture

```
                Shared PostgreSQL (Neon)

               ┌─────────────────────┐
               │     RBAC Service    │
               │---------------------│
               │ Users               │
               │ Roles               │
               │ Permissions         │
               └──────────┬──────────┘
                          │
                Shared Models Package
                          │
               ┌──────────┴──────────┐
               │ Ticket Management   │
               │---------------------│
               │ Tickets             │
               │ Interactions        │
               │ Attachments         │
               │---------------------│
               │ Agent Workspace UI  │
               └─────────────────────┘
```

---

# Author

Ticket Management Team
