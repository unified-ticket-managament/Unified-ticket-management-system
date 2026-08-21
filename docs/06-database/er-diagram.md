# Entity Relationship Diagram

## Core RBAC entities

```mermaid
erDiagram
    ROLES ||--o{ USERS : "has many"
    USERS ||--o{ USERS : "manager_id / teamlead_id / reporting_manager_id (self-FK)"
    CATEGORIES ||--o{ USERS : "category_id (legacy single)"
    CATEGORIES }o--o{ USERS : "user_categories (M2M)"
    ROLES ||--o{ ROLE_PERMISSIONS : ""
    PERMISSIONS ||--o{ ROLE_PERMISSIONS : ""
    USERS ||--o{ USER_PERMISSION_OVERRIDES : "grants"
    PERMISSIONS ||--o{ USER_PERMISSION_OVERRIDES : ""
    USERS ||--o{ PERMISSION_REQUESTS : "requests"
    USERS ||--o{ REPORTING_MANAGER_TEAMS : "account_manager_id"
    CATEGORIES ||--o{ REPORTING_MANAGER_TEAMS : ""
    USERS ||--o{ AUDIT_LOGS : "actor"
```

## Core ticketing entities

```mermaid
erDiagram
    CLIENTS ||--o{ TICKETS : "client_company_id"
    CLIENTS ||--o{ CLIENT_CONTACTS : ""
    CLIENTS ||--o{ CLIENT_ASSIGNMENTS : ""
    USERS ||--o{ CLIENTS : "account_manager_id"
    TICKETS ||--o{ INTERACTIONS : "ticket_id (nullable pre-ticket)"
    INTERACTIONS ||--o{ INTERACTIONS : "parent_interaction_id (thread root)"
    INTERACTIONS ||--o{ ATTACHMENTS : ""
    USERS ||--o{ TICKETS : "agent_id"
    TICKETS ||--o{ TICKET_RELATIONS : "symmetric self-M2M"
    TICKETS ||--o| RESOLUTION_SLAS : "1:1"
    RESOLUTION_SLAS ||--o{ RESOLUTION_SLA_PAUSE_INTERVALS : ""
    INTERACTIONS ||--o| FIRST_RESPONSE_SLAS : "1:1 (thread root)"
    TICKETS ||--o{ TICKET_ESCALATIONS : ""
    TICKET_ESCALATIONS ||--o| ESCALATION_HANDLING_SLAS : "1:1 while active"
    TICKETS ||--o{ TICKET_AUDIT_LOGS : ""
    SLA_POLICIES ||--o{ RESOLUTION_SLAS : "priority tier"
    SLA_POLICIES ||--o{ FIRST_RESPONSE_SLAS : "priority tier"
```

## Notifications

```mermaid
erDiagram
    USERS ||--o{ NOTIFICATIONS : "recipient"
```

Notes:
- `resolution_slas` and `first_response_slas` are **not** the same clock — see [03-business-workflows/sla](../03-business-workflows/sla/) for why they're modeled as two independent 1:1 relationships (one to `Ticket`, one to the thread-root `Interaction`).
- `Ticket.client_id` (legacy, FK→`users`) and `Ticket.client_company_id` (current, FK→`clients`) coexist — the legacy column reflects an earlier model where a "client" was a `users` row directly; verify which is authoritative before writing new code against either (see [16-known-limitations](../16-known-limitations/README.md) if this hasn't been fully reconciled).
- `ticket_relations` is a **symmetric** self-referencing M2M — a link between ticket A and B is stored as two mirrored rows, not one directional row.
