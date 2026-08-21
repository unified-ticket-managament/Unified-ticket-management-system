# Database Overview

## One physical database, two migration histories

UTMS uses **one** PostgreSQL database (hosted on Neon), but the schema is managed by **two independent Alembic chains**:

| Chain | Config | Owns |
|---|---|---|
| `alembic_rbac` | `unified-backend/alembic_rbac/alembic.ini` | `users`, `roles`, `categories`, `user_categories`, `permissions`, `role_permissions`, `audit_logs`, `user_permission_overrides`, `permission_requests`, `reporting_manager_teams` |
| `alembic_ticketing` | `unified-backend/alembic_ticketing/alembic.ini` | `clients`, `client_assignments`, `client_contacts`, `tickets`, `interactions`, `attachments`, `ticket_audit_logs`, `mail_folders`, `ticket_relations`, `sla_policies`, `first_response_slas`, `resolution_slas`, `resolution_sla_pause_intervals`, `sla_breach_notifications`, `message_read_receipts`, `ticket_escalations`, `escalation_handling_slas`, `rules`, `notifications` |

Each chain has its own `version_table` (ticketing's is `ticket_alembic_version`) so the two histories never collide — confirmed two migrations in different chains once shared an identical revision id (`b3d5f7a9c1e2`) with no ill effect, precisely because of this separation.

**Why two chains against one database?** The system began as two separate services with two separate databases-in-intent; the backend consolidation merged the *process*, not the schema management — each domain kept full control over its own migration history rather than being forced into one combined chain. See [15-architecture-decisions/ADR-001-database-architecture.md](../15-architecture-decisions/ADR-001-database-architecture.md).

## Cross-chain foreign keys — a deliberate, asymmetric rule

Nearly every ticketing table has a real FK into `users.user_id` (owned by `alembic_rbac`) — `tickets`, `interactions`, `clients`, `client_assignments`, `mail_folders`, `rules`, `ticket_escalations`, `message_read_receipts`, `ticket_audit_logs`, etc. This is safe because `users` is stable, foundational, cross-domain infrastructure.

The reverse never happens: `UserPermissionOverride.scope_ticket_id` and `PermissionRequest.scope_ticket_id` (both RBAC-owned) deliberately use a **plain, unconstrained UUID** with no FK into `tickets` (ticketing-owned) — validated in application code instead. This avoids entangling the two chains' migration ordering: a ticketing migration must never be required to run before an RBAC one just to satisfy a constraint.

## Shared models package

`User`, `Role`, `Category` live in `shared_models/shared_models/models/` — a separate, local-editable-installed Python package both `app.rbac` and `app.ticketing` import from directly. There is exactly one copy of these three model definitions; `app/rbac/models/{user,role,category}.py` are thin re-export shims, not independent copies.

## Migration current heads (as of this documentation pass)

- `alembic_rbac`: `f1a3c5e7b9d2_add_user_categories_table.py`
- `alembic_ticketing`: `b5d7f9a1c3e6_add_category_transferred_audit_event_type.py`

See [migrations.md](migrations.md) for the full chronological summary and notable migrations.

## Postgres-native enums vs. plain strings

A deliberate split exists between values encoded as real Postgres enum types (locked-down, requiring a migration to extend — `TicketStatus`, `TicketPriority`, `SLAClockStatus`, `EscalationLevel`, `EscalationStatus`, `AuditEventType`, `AuditEntityType`, `ActorRole`, `InteractionStatus`, `InteractionDirection`) and values kept as plain strings specifically because they're expected to change frequently without a schema migration (`RuleCategory`, `NotificationType`, `Interaction.interaction_type`, `PermissionRequest.status`, `SLABreachNotification.clock_type`/`.threshold`, `TicketEscalation.triggered_by`/`.closed_reason`, `Attachment.scan_status`, and — as of `alembic_rbac`'s `a4c6e8b0d2f5` migration, 2026-08-21 — `Category.category_name`). See [tables/](tables/) for exactly which column uses which.

**`Category.category_name` was converted from a native Postgres enum to a plain, unique, indexed `VARCHAR(150)`** (migration `a4c6e8b0d2f5_category_name_enum_to_varchar`, head of `alembic_rbac` as of this pass). The `category_name_enum` Postgres type was dropped, and the backing Python `CategoryName` enum (`shared_models.models.category`) was deleted outright — there is no fixed category list anymore. This lets a Super Admin/Account Manager create a new work-specialization category (e.g. "PatientOutreach") at runtime through the ordinary Category CRUD API, with no code change and no migration. Existing category values were preserved as-is by the cast. See [06-database/migrations.md](migrations.md) and [04-functional-modules/organization-structure.md](../04-functional-modules/organization-structure.md).
