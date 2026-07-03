# Ticket Management System - Progress
### PHASE 1 - DAY1 
## Project Overview

This project is a **Ticket Management Microservice** that is being developed independently from the RBAC service.

Both services use:

* Shared PostgreSQL database (Neon)
* Shared SQLAlchemy models (`shared_models`)
* Independent repositories
* Independent Alembic migration histories

---

# Tech Stack

## Backend

* Python 3.14
* FastAPI
* SQLAlchemy 2.0
* Alembic
* Pydantic
* Uvicorn

## Database

* PostgreSQL (Neon)

## ORM

* SQLAlchemy ORM

## Migrations

* Alembic

## Shared Package

shared_models

Contains:

* Base
* User
* Role
* TimestampMixin

---

# Repository Architecture

```
shared-models/
│
├── database/
│   └── base.py
│
├── mixins/
│   └── timestamp_mixin.py
│
└── models/
    ├── user.py
    └── role.py
```

```
ticket-management/
│
├── backend/
│   │
│   ├── alembic/
│   │
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── database/
│   │   ├── models/
│   │   ├── repositories/
│   │   ├── schemas/
│   │   ├── services/
│   │   └── main.py
│   │
│   ├── requirements.txt
│   ├── alembic.ini
│   └── .env
│
└── frontend/
```

---

# Shared Database Architecture

```
Neon PostgreSQL
│
├── RBAC Service
│   ├── users
│   ├── roles
│   ├── permissions
│   ├── role_permissions
│   ├── audit_logs
│   └── alembic_version
│
└── Ticket Management
    ├── tickets
    ├── interactions
    ├── attachments
    └── ticket_alembic_version
```

---

# Completed

## Shared Models

Completed

* Shared repository created
* Base implemented
* TimestampMixin implemented
* User model implemented
* Role model implemented
* Local package installation working

---

## Ticket Models

Completed

### Ticket

Implemented

* UUID Primary Key
* Client User FK
* Assigned User FK
* Status Enum
* Priority Enum
* Relationships

---

### Interaction

Implemented

* UUID PK
* Ticket FK
* JSONB Content
* Type Enum
* Direction Enum

---

### Attachment

Implemented

* UUID PK
* Interaction FK
* File Metadata

---

## Database

Completed

* Connected to Neon
* Async connection working
* Shared database confirmed

---

## Alembic

Completed

* Alembic configured
* Separate version table

```
ticket_alembic_version
```

RBAC continues using

```
alembic_version
```

---

## Shared Models Integration

Completed

Ticket Management imports

```
User
Role
Base
TimestampMixin
```

from

```
shared_models
```

---

# Current Progress

## Manual Initial Migration

Status:

In Progress

Reason:

The initial migration is intentionally manual.

It creates ONLY

* tickets
* interactions
* attachments

without touching RBAC tables.

---

## SQL Verification

Completed

Verified SQL contains

```
CREATE TABLE tickets
CREATE TABLE interactions
CREATE TABLE attachments
```

Verified SQL does NOT contain

```
CREATE TABLE users
CREATE TABLE roles
CREATE TABLE permissions
CREATE TABLE audit_logs
```

---

# Not Started

Repository Layer

* Ticket Repository
* Interaction Repository
* Attachment Repository

---

Service Layer

* Ticket Service
* Interaction Service
* Attachment Service

---

Schemas

* Ticket Schemas
* Interaction Schemas
* Attachment Schemas

---

API Layer

CRUD APIs

* Create Ticket
* Get Ticket
* Update Ticket
* Delete Ticket

Interactions

Attachments

---

Authentication Integration

RBAC integration

JWT validation

Permission validation

---

Business Logic

Ticket assignment

Ticket workflow

Status transitions

Validation

---

Testing

Unit Tests

Integration Tests

API Tests

---

Documentation

Swagger improvements

Architecture diagrams

Deployment guide

---

# Key Architectural Decisions

## 1

Shared Models Repository

Decision:

Use one shared package containing

* Base
* User
* Role
* TimestampMixin

Reason:

Avoid duplicate SQLAlchemy models across repositories.

---

## 2

Shared Database

Decision:

Both services use the same Neon PostgreSQL database.

Reason:

Single source of truth.

---

## 3

Separate Alembic Version Tables

RBAC

```
alembic_version
```

Ticket

```
ticket_alembic_version
```

Reason:

Independent migration histories.

---

## 4

Table Ownership

RBAC owns

* users
* roles
* permissions
* role_permissions
* audit_logs

Ticket owns

* tickets
* interactions
* attachments

Reason:

Clear ownership between teams.

---

## 5

First Migration

Decision

Manual

Reason

Avoid Alembic attempting to recreate RBAC tables because both services share Base.metadata.

---

## 6

Future Migrations

Decision

Use

```
alembic revision --autogenerate
```

after the initial manual migration.

Reason

Normal development workflow.

---

## 7

Client & Staff

Decision

Use

```
users.id
```

instead of

```
clients
staff
managers
```

Reason

RBAC stores all user types inside one users table.

Role determines whether the user is

* Client
* Staff
* Manager
* Admin
* Team Lead

---

# Known Issues

## Issue 1

Alembic autogenerate sees shared models.

Reason

Shared Base.metadata contains

* users
* roles
* tickets
* interactions
* attachments

Current solution

Initial migration is manual.

---

## Issue 2

Enum duplication

Resolved

Migration updated to avoid duplicate PostgreSQL enum creation.

---

## Issue 3

Initial migration

Still pending execution.

Need to

```
alembic upgrade head
```

after final migration verification.

---

# Next Immediate Tasks

1.

Complete

```
alembic upgrade head
```

2.

Verify in Neon

```
tickets
interactions
attachments
```

exist.

3.

Verify

```
ticket_alembic_version
```

contains the latest revision.

4.

Begin Repository Layer.

5.

Implement Service Layer.

6.

Implement CRUD APIs.

---

# Long-Term Roadmap

Phase 1

* Database
* Models
* Repositories
* Services
* CRUD APIs

Phase 2

* Assignment Engine
* Status Workflow
* Email Integration
* Notifications

Phase 3

* SLA
* Dashboard
* Analytics
* Escalations
* Reporting

---

# Notes for Future Chat

Important decisions that should NOT be changed:

* Keep Shared Models architecture.
* Keep shared Base.
* Keep shared User and Role.
* Keep shared Neon database.
* Keep separate Alembic version tables.
* RBAC owns RBAC tables.
* Ticket service owns Ticket tables.
* Initial migration is manual.
* Future migrations use Alembic autogenerate.
* One users table represents Client, Staff, Manager, Admin, and Team Lead through role_id.
* Ticket references users.id for both client and assigned staff.
* Phase 1 supports one assigned staff per ticket.
* Multiple staff assignment will be implemented in a future phase using a separate assignment table.
