# Migrations

## Running migrations

```bash
cd unified-backend
alembic -c alembic_rbac/alembic.ini upgrade head
alembic -c alembic_ticketing/alembic.ini upgrade head
```

Order matters only against a genuinely empty database, since ticketing's tables FK into RBAC's `users`. Both are run in this exact order by `scripts/start.sh` and by the EC2 deploy workflow.

## `alembic_rbac` — 21 migrations, linear chain

Root: `9cadc1a089a3_initial_rbac_schema`. **Head: `a4c6e8b0d2f5_category_name_enum_to_varchar`**.

Chronological summary: initial schema → categories + `category_id` on users → `category_name` converted to a native enum → `user_permission_overrides` → `permission_requests` → `notifications` → `scope_ticket_id` added to overrides/requests → `permission_version` on users → revoke fields on permission requests → `selected_approver_id` on permission requests → `reporting_manager_teams` → ten Profile-module fields on users → Viewer role renamed to Client → real-org-data category names → `designation` on users → `employee_number` on users → `reporting_manager_id` on users → `is_on_leave` on users → `dismissed_at` on notifications → `user_categories` M2M table → **`category_name` converted from the native enum back to a plain VARCHAR(150), and the enum type dropped (head, 2026-08-21)**.

**`a4c6e8b0d2f5_category_name_enum_to_varchar` (head)**: `ALTER COLUMN category_name TYPE VARCHAR(150) USING category_name::text`, then `DROP TYPE category_name_enum`. Reverses the original design decision (a fixed, migration-gated enum) in favor of runtime-creatable categories — see [06-database/database-overview.md](database-overview.md). Its `downgrade()` is explicitly best-effort only: it fails if any row holds a category value added after this migration ran, since that value has no member in the enum it would need to recreate — the same "no meaningful downgrade" convention this codebase already uses for other one-way shape changes.

## `alembic_ticketing` — 59 migrations, one genuine branch-and-merge

Root: `c6f212b05143_initial_ticket_management_schema`. One real fork-and-merge exists: `b7d9f1a3c5e8_add_user_id_to_clients` has **two** `down_revision`s (two independently-created heads off a common ancestor, merged back into one) — despite its filename, this migration makes no schema change itself; it's purely the merge commit. **Head: `b5d7f9a1c3e6_add_category_transferred_audit_event_type`**.

### Notable migrations (non-obvious from filename alone)

| Migration | What it actually did |
|---|---|
| `317e5570c7df_add_sla_tables` | Also seeds 3 fixed-UUID `sla_policies` rows (HIGH/MEDIUM/LOW) — not just schema. |
| `277b41c65b53_add_ticket_number_sequence` | Introduced `ticket_number_seq`, backfilled `ticket_number` by `created_at ASC, ticket_id ASC` rank **against whatever tickets existed at that moment** — later found to be stale test data, not the real population (see below). |
| `f3a5c7e9b1d4_fix_orphaned_cycle_columns` | Repaired `resolution_slas.escalation_cycle`/`sla_breach_notifications.cycle` columns that existed live via out-of-band DDL but were never in any migration — this had been causing a 100%-failure ticket-creation bug before the fix. |
| `c4d6e8f0a2b4_renumber_tickets_contiguous` | A **one-time data fix**, not a schema change — re-ran the same creation-order ranking against the *current* live population only, correcting a real dataset where `ticket_number` jumped from `TKT-06` to `TKT-187` due to ~180 since-deleted test tickets present when `277b41c65b53` first ran. No sensible `downgrade()` exists for this one. |
| `a4c6e8f0b2d4_fix_client_inbox_email_distribution` | Corrects `clients.inbox_email` (previously auto-picked from contacts instead of being a curated distribution address); makes it nullable; migrates old wrong values into `client_contacts`. |
| `d7f9b1c3e5a7_assignment_chain_escalation_routing` | Adds the `ASSIGNMENT_CHAIN` escalation-level enum value and `owner_roles`/`chain_owner_ids`/`chain_position` columns — retiring the older TEAM_LEAD/MANAGER role-ladder escalation model in favor of assignment-chain routing. |
| `a2c4e6f8b0d3_rename_sla_manually_paused_resumed` | `ALTER TYPE ... RENAME VALUE` — renamed `SLA_MANUALLY_PAUSED`/`SLA_MANUALLY_RESUMED` to `SLA_PAUSED`/`SLA_RESUMED` in place, so both automatic and manual pause/resume share one event pair. |
| `d33a0758e3c4_add_escalation_handling_slas` | Adds the `escalation_handling_slas` table only — a related autogenerate diff also proposed dropping several unrelated, deliberately-kept indexes (see [indexes.md](indexes.md)); that drift was stripped out of this migration rather than silently applied. |
| `9c4e6a8b1d3f_add_critical_to_ticket_priority_enum` | `ALTER TYPE ... ADD VALUE IF NOT EXISTS` — widens `ticket_priority_enum` with `CRITICAL`. |
| `b7f1d3e5a9c2_add_critical_sla_policy_row` | Adds the CRITICAL-tier `SLAPolicy` row (5 min First Response, 60 min Resolution, 10 min Ack Window, 25% Handling, 50/80% warnings). |
| `e6a8c0d2f4b6` | Adds `selected_approver_id` to `permission_requests` and widens the pending-uniqueness index to include `scope_ticket_id` — the "address a request to one specific person" redesign. |

## Adding a Postgres enum value

Both chains use `ALTER TYPE ... ADD VALUE IF NOT EXISTS` (never a full type replacement) for widening an existing native enum — see the repo's own `add-postgres-enum-value` skill (`ticketing-service/.claude/skills/`, referenced from root `CLAUDE.md`) before adding a new member to `TicketPriority`, `EscalationLevel`, `EscalationStatus`, `SLAClockStatus`, or `AuditEventType`. **Note**: `ALTER TYPE ... ADD VALUE` cannot run inside the same transaction as other DDL in some Postgres versions — check the skill/existing migrations for the exact pattern used in this codebase before writing a new one by hand.

## A stale-schema symptom looks exactly like a logic bug — check this first

A reported "bug" in the escalation-acceptance code path once turned out to be the dev database sitting 4 migrations behind head (missing `ticket_escalations.handling_stage`/`handling_stage_started_at`/`handling_stage_due_at`, `resolution_slas.active_target_minutes`/`escalation_cycle`, `sla_policies.handling_stage_percentages`) — every affected code path 500'd with `UndefinedColumnError` until `alembic -c alembic_ticketing/alembic.ini upgrade head` was run, with **zero application-code changes** needed. **Before assuming an SLA/escalation bug report needs a code fix, run `alembic -c alembic_ticketing/alembic.ini current` against `heads`** (and the `alembic_rbac` equivalent) first.
