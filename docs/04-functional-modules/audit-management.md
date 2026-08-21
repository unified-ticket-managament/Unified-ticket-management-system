# Audit Management Module

## Purpose
Maintain two separate, permanent records of significant actions — one for identity/access management, one for everything that happens to a ticket.

## Responsibilities
- RBAC-native audit logging (`audit_logs`) — auth events, user/role/permission mutations.
- Ticketing-domain audit logging (`ticket_audit_logs`) — the much larger ticket-lifecycle event catalog.
- Scoped-by-default vs. centralized viewing modes for the ticket audit trail.

## Main Components
- `app/rbac/services/audit_log_service.py`, `app/rbac/models/audit_log.py`, `app/rbac/api/v1/audit_logs.py`
- `app/ticketing/services/audit_log_service.py`, `app/ticketing/models/audit_log.py`, `app/ticketing/enums/audit_enums.py`

## Inputs
Every mutating action across both domains that has been wired to call the corresponding `AuditLogService`.

## Outputs
Queryable audit trails via `/api/v1/audit-logs` and `/tickets/audit-logs`.

## Business Rules
- Two systems, never conflated: RBAC's `audit_logs` vs. Ticketing's `ticket_audit_logs` (same class name, `AuditLog`, different tables, different domains).
- The Ticket Audit Log page is scoped-by-default (no permission required, role-accurate slice) with an opt-in centralized mode gated by `ticket:view_global_audit_log` — avoiding the trap of one permission requirement blocking the whole page for most roles.
- Several action types are deliberately not logged (attachment download/delete, mail draft save/delete, Reports/Settings actions) — checked and ruled out as out of scope, not overlooked.

## Dependencies
Every service that performs a loggable mutation.

## Database Entities
`audit_logs` (RBAC), `ticket_audit_logs` (Ticketing).

## APIs
[07-api/organization-audit.md](../07-api/organization-audit.md) (RBAC), [07-api/tickets.md](../07-api/tickets.md) (`/audit-logs` endpoints, Ticketing).

## Important Classes/Services
`AuditLogService` (one per domain).

## External Integrations
None.

## Known Limitations
- RBAC's own `/audit-logs` list/create/delete endpoints check a hardcoded role-name string ("Super Admin") rather than a permission — a future role rename would silently break these routes.
- Two Alembic migrations in different chains once shared an identical revision id — harmless given separate `version_table`s, but a real gotcha if scripting against revision ids directly.

## Related workflows
[03-business-workflows/audit/audit-workflow.md](../../03-business-workflows/audit/audit-workflow.md).
