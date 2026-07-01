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
│   │   ├── api/                 # API routes (email, agent, ticket, interaction)
│   │   ├── core/                # Configuration, logging, security
│   │   ├── database/            # Database connection / session
│   │   ├── enums/                # Ticket & interaction enums
│   │   ├── middleware/           # Logging & security headers
│   │   ├── models/               # SQLAlchemy models
│   │   ├── repositories/         # Database operations
│   │   ├── schemas/              # Pydantic schemas
│   │   ├── services/             # Business logic (incl. access_control.py)
│   │   └── main.py               # FastAPI entry point
│   │
│   ├── .env
│   ├── alembic.ini
│   └── requirements.txt          # (mirrors ../requirements.txt)
│
├── frontend/
│   ├── src/
│   │   ├── api/                  # Axios calls per resource (ticket, agent, interaction, email)
│   │   ├── components/
│   │   │   ├── common/            # Button, Card, Badge, Modal, FormField, Skeleton, ToastViewport...
│   │   │   ├── layout/            # Sidebar, Topbar, AppLayout
│   │   │   ├── inbox/             # AgentInbox, EmailDetails, InboxActionsPanel
│   │   │   └── ticket/            # TicketHeader, TicketActivityRail, TicketConversation, TicketDetails, TicketActions
│   │   ├── context/               # WorkflowContext (acting agent, active ticket/timeline), ToastContext
│   │   ├── hooks/                 # useApiAction
│   │   ├── lib/                   # format, ticketTone, interactionMeta, agents
│   │   ├── pages/                 # Dashboard, CreateMailPage, InboxPage, InteractionsPage, TicketsListPage, TicketDetailPage
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
- Tailwind CSS
- React Router v6
- Axios
- lucide-react (icons)

---

# Clone Repository

```bash
git clone <repository-url>
```

Example

```bash
git clone https://github.com/supriyakanumarla/Phase-1.git
```

Move into the project

```bash
cd ticket-management
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
```

## Run Database Migrations

```bash
cd backend
alembic upgrade head
```

## Run the Backend

```bash
uvicorn app.main:app --reload
```

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
VITE_API_BASE_URL=http://localhost:8000
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

| Method | Path | Description |
|---|---|---|
| POST | `/tickets/from-interaction` | Creates a ticket from a pending inbox interaction. |
| POST | `/tickets/{ticket_id}/attach-interaction` | Attaches a pending interaction to an existing ticket. |
| GET | `/tickets` | Lists tickets, most recent first. Optional `agent_name` query param scopes results to that agent's assignments plus unassigned tickets. |
| GET | `/tickets/{ticket_id}` | Ticket detail. Optional `agent_name` — returns `403` if the ticket is assigned to someone else. |
| GET | `/tickets/{ticket_id}/interactions` | Ticket timeline. Optional `agent_name` — same `403` rule as above, so a ticket's interactions can't be viewed by bypassing the ticket-level check. |
| POST | `/tickets/{ticket_id}/notes` | Adds an internal note (recorded as an interaction). |
| POST | `/tickets/{ticket_id}/reply` | Sends a reply to the client (recorded as an OUTBOUND interaction). |
| POST | `/tickets/{ticket_id}/status` | Changes ticket status; recorded on the timeline. |
| POST | `/tickets/{ticket_id}/priority` | Changes ticket priority; recorded on the timeline. |
| POST | `/tickets/{ticket_id}/attachments` | Uploads a file to the ticket; recorded on the timeline. |
| POST | `/tickets/{ticket_id}/interactions/{interaction_id}/hide` | Soft-deletes ("hides") one interaction on this ticket. Never physically deletes the row. |
| POST | `/tickets/{ticket_id}/transfer` | Transfers full ownership to another active Staff member. The previous agent immediately loses access; the change is recorded as an `AGENT_TRANSFER` interaction. |
| PATCH | `/tickets/{ticket_id}` | Direct field update (title, ticket_type, custom_fields, closed_at). Prefer the dedicated `/status`, `/priority`, `/transfer` routes so the change lands on the timeline too. |

## Interactions

| Method | Path | Description |
|---|---|---|
| POST | `/interactions/{interaction_id}/hide` | Ticket-agnostic soft-delete — also works for pending (pre-ticket) inbox emails, which `POST /tickets/{id}/interactions/{id}/hide` can't reach. |

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
  filtering), Tickets (sortable/filterable table), and a 3-column Ticket
  Detail workspace (timeline, conversation, properties/actions)
- Enterprise-grade UI polish: consistent design system (spacing, typography,
  color, shadows), skeleton loading states, empty states, responsive layout
  down to mobile (collapsible sidebar drawer), and accessibility basics
  (keyboard-navigable tables/lists, focus states, aria-labels)

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
