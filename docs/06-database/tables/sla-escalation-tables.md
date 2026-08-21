# SLA & Escalation Tables

## `sla_policies`

One row per `TicketPriority` value (LOW/MEDIUM/HIGH/CRITICAL — 4 rows).

| Column | Type | Business meaning |
|---|---|---|
| policy_id | UUID PK | |
| priority | enum `ticket_priority_enum`, UNIQUE | The tier this policy governs |
| first_response_target_minutes | Integer NOT NULL | First Response SLA target |
| resolution_target_minutes | Integer NOT NULL | Resolution SLA target |
| escalation_ack_target_minutes | Integer NOT NULL | Ack-window before auto-advance |
| handling_sla_percentage | Float, default 25.0 | **Superseded** — `handling_stage_percentages` (JSONB) is the field actually read now |
| handling_stage_percentages | JSONB list, NOT NULL | Per-stage Handling SLA percentages |
| warning_1_percentage | Float, default 50.0 | "Half elapsed" threshold |
| warning_2_percentage | Float, default 80.0 | "At risk" threshold |
| is_active | Boolean, default True | |

Live-editable via `PATCH /sla/policies/{id}` (Super Admin/Site Lead only) — not a hardcoded constant.

## `first_response_slas`

One row per thread-root interaction.

| Column | Type | Business meaning |
|---|---|---|
| first_response_sla_id | PK | |
| interaction_id | FK→interactions, UNIQUE, indexed | The thread root this clock belongs to |
| client_id | FK→clients, indexed | Denormalized for query performance |
| priority | enum, snapshotted at creation | |
| status | enum `sla_clock_status_enum`, default PENDING, indexed | `PENDING, RUNNING, PAUSED, COMPLETED` |
| started_at / due_at (indexed) / completed_at | | |
| completion_reason | String(30), plain string | e.g. `"OTP_RECOGNIZED"`, agent-reply reason |
| resulting_ticket_id | FK→tickets | Set once a ticket is created from this thread |

Composite index `(status, due_at)` backs the sweep's active-clock scan.

## `resolution_slas`

One row per ticket (1:1, UNIQUE `ticket_id`).

| Column | Type | Business meaning |
|---|---|---|
| resolution_sla_id | PK | |
| ticket_id | FK→tickets, UNIQUE, indexed | |
| client_id | FK→clients, indexed | Denormalized |
| priority | enum, current snapshot | Reshifted on priority change |
| status | enum, default RUNNING, indexed | `RUNNING, PAUSED, COMPLETED` (+ shared members with the other clock enum) |
| started_at | | |
| due_at | indexed | **Mutable, shifting** value — reshifted on priority change, not an accumulated-elapsed counter |
| active_target_minutes | Integer | Current effective target |
| paused_at / total_paused_seconds | | `total_paused_seconds` is display-only — the real pause history lives in the child table below |
| completed_at | | Set only when the ticket is **closed**, never merely resolved |
| escalation_cycle | Integer, default 0 | Restart counter feeding the SLA-breach-notification dedup — bumped when an escalation cycle restarts, so thresholds can re-notify |

Composite index `(status, due_at)`.

## `resolution_sla_pause_intervals`

Append-only child ledger of `resolution_slas`.

`pause_interval_id` (PK), `resolution_sla_id` (FK, indexed), `paused_at`, `resumed_at` (null while still paused), `pause_reason` (String(30), plain string — e.g. distinguishes automatic `WAITING_FOR_CLIENT` vs. `manual_override`), `triggering_interaction_id` (FK→interactions, null), `created_at`. Index on `(resolution_sla_id, paused_at)`.

## `ticket_escalations`

| Column | Type | Business meaning |
|---|---|---|
| escalation_id | PK | |
| ticket_id | FK→tickets, indexed | |
| resolution_sla_id | FK, nullable | Display-link only — escalation never writes to this clock's own columns |
| level | enum `ticket_escalation_level_enum` | `TEAM_LEAD`/`MANAGER` (both retired), `ASSIGNMENT_CHAIN`, `SITE_LEAD` |
| status | enum `ticket_escalation_status_enum`, default ACTIVE, indexed | `ACTIVE, ACKNOWLEDGED, CLOSED` |
| owner_ids | JSONB list | Current owners — the real scoping key for the Escalated tab and Acknowledge action |
| owner_roles | JSONB dict | |
| chain_owner_ids | JSONB list | Frozen assignment chain at creation time |
| chain_position | Integer, default 0 | |
| original_priority | enum | Snapshot before the CRITICAL override |
| has_advanced_past_starting_level | Boolean | |
| handling_stage / handling_stage_started_at / handling_stage_due_at | Integer / DateTime / DateTime | Non-null `due_at` = "currently running" |
| triggered_by | String(20), plain string | `MANUAL` / `AUTO_SLA_BREACH` |
| triggered_by_user_id | FK→users | |
| created_at / level_started_at / ack_due_at (indexed) | | |
| acknowledged_at / acknowledged_by | FK→users | Step 1 completion |
| closed_at / closed_reason | | String(30), plain |
| updated_at | | |

Partial index on `handling_stage_due_at WHERE NOT NULL`; **partial UNIQUE** `ix_ticket_escalations_one_active_per_ticket` on `ticket_id WHERE status != 'CLOSED'`.

## `escalation_handling_slas`

A second, independent post-acceptance clock — never written by anything except `EscalationHandlingSlaService`.

| Column | Type | Business meaning |
|---|---|---|
| escalation_handling_sla_id | PK | |
| escalation_id | FK→ticket_escalations, indexed | |
| ticket_id | FK→tickets, indexed | Denormalized |
| status | enum `sla_clock_status_enum` (reused, `create_type=False`) | `RUNNING`/`COMPLETED` only in practice |
| target_seconds | Integer | 25% of the *original* Resolution SLA target, computed once |
| started_at / due_at (indexed) | | |
| breached_at | nullable | Doubles as the sweep's idempotency guard for this clock |
| completed_at | | |

Partial UNIQUE `ix_escalation_handling_slas_one_active_per_escalation` on `escalation_id WHERE breached_at IS NULL AND completed_at IS NULL`.

## `sla_breach_notifications` (idempotency ledger)

`sla_breach_notification_id` (PK), `clock_type` (String(20): `FIRST_RESPONSE`/`RESOLUTION`), `clock_id` (UUID, **no FK** — polymorphic, points at either clock table depending on `clock_type`), `threshold` (String(20): `HALF_ELAPSED`/`AT_RISK`/`BREACHED`/`ESCALATED`), `cycle` (Integer, default 0), `notified_at`. **UNIQUE** `(clock_type, clock_id, threshold, cycle)` — the literal `ON CONFLICT` target that makes each crossing notify exactly once.
