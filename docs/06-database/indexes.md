# Indexes & Constraints That Encode Business Rules

Several indexes in this schema aren't just performance optimizations — they **are** the enforcement mechanism for a business rule. These are the ones worth understanding, not just the full column-level index list (see [tables/](tables/) for that).

## Partial unique indexes (the "at most one active X" pattern)

| Index | Table | Condition | Business rule enforced |
|---|---|---|---|
| `ix_user_permission_overrides_active_unique` | `user_permission_overrides` | `WHERE revoked_at IS NULL`, on `(user_id, permission_id, COALESCE(scope_ticket_id, sentinel))` | At most one **active** override per user+permission+scope at a time, while preserving full grant→revoke→re-grant history. The `COALESCE` matters — a plain 3-column unique index would treat every `NULL` scope as distinct (Postgres default), silently allowing two simultaneous *global* grants. |
| `ix_permission_requests_pending_unique` | `permission_requests` | `WHERE status='PENDING'`, on `(requester_id, permission_id, COALESCE(scope_ticket_id, sentinel))` | At most one pending request per requester+permission+scope — but two *different* ticket scopes for the same permission don't collide with each other. |
| `ix_ticket_escalations_one_active_per_ticket` | `ticket_escalations` | `WHERE status != 'CLOSED'`, on `ticket_id` | At most one non-closed escalation per ticket at a time — this is what makes `auto_escalate_if_needed` safely idempotent. |
| `ix_escalation_handling_slas_one_active_per_escalation` | `escalation_handling_slas` | `WHERE breached_at IS NULL AND completed_at IS NULL`, on `escalation_id` | At most one currently-running Handling SLA per escalation. |

## The SLA breach idempotency ledger

`ix_sla_breach_notifications_unique` — a plain (non-partial) unique index on `(clock_type, clock_id, threshold, cycle)`, the actual target of the sweep's `INSERT ... ON CONFLICT DO NOTHING ... RETURNING`. This is the entire mechanism behind "each threshold notifies exactly once per crossing" — no application-level locking or check-then-insert race exists; the database constraint itself is the guard.

## Other uniqueness constraints worth knowing

| Constraint | Table | Meaning |
|---|---|---|
| `UNIQUE(email)` | `users` | One account per email |
| `UNIQUE(employee_number)` | `users` | Real, human-assigned employee ID — nullable (Client role is exempt) |
| `UNIQUE(ticket_number)` | `tickets` | The `TKT-<n>` reference, backed by a dedicated `SEQUENCE`, never reused |
| `UNIQUE(message_id)` | `interactions` | The email-deduplication key |
| `UNIQUE(client_id, lead_role)` | `client_assignments` | One AR/Coding/Posting Lead assignment per client per role |
| `UNIQUE(client_id, email)` | `client_contacts` | No duplicate contact rows per client |
| `UNIQUE(account_manager_id, category_id)` | `reporting_manager_teams` | No duplicate Reporting Manager assignment — but a category *can* have more than one Reporting Manager (the constraint doesn't prevent that), and one Account Manager can be Reporting Manager for more than one category |
| `UNIQUE(priority)` | `sla_policies` | Exactly one policy row per priority tier |
| `UNIQUE(role_id, permission_id)` (composite PK) | `role_permissions` | No duplicate grants |

## Check constraints

`client_assignments.lead_role` — `CheckConstraint(lead_role IN ('AR_LEAD', 'CODING_LEAD', 'POSTING_LEAD'))`.

## Performance indexes worth knowing about

`ix_tickets_updated_at`, `ix_tickets_pool_view`, `ix_tickets_title_trgm`, and several `interactions` indexes were flagged during an autogenerate diff as "real, deliberately-added prior work simply not declared in the current SQLAlchemy models" — a later migration's diff proposed dropping them, but that was deliberately stripped out rather than silently applied. If you ever run `alembic revision --autogenerate` against this chain and see these proposed for deletion, that's model/migration drift to investigate, not a change to actually apply.
