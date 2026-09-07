# Auditability

## Two independent audit systems

See [04-functional-modules/audit-management.md](../04-functional-modules/audit-management.md) and [03-business-workflows/audit/audit-workflow.md](../03-business-workflows/audit/audit-workflow.md) for the full detail. Summary for a security review:

| System | Table | Covers |
|---|---|---|
| RBAC-native | `audit_logs` | Login/logout/password-change, user/role/permission mutations, permission override/request lifecycle |
| Ticketing-domain | `ticket_audit_logs` | ~30 event types across the entire ticket/SLA/escalation lifecycle |

## What IS provably recorded

- Every login attempt (success and failure, with a distinguishing reason).
- Every user/role/permission mutation performed through the RBAC domain's now-audited routes.
- Every permission-override grant/revoke and permission-request lifecycle transition, including `previous_status`/`new_status`.
- Every ticket status/priority/category change, assignment/transfer, SLA pause/resume, and escalation lifecycle event.
- The CRITICAL-priority auto-bump, correctly attributed to `ActorRole.SYSTEM` rather than a human actor.

## What is NOT recorded (deliberately, per root `CLAUDE.md`'s own explicit scope note)

- Attachment download. (Attachment **delete** is now recorded — `ATTACHMENT_DELETED` — corrected from an earlier version of this note.)
- Mail draft save/delete.
- Any Reports or Settings page action (no backend endpoint exists to hook an audit call into).
- Read access to a ticket, email body, or attachment (only mutations are audited — viewing is not).

## Known inconsistencies affecting auditability guarantees

- **Corrected (was previously stale here): only RBAC's `POST /audit-logs` (manual create) still authorizes via a hardcoded role-name string.** `list`/`get`/`export` are now gated by the real `audit:view`/`audit:export` permissions, and `DELETE /audit-logs/{id}` was retired outright (no longer exists — audit rows are append-only by design). Create's hardcoded check is deliberate (it's an admin escape hatch with zero legitimate callers, not the real audit-writing path), not an oversight — see `docs/07-api/organization-audit.md`.
- **A `ticket_audit_logs` row with no `ticket_id` is written but not retrievable through any current Audit Log view** (e.g. `CLIENT_CREATED`, every `DISTRIBUTION_LIST_*` event) — every read path requires `ticket_id IS NOT NULL` or inner-joins to `tickets`. A compliance reviewer should not assume these event types are queryable just because they exist in the enum and are written to the table. See `docs/AUDIT_LOG_BACKLOG.md` (BL-001).
- Two migrations in different Alembic chains once shared an identical revision id — harmless operationally (separate `version_table`s) but worth knowing if ever reconciling revision history for a compliance review.
- `AttachmentService.upload_attachment`'s authorization check was, for a real period of this system's history, silently never executed at all (a missing `await`) — meaning any upload during that window happened with **no enforced authorization**, though the *audit log entry itself* (if one existed for uploads — not confirmed) would still have recorded who performed it. This is now fixed.

## Recommendation for a security/compliance reviewer

Query `ticket_audit_logs`/`audit_logs` directly for the specific event types relevant to your review rather than assuming full coverage of every action a user could take — this system's audit coverage is broad but explicitly, deliberately incomplete in the areas noted above.
