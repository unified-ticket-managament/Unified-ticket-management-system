# Audit Workflow

## 1. Purpose
Maintain a permanent, tamper-resistant record of significant actions — across **two genuinely separate systems** that happen to share the phrase "audit log."

## 2. Trigger
Any write to `audit_logs` (RBAC domain) or `ticket_audit_logs` (Ticketing domain), each triggered inline by the service performing the mutating action.

## 3. Actors
The system (writes the record); any user (whose action is being recorded); `ActorRole.SYSTEM` for automated changes (e.g. the CRITICAL priority bump).

## 4. Preconditions
None — audit writes happen as a side effect of the triggering action, in the same transaction.

## 5. High-Level Flow
Mutating action → service performs the write → service also writes the corresponding audit row → both commit together (or both roll back together).

## 6. Detailed Workflow

**RBAC-native `audit_logs`** (`app.rbac`): historically written only by the permission-override grant/revoke flow and the permission-request lifecycle. Substantially widened since: `AuthService` (`auth.login`/`auth.login_failed`/`auth.logout`/`auth.change_password`), `UserService` (`user.create`/`.update`/`.delete`/`.activate`/`.deactivate`/`.role_changed`), `RoleService` (`role.create`/`.update`/`.delete`), `RolePermissionService` (`role.permissions_added`/`.permissions_removed` — a diff of only what changed, never a blanket re-log).

**Ticketing-domain `ticket_audit_logs`** (`app.ticketing`, model literally named `AuditLog` but a distinct table from the RBAC one): a much larger, ticket-scoped event catalog (`AuditEventType`, ~30 values) covering ticket creation/status/priority/category changes, assignment/transfer, SLA pause/resume, escalation creation/acknowledgment/advancement/closure, notes, replies, and more.

## 7. Business Rules
- **These are two separate tables/systems and must never be conflated.** `audit_logs` (RBAC) records identity/access-management actions; `ticket_audit_logs` (Ticketing) records everything that happens to a specific ticket. A ticket ID has no meaning in the RBAC table; a user-management action has no row in the ticketing table.
- **Deliberately NOT logged, checked and ruled out as out of scope, not overlooked**: attachment download/delete and mail draft save/delete (would need new `AuditEventType` values — a Postgres-enum-widening migration); Reports/Settings have no backend endpoint to hook into; Ticket Resolved/Closed/Reopened are already fully covered by the existing `STATUS_CHANGED`-family events, so no separate events were added for them.
- Every permission-override/permission-request action logs a `previous_status`/`new_status` pair explicitly, not just an ad-hoc field subset.

## 8. Decision Points
- Which domain does the action belong to? → determines which of the two tables receives the row.
- Is this a diff-worthy update (role permissions, user profile fields)? → log only what changed, never the full new state redundantly.

## 9. Database Changes
`audit_logs` (RBAC) or `ticket_audit_logs` (Ticketing) — append-only, never updated or deleted by normal application flow (a Super-Admin-gated manual delete endpoint exists on the RBAC side, `DELETE /api/v1/audit-logs/{id}`, but is not part of ordinary workflow).

## 10. APIs Involved
`GET /api/v1/audit-logs` (RBAC, `audit:view`-gated — see §16 for why "Super-Admin" is no longer the accurate description), `GET /api/v1/audit-logs/export` (RBAC, requires both `audit:view` and `audit:export`), `GET /tickets/{id}/audit-logs` and `GET /tickets/audit-logs` (ticketing — scoped-by-default with an opt-in global mode gated by `ticket:view_global_audit_log`, independent of `audit:view`).

## 11. Services / Components Involved
`AuditLogService` (both domains have their own, same name, different table), `AuditLogRepository` (both domains).

## 12. External Integrations
N/A.

## 13. Notifications
Audit writes themselves don't notify — they're a passive record of an action whose *other* side effects (assignment, SLA breach, etc.) do the notifying.

## 14. Audit Events
See §6 above for the two catalogs.

## 15. Failure Scenarios
A Postgres-native enum missing a value the application code expects to write (or read) raises a `LookupError`/`InvalidTextRepresentationError` — this has caused real, confusing "looks like CORS" 500s (see [14-troubleshooting](../../14-troubleshooting/README.md)) more than once in this codebase's history.

## 16. Edge Cases
- The Ticket Audit Log page was deliberately reworked into a **scoped-by-default** view (no permission required, role-accurate slice — Staff narrowed to just their own assigned tickets) plus an **opt-in global mode** gated by `ticket:view_global_audit_log` — requiring the permission for the whole page would have turned an Override-only grant into "blocks the page outright" for most roles.
- **`GET /api/v1/audit-logs`'s list/get/user/export routes are now gated by the real `audit:view`/`audit:export` permissions**, not a hardcoded `role.name == "Super Admin"` check — that hardcoded check previously 403'd a Site Lead who holds `audit:view` by default but isn't literally named "Super Admin," a real functional gap since fixed. The manual `POST /audit-logs` create route (an administrative escape hatch with no legitimate caller, not the system's real audit-writing path) still uses the hardcoded check, by deliberate design, and `DELETE /audit-logs/{id}` was removed outright (audit rows are append-only; a repo-wide search found zero legitimate callers).
- **The Ticket Audit Log page and the Centralized (RBAC) Audit Log page now render every individual event through the same shared frontend component** (`AuditEventRow`/`AuditEventList`/`AuditEventDetailsDrawer`, fed by two adapters in `normalizeAuditEvent.ts` that each build a common `UnifiedAuditEvent` shape from their own domain's API response) — a single event never looks different depending on which of the two domains produced it, even though the underlying tables and permissions stay fully separate. See `docs/04-functional-modules/audit-management.md`'s "Unified audit-event presentation" section.
- **A `ticket_audit_logs` row with no `ticket_id`** (e.g. `CLIENT_CREATED`, `DISTRIBUTION_LIST_CREATED`/`_UPDATED`/`_MEMBER_ADDED`/`_MEMBER_REMOVED`/`_DEACTIVATED`/`_DELETED`) **is written but not retrievable through any current Audit Log view** — every read path (`list_visible_page`, `list_by_ticket`, `list_by_ticket_ids`) either requires `ticket_id IS NOT NULL` or inner-joins to `tickets`. This is a known, currently-unresolved gap — see `docs/AUDIT_LOG_BACKLOG.md` (BL-001).
- Two Alembic migrations in *different* chains once shared the identical revision id (`b3d5f7a9c1e2`) — harmless (each chain uses its own `version_table`) but worth knowing before assuming revision ids are unique repo-wide.

## 17. Postconditions
A permanent, queryable record exists for the action, attributed to the correct actor (or `SYSTEM`), with enough `old_values`/`new_values` detail to reconstruct what changed.

## 18. Relevant Source Files
- `unified-backend/app/rbac/models/audit_log.py`, `app/rbac/services/audit_log_service.py`
- `unified-backend/app/ticketing/models/audit_log.py`, `app/ticketing/services/audit_log_service.py`
- `unified-backend/app/ticketing/enums/audit_enums.py`

## 19. Example Scenario
A Site Lead changes a Team Lead's category. `UserService.update_user` writes a `user.update` row (diffing just `category_id`) to RBAC's `audit_logs`, and bumps the affected user's `permission_version`. Separately, if that Team Lead is later reassigned a ticket in their new category, that action writes an entirely unrelated `ASSIGNED` row to `ticket_audit_logs` — two systems, two rows, one real action chain a developer might need to trace across both.
