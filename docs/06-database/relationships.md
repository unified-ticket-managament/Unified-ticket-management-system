# Relationships

## Cross-Alembic-chain foreign keys (RBAC ← Ticketing)

Every one of these is a real, enforced FK from a ticketing table into an RBAC-owned table:

| Ticketing table | Column | → RBAC table |
|---|---|---|
| `tickets` | `client_id` (legacy) | `users.user_id` |
| `tickets` | `agent_id`, `assigned_by`, `created_by`, `closed_by` | `users.user_id` |
| `clients` | `account_manager_id` | `users.user_id` |
| `interactions` | `performed_by`, `claimed_by` | `users.user_id` |
| `mail_folders` | `created_by` | `users.user_id` |
| `rules` | `created_by` | `users.user_id` |
| `ticket_escalations` | `triggered_by_user_id`, `acknowledged_by` | `users.user_id` |
| `message_read_receipts` | `user_id` | `users.user_id` |
| `ticket_audit_logs` | `actor_id` | `users.user_id` |

## Deliberately absent cross-chain foreign keys (RBAC → Ticketing)

| RBAC table | Column | Would-be target | Why no FK |
|---|---|---|---|
| `user_permission_overrides` | `scope_ticket_id` | `tickets.ticket_id` | Avoids coupling migration ordering between chains; validated in application code (`PermissionRequestService.create_request` looks the ticket up via `app.ticketing`'s own `TicketRepository` directly, since both are one process) |
| `permission_requests` | `scope_ticket_id` | `tickets.ticket_id` | Same reasoning |

## Self-referencing relationships

| Table | Column(s) | Meaning |
|---|---|---|
| `users` | `manager_id`, `teamlead_id`, `reporting_manager_id` | Three independent hierarchy concepts — see [04-functional-modules/organization-structure.md](../04-functional-modules/organization-structure.md) |
| `interactions` | `parent_interaction_id` | Always resolves to the thread root, never an intermediate reply |
| `ticket_relations` | `ticket_id`, `related_ticket_id` (composite PK, both FK→`tickets`) | Symmetric — a link is stored as two mirrored rows |

## One-to-one relationships (enforced by UNIQUE, not just convention)

| Table | Unique column | Meaning |
|---|---|---|
| `resolution_slas` | `ticket_id` | Exactly one Resolution clock per ticket |
| `first_response_slas` | `interaction_id` | Exactly one First Response clock per thread root |

## Many-to-many relationships

| Join table | Between | Notes |
|---|---|---|
| `user_categories` | `users` ↔ `categories` | The newer, multi-category membership model; `users.category_id` (a scalar FK) is the older, legacy single-category column that still exists alongside it |
| `role_permissions` | `roles` ↔ `permissions` | Composite PK, no surrogate key |

## Polymorphic references (no FK, by necessity)

| Table | Column | Points at (by convention, not FK) |
|---|---|---|
| `sla_breach_notifications` | `clock_id` | Either `first_response_slas.first_response_sla_id` or `resolution_slas.resolution_sla_id`, distinguished by the sibling `clock_type` column |
| `ticket_audit_logs` | `entity_id` | Whatever `entity_type` says (TICKET/INTERACTION/ATTACHMENT/CLIENT/USER) |
| `notifications` | `related_entity_id` | Whatever `related_entity_type` says (free-form string, not enum-constrained) |
