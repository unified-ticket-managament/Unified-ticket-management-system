# Ticket & Interaction Tables

## `tickets`

The central work unit.

| Column | Type | Null? | Default | Business meaning |
|---|---|---|---|---|
| ticket_id | UUID | NOT NULL | uuid4 | PK |
| ticket_number | BigInteger | NOT NULL | `nextval('ticket_number_seq')` | The `TKT-<n>` human reference — UNIQUE, assigned once, never reused |
| client_id | UUID | NULL | | FK→users — **legacy** client-as-a-user-row model |
| client_company_id | UUID | | indexed | FK→clients — the current client model |
| agent_id | UUID | NULL | indexed | FK→users — current owner; null while unassigned/pool |
| assigned_by | UUID | NULL | | FK→users — who made the assignment |
| created_by | UUID | NULL | | FK→users |
| title | String(255) | | | |
| ticket_type | String(50) | | indexed | Free string, historically a source of a sweep-crashing bug when it didn't match a real `CategoryName` — see [16-known-limitations](../../16-known-limitations/performance-limitations.md) |
| current_status | enum `ticket_status_enum` | | OPEN, indexed | `OPEN, IN_PROGRESS, PENDING, WAITING_FOR_CLIENT, RESOLVED, CLOSED` |
| current_priority | enum `ticket_priority_enum` | | MEDIUM | `LOW, MEDIUM, HIGH, CRITICAL` — CRITICAL is escalation-only, never manually set |
| custom_fields | JSONB | | {} | Extensible per-ticket metadata |
| version | Integer | | 1 | Optimistic-concurrency-style counter (verify actual usage in code before relying on it for conflict detection) |
| closed_at / closed_by | DateTime / FK→users | NULL | | Only set on real closure, not on RESOLVED |
| created_at | DateTime tz | | indexed | |

## `interactions`

Every atomic communication event — email, reply, note, forward, status change record — represented as one row.

| Column | Type | Null? | Business meaning |
|---|---|---|---|
| interaction_id | UUID | PK | |
| ticket_id | UUID | NULL, indexed | FK→tickets — null for a pre-ticket pending item |
| interaction_type | String(50) | indexed | Plain string, not enum-backed (deliberately flexible) |
| status | enum `interaction_status_enum` | default PENDING, indexed | `PENDING, ASSIGNED, IGNORED` |
| direction | enum `interaction_direction_enum` | NOT NULL | `INBOUND, OUTBOUND, INTERNAL` |
| performed_by | UUID | indexed | FK→users |
| payload | JSONB | | Body, metadata, internal-note recipient snapshot, etc. |
| subject | String(500) | NULL | |
| is_visible | Boolean | default True, indexed | Soft-delete flag ("Hide") |
| removed_by / removed_at | | | Soft-delete audit fields |
| claimed_by / claimed_at | FK→users / DateTime | indexed | Pending-item claim tracking |
| tags | JSONB list | | |
| folder_id | UUID | indexed | FK→mail_folders |
| is_draft | Boolean | default False | |
| message_id | String(255) | UNIQUE, null | The email-dedup key |
| client_id | UUID | indexed | FK→clients |
| parent_interaction_id | UUID (self-FK) | indexed | Always resolves to the thread root |
| received_at | DateTime | indexed | |
| conversation_id / in_reply_to_message_id / references | String / String / JSONB | indexed (first two) | Threading headers from Graph |
| created_at | DateTime | indexed | |

## `attachments`

`attachment_id` (PK), `interaction_id` (FK→interactions, NOT NULL — attachments are keyed on the interaction, not the ticket, which is why pre-ticket draft attachments work), `filename`, `mime_type` (null), `size_bytes` (BigInteger, null), `storage_key` (Text), `bucket_name` (String(255), null), `scan_status` (String(20), default "pending" — plain string), `uploaded_at`, `created_at`/`updated_at` (both nullable, unusually — verify whether this is intentional if writing new code against them).

## `ticket_relations`

Composite PK `(ticket_id, related_ticket_id)`, both FK→tickets. **Symmetric** — a link between A and B is stored as two mirrored rows, not a directional one.

## `ticket_audit_logs` (ticketing's own audit trail — named to avoid colliding with RBAC's `audit_logs`)

`audit_id` (PK), `entity_type` (enum `audit_entity_type_enum`: TICKET/INTERACTION/ATTACHMENT/CLIENT/USER), `entity_id` (UUID, no FK — polymorphic per `entity_type`), `event_type` (enum `audit_event_type_enum`, ~30 values), `actor_id` (FK→users, null), `actor_name` (String(255), snapshotted at write time), `actor_role` (enum `audit_actor_role_enum`: AGENT/CLIENT/SYSTEM), `old_values`/`new_values` (JSONB), `ticket_id` (FK→tickets, nullable — a query-performance mirror, not the sole ticket association), `created_at`. Four composite indexes, each paired with `created_at DESC` (on `entity_type+entity_id`, `actor_id`, `event_type`, `ticket_id`).
