# Data Retention

No formal data-retention policy document exists in the repository. This page describes what's actually implemented — soft-delete vs. hard-delete vs. append-only — as observed in the schema and services.

## Never deleted (append-only or status-transition-only)

| Table | Behavior |
|---|---|
| `permission_requests` | Never deleted — `status` transitions `PENDING → APPROVED/REJECTED`, `APPROVED → REVOKED`. Full lifecycle is always queryable via the History view. |
| `user_permission_overrides` | Never hard-deleted — `revoked_at`/`revoked_by` soft-revoke, preserving a full grant→revoke→re-grant history. |
| `resolution_sla_pause_intervals` | Explicitly append-only — a new row per pause, never overwritten. |
| `ticket_audit_logs` / `audit_logs` | Append-only by normal application flow. RBAC's own table has a Super-Admin-gated manual `DELETE` endpoint, but this is an administrative escape hatch, not part of ordinary retention behavior. |
| `sla_breach_notifications` | Never deleted — this is the idempotency ledger; deleting a row would let a threshold re-notify. |

## Soft-deleted

| Table/column | Mechanism |
|---|---|
| `interactions.is_visible` / `.removed_by` / `.removed_at` | "Hide" on an interaction is a soft-delete, not a real row removal. |
| `notifications.dismissed_at` | "Clear All" sets this rather than deleting rows. |

## Hard-deleted (real DELETE)

| Table | Trigger |
|---|---|
| `attachments` | `DELETE /attachments/{id}` — a real delete, gated by `ticket:delete_attachment`. |
| `mail_folders` | `DELETE /folders/{id}`. |
| `rules` | `DELETE /rules/{id}`. |
| `audit_logs` (RBAC) | Super-Admin-only manual endpoint. |
| `users` (historically, via a one-off cleanup) | The 2026-08-10 employee-data cleanup removed 25 dummy/demo accounts via targeted, dependency-checked, transactional deletes — not routine, and required first enumerating **all 30** foreign-key columns referencing `users.user_id` via Postgres's own `information_schema` catalogs, since a manual checklist had missed one (`message_read_receipts.user_id`). See [17-roadmap](../17-roadmap/README.md)/[19-release-notes](../19-release-notes/README.md) for this event's context. |

## Ticket deletion and `ticket_number`

Tickets can apparently be deleted (the 2026-08-10 ticket-renumbering incident references "test tickets were cleaned up afterward"), but `ticket_number` is **never reused** even if the owning ticket is deleted — enforced by the sequence never resetting backward, not by any soft-delete flag on `tickets` itself (no such flag was found on the `Ticket` model).

## PHI/PII retention

No automated data-retention/expiry policy (e.g. "delete client PII after N years") was found in code or migrations. See [08-security/phi-pii-handling.md](../08-security/phi-pii-handling.md) for what PHI/PII this system actually handles and where.

## Known gap

There is no documented, automated retention/archival policy for any table in this system — everything described above is either explicit soft-delete/append-only behavior or an ordinary hard-delete endpoint, not a time-based retention rule. If a compliance requirement (e.g. "purge closed tickets after 7 years") exists, it is **not implemented in code** as of this documentation pass.
