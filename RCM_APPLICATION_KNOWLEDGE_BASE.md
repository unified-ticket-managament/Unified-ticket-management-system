# RCM Ticketing Application — Complete Knowledge Base (for Synthetic Environment Design)

**Purpose of this document**: a single, self-contained, authoritative technical + business specification of this application, written for another AI (or engineer) building a production-aligned synthetic RCM data/environment — with no access to prior conversations about this codebase. Every claim below is either (a) verified directly against the current source code of the running monorepo (`unified-backend/`, `shared_models/`), or (b) explicitly flagged as an assumption, a live-database-only state that cannot be re-verified from source, or an open design question. Nothing is invented to fill a gap — gaps are called out.

**Companion documents in this repo** (narrower-scope, still accurate, safe to cross-reference): `ML_TICKETING_SCHEMA_REFERENCE.md` (schema reference written specifically for an AI-ticket-recommendation ML project) and `RCM_TICKETING_KNOWLEDGE_BASE.md` (business/domain brief for that same ML project's synthetic data generator). This document supersedes both in scope — it covers the whole application, not just the recommendation feature — but does not contradict them; where they overlap, values were re-verified against source for this document.

**How this document was produced**: a direct, code-verified read of `unified-backend/app/` (both `rbac` and `ticketing` sub-packages), `shared_models/`, the two Alembic migration chains, and the RBAC/ticketing seed scripts — not from documentation, memory, or assumption, except where explicitly labeled "project memory" (a point-in-time note about live database state that cannot be re-derived from source code, and should be re-verified before being trusted as current).

---

## 1. Business Overview & Application Purpose

This is a **ticket management system built for Revenue Cycle Management (RCM) support** — the operational arm of a medical billing company that handles email-based support traffic from its client companies (physician practices, clinics, billing departments) about claims, payments, prior authorizations, and patient billing accounts.

**Structural premise**: each client company has one shared inbox address. Any number of people at that client company can email in from that address (or that domain); every inbound message lands in one company-wide mail pool before a human triages it. The product is two things bolted together:

1. **A mailbox-to-ticket triage tool** — inbound email → shared pool → an agent decides "reply and archive, no ticket needed" vs. "this needs operational tracking as a ticket," or attaches the email onto an already-existing ticket.
2. **A ticket work-tracking tool** once a ticket exists — assignment, replies, internal notes, attachments, status/priority changes, two independent SLA clocks, and an internal escalation ownership chain when work runs late.

A **Client row is a company, not an individual person** (`unified-backend/app/ticketing/models/client.py`) — e.g., "Lakeside Medical Billing LLC." Any number of real people at that company can be the sender of an inbound email; all route to the same `Client` row via address matching, and to one owning Account Manager (`clients.account_manager_id`). For this system, "the customer" is always the client company, never an individual patient — patient-level detail (if it appears at all) lives only inside free-text message bodies, never as a modeled entity.

**Deployment shape** (for environment-design context, not a business fact): one FastAPI backend (`unified-backend/`) serves both a "ticket workspace" (embedded inside a larger Next.js shell app that also owns authentication/RBAC/org administration) and a standalone Vite/React ticketing frontend. One physical Postgres database (Neon) backs everything, written to by two independently-versioned Alembic migration chains (`alembic_rbac` for users/roles/permissions/categories, `alembic_ticketing` for tickets/interactions/SLA/escalation).

---

## 2. RCM Domain Terminology (Glossary)

The system's ticket categories and conversation content are medical-billing-specific. A synthetic generator needs this vocabulary to produce content that reads as authentic rather than generic "customer support."

| Term | Meaning |
|---|---|
| **RCM (Revenue Cycle Management)** | The end-to-end process of getting a healthcare provider paid: registration/eligibility → charge capture → claim submission → payment posting → denial management → AR follow-up. |
| **Claim** | A formal request submitted to a payer (insurance company) for payment for services rendered. |
| **Payer** | The insurance company or government program (Medicare, Medicaid, commercial plans) responsible for paying a claim. |
| **Clearinghouse** | An intermediary that transmits claims electronically from provider to payer, scrubbing/validating them first. |
| **EOB (Explanation of Benefits)** | A payer statement explaining what was paid, denied, and why. |
| **ERA (Electronic Remittance Advice)** | The machine-readable electronic equivalent of an EOB. |
| **Denial** | A payer's refusal to pay a claim, accompanied by a reason code. |
| **CARC / RARC** | Claim/Remittance Adjustment Reason Codes — standardized codes explaining a denial or adjustment (e.g., CO-16 "missing information," CO-97 "benefit bundled into another service," CO-29 "timely filing limit expired"). |
| **Appeal** | A formal request to reconsider a denied claim. |
| **Resubmission** | Re-sending a corrected claim after a denial or rejection. |
| **Prior Authorization (PA / Auth)** | Payer approval required *before* a service is performed, to guarantee payment. Can be denied, expire, or require a "retro" (after-the-fact) request. |
| **Eligibility Verification** | Confirming a patient's insurance coverage/benefits before or at time of service. |
| **Coordination of Benefits (COB)** | Determining which of a patient's multiple payers is primary vs. secondary. |
| **Charge Entry** | Entering billable services (CPT/HCPCS procedure codes) with diagnosis codes (ICD-10) into the billing system to generate a claim. |
| **CPT / HCPCS code** | Procedure/service code on a claim. |
| **ICD-10 code** | Diagnosis code on a claim. |
| **Modifier** | A two-character code appended to a CPT code altering its meaning (e.g., bilateral procedure, multiple procedures). |
| **NPI (National Provider Identifier)** | Unique ID for a healthcare provider/organization. |
| **Superbill / Encounter Form** | The source document listing diagnoses/procedures for a visit, used to generate a claim. |
| **Timely Filing Limit** | The payer-imposed deadline (often 90–180 days) to submit or appeal a claim. |
| **Accounts Receivable (AR)** | Unpaid claims/balances owed to the provider. "AR follow-up" = working aged claims until they're paid or resolved. |
| **Aging Bucket** | AR grouped by how long it's been outstanding (0–30, 31–60, 61–90, 90+ days) — older buckets are higher urgency. |
| **Payment Posting** | Recording payments/adjustments from an EOB/ERA into the billing system against the correct claim/patient account. |
| **Contractual Adjustment / Write-off** | The portion of a charge the provider agrees not to collect (payer contract rate, or bad debt). |
| **Patient Responsibility** | The portion of a bill the patient (not the payer) owes — copay, deductible, coinsurance. |
| **Credentialing** | Verifying a provider's qualifications with a payer so they can bill that payer at all (occasionally adjacent to PA/Eligibility tickets). |

### Ticket categories (the one classification axis)

`CategoryName` — 7 fixed values, each mapping to one RCM business function:

| Category | RCM function | Characteristic issue types |
|---|---|---|
| **Eligibility** | Verifying patient insurance coverage/benefits | Coverage terminated/inactive, wrong plan on file, COB mismatch, benefits verification delay, plan requires referral not on file |
| **Patient Calling** | Patient-facing billing communication | Balance/statement disputes, payment plan requests, demographic/address corrections, complaint about a collections call |
| **AR (Accounts Receivable)** | Following up on unpaid/aged claims | Aged claim with no payer response, appeal status check, claim stuck "in process," aging-bucket escalation |
| **Payment Posting** | Recording payments from EOBs/ERAs | Payment posted to wrong account/claim, EOB mismatch, missing/unposted ERA, refund request from overpayment |
| **PA (Prior Authorization)** | Getting payer approval before service | Auth denied, auth expired before service rendered, missing clinical documentation, need retro-authorization, wrong CPT on auth |
| **Charge Entry** | Entering billable services into the system | Coding error (wrong CPT/ICD-10), missing modifier, charge never entered, duplicate charge entered |
| **Claims** | Submitting and resolving claims | Claim denied (CARC-style reason), claim rejected at clearinghouse, needs resubmission, needs formal appeal, missing NPI/provider info |

**Schema gap to preserve, not "fix," in synthetic data**: `Ticket.ticket_type` is a plain `String(50)` with **no foreign key** to `categories` — nothing at the database level stops an arbitrary string here; only the frontend dropdown enforces the 7 values. Sample `ticket_type` from the 7 values above for realism, but the schema itself will accept anything.

---

## 3. Roles & Organizational Model

### 3.1 RBAC roles (`shared_models.models.Role`, no rank column — hierarchy is application-code-only)

| Role | Ticketing responsibility |
|---|---|
| **Super Admin** | Unrestricted oversight of the entire application (RBAC + ticketing). Not typically a ticket actor in realistic conversation content. |
| **Site Lead** | Company-wide oversight; global inbox catch-all for unmatched mail; terminal escalation level (`SITE_LEAD`). |
| **Account Manager** | Owns a set of client companies (`clients.account_manager_id`) — the actual client-facing correspondent in most ticket threads (the address clients see replies come from). Escalation level `MANAGER`. Also the role layered with the optional "Reporting Manager" HR responsibility (§16). |
| **Team Lead** | Operational head of one work-specialization category (Eligibility/AR/Claims/etc.); supervises that category's Staff. Escalation level `TEAM_LEAD` (the usual starting point). |
| **Staff** | Does the hands-on category-scoped work (works claims, posts payments, verifies eligibility). The most common `agent_id`/reply-author for routine ticket work. |
| **Viewer** | The one role outside the Super Admin > Site Lead > Account Manager > Team Lead > Staff hierarchy entirely — client-facing, not a ticket actor. Default permissions: `user:view`, `role:view`, `permission:view` only. |

### 3.2 Three genuinely independent relationships between users (do not collapse into one column)

1. **Real reporting line** — `User.manager_id` (an Account Manager) / `User.teamlead_id` (a Team Lead) — pre-existing, straightforward "who does this person report to."
2. **Reporting Manager mapping** (`reporting_manager_teams` table) — a genuinely many-to-many Account Manager ↔ Category assignment representing an *additional*, optional HR/people-management responsibility layered onto an existing Account Manager. It is never a separate role and never implied by simply holding the Account Manager role. No uniqueness constraint on the category side — a category can have more than one Reporting Manager. Gated by permission `org:manage_reporting_managers` (Super Admin/Site Lead only by default).
3. **Ticket-assignment capability** — every Account Manager can hand ticket work to **any** Team Lead company-wide, regardless of category/department (see §13 Assignment Rules) — this is wider than either relationship #1 or #2 and is a deliberate business rule, not a bug.

**Scope note (explicitly confirmed, not built)**: the real HR action surface a Reporting Manager would need (Approve/Reject Leave, View Attendance/Performance/Timesheets, Conduct Reviews, Team KPIs, etc.) has **zero existing UI/backend surface** anywhere in this codebase — only the data-model/permission/assignment/org-chart plumbing exists.

---

## 4. Major Modules & Workflows (map)

| Module | Owns | Key concepts |
|---|---|---|
| **RBAC** | Users, Roles, Permissions, Categories, Permission Overrides, Permission Requests, Reporting Managers, RBAC-native Audit Log | Authentication (JWT), authorization (role defaults + per-user overrides, optionally ticket-scoped), org structure |
| **Ticketing** | Clients, Interactions (the unified email/reply/note timeline), Tickets, Attachments, Ticket Relations, Resolution SLA, First Response SLA, Ticket Escalation, Escalation Handling SLA, SLA Policy, SLA Breach Notification ledger, ticketing-native Audit Log | Mail intake → triage → ticket lifecycle → SLA clocks → escalation chain |
| **Notifications** | Notification rows, Server-Sent-Events push | In-app + email notification of business events (assignment, SLA thresholds, escalation, permission changes) |

**End-to-end flow, condensed** (see §11 for full field-by-field detail):

```
Inbound email (Microsoft Graph)
  → duplicate check (message_id)
  → Client resolution (sender/recipient vs. clients.inbox_email; unmatched → Site Lead)
  → deterministic thread match (conversation_id → in_reply_to → references)
       ├─ matched onto an existing ticketed thread → auto-attach, done
       └─ no match → new "pool" Interaction (ticket_id=NULL, status=PENDING), FirstResponseSLA starts
  → sits in shared Mail/Inbox pool until an agent acts
  → agent: reply & archive (no ticket) | attach to existing ticket | Create Ticket
  → Ticket created: ResolutionSLA starts, FirstResponseSLA completes (reason="TICKET_CREATED")
  → ticket work: replies / internal notes / attachments / status / priority / transfer / claim
  → possible escalation if it runs late (auto or manual)
  → RESOLVED (agent-proposed) → CLOSED (supervisor-verified, only CLOSED stops the Resolution SLA clock)
```

---

## 5. Database Schema

Two independent Alembic chains write to one physical Postgres database: `alembic_rbac` (users/roles/permissions/categories) and `alembic_ticketing` (tickets/interactions/SLA/escalation). Tables grouped by owning chain.

### 5.A — RBAC domain (`alembic_rbac`)

#### `users`
*Model: `shared_models/shared_models/models/user.py`. The single cross-cutting identity record shared by both domains.*

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `user_id` | UUID | N | `uuid4()` | **PK** |
| `name` | String(100) | N | — | |
| `email` | String(255) | N | — | **Unique**, indexed |
| `password_hash` | String(255) | N | — | (not `hashed_password`) |
| `role_id` | UUID | N | — | **FK** → `roles.role_id` |
| `manager_id` | UUID | Y | — | **FK (self)** → `users.user_id` |
| `teamlead_id` | UUID | Y | — | **FK (self)** → `users.user_id` |
| `category_id` | UUID | Y | — | **FK** → `categories.category_id` |
| `is_active` | Boolean | N | `True` | |
| `permission_version` | Integer | N | `1` | cache-busting counter, bumped on any RBAC-relevant change to this user |
| `date_of_birth` | Date | Y | — | |
| `alternate_email` | String(255) | Y | — | |
| `phone_number` | String(30) | Y | — | |
| `office_location` | String(255) | Y | — | |
| `department` | String(100) | Y | — | one-time backfilled from category name; independent of `category_id`, display-only |
| `team` | String(100) | Y | — | display-only, no edit surface writes it |
| `language` | String(10) | Y | `server_default='en'` | |
| `date_format` | String(20) | Y | `server_default='MM/DD/YYYY'` | |
| `time_format` | String(10) | Y | `server_default='12h'` | |
| `time_zone` | String(50) | Y | — | |
| `default_dashboard` | String(50) | Y | `server_default='Dashboard'` | |
| `created_at` / `updated_at` | DateTime(tz) | N | now() | |

No `ondelete` on any of the 4 FKs (deliberate, app-enforced).

#### `roles`
| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `role_id` | UUID | N | `uuid4()` | **PK** |
| `name` | String(100) | N | — | **Unique** |

No `rank`/`level`/`description` column — hierarchy is implicit in application code only.

#### `categories`
| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `category_id` | UUID | N | `uuid4()` | **PK** |
| `category_name` | native enum `category_name_enum` | N | — | **Unique** |

7 fixed rows, fixed UUIDs (see §17 Reference Data). No timestamps on this table.

#### `permissions`
| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `permission_id` | UUID | N | `uuid4()` | **PK** |
| `permission_name` | String(100) | N | — | **Unique**, e.g. `"ticket:create"` |
| `description` | Text | Y | — | |
| `created_at` | DateTime(tz) | N | app-side now() | |

#### `role_permissions`
Pure join table. **Composite PK** `(role_id, permission_id)`, both `ondelete="CASCADE"`. No extra columns.

#### `audit_logs` (RBAC-native — distinct from ticketing's `ticket_audit_logs`)
| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `audit_log_id` | UUID | N | `uuid4()` | **PK** |
| `user_id` | UUID | Y | — | **FK** → `users`, `ondelete=SET NULL` |
| `action` | String(100) | N | — | indexed, free string, e.g. `"auth.login"` |
| `entity_type` | String(100) | N | — | indexed, free string |
| `entity_id` | String(100) | Y | — | plain string, no FK |
| `old_value` / `new_value` | Text | Y | — | JSON-serialized manually via `json.dumps` by callers — **not JSONB** |
| `ip_address` | String(50) | Y | — | |
| `user_agent` | String(500) | Y | — | |
| `timestamp` | DateTime(tz) | N | app-side now() | indexed |

#### `user_permission_overrides`
| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `override_id` | UUID | N | `uuid4()` | **PK** |
| `user_id` | UUID | N | — | **FK** → `users`, CASCADE |
| `permission_id` | UUID | N | — | **FK** → `permissions`, CASCADE |
| `granted_by` | UUID | Y | — | **FK** → `users`, SET NULL |
| `reason` | Text | Y | — | |
| `granted_at` | DateTime(tz) | N | app-side now() | |
| `expires_at` | DateTime(tz) | Y | — | blank = permanent |
| `revoked_at` / `revoked_by` | DateTime(tz)/UUID | Y | — | soft-revoke, never deleted |
| `scope_ticket_id` | UUID | Y | — | plain UUID, **no FK** (cross-chain reference) |

Partial unique index: `(user_id, permission_id, COALESCE(scope_ticket_id, '00000000-0000-0000-0000-000000000000'::uuid)) WHERE revoked_at IS NULL` — at most one active grant per user+permission+scope. **Purely additive** — there is no mechanism to grant a user *less* than their role default (a "role allows, override revokes" scenario isn't buildable without new schema).

#### `permission_requests`
| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `request_id` | UUID | N | `uuid4()` | **PK** |
| `requester_id` | UUID | N | — | **FK** → `users`, CASCADE |
| `permission_id` | UUID | N | — | **FK** → `permissions`, CASCADE |
| `requested_role` | String(100) | N | — | immutable display snapshot only |
| `selected_approver_id` | UUID | Y | — | **FK** → `users`, SET NULL — real routing key |
| `reason` | Text | N | — | |
| `scope_ticket_id` | UUID | Y | — | no FK |
| `status` | String(20) | N | `"PENDING"` | plain string; `PENDING/APPROVED/REJECTED/REVOKED` |
| `reviewed_by` / `reviewed_at` / `review_comment` | UUID/DateTime/Text | Y | — | |
| `expires_at` | DateTime(tz) | Y | — | |
| `granted_override_id` | UUID | Y | — | **FK** → `user_permission_overrides`, SET NULL |
| `revoked_by` / `revoked_at` / `revoke_reason` | UUID/DateTime/Text | Y | — | |
| `created_at` | DateTime(tz) | N | app-side now() | |

Partial unique index: `(requester_id, permission_id, COALESCE(scope_ticket_id, sentinel)) WHERE status='PENDING'`.

#### `reporting_manager_teams`
| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | UUID | N | `uuid4()` | **PK** |
| `account_manager_id` | UUID | N | — | **FK** → `users`, CASCADE |
| `category_id` | UUID | N | — | **FK** → `categories`, CASCADE |
| `assigned_by` | UUID | Y | — | **FK** → `users`, SET NULL |
| `assigned_at` | DateTime(tz) | N | app-side now() | |

Unique constraint on `(account_manager_id, category_id)` pair only — **no** uniqueness on `category_id` alone; a category can have several Reporting Managers.

### 5.B — Ticketing domain (`alembic_ticketing`)

#### `tickets`
*Model: `unified-backend/app/ticketing/models/ticket.py`. The core work item.*

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `ticket_id` | UUID | N | `uuid4()` | **PK** |
| `client_id` | UUID | Y | — | **FK** → `users` — **legacy, always NULL for new tickets, do not write to it** |
| `client_company_id` | UUID | Y | — | **FK** → `clients.client_id`, indexed — the real client-ownership column |
| `agent_id` | UUID | Y | — | **FK** → `users`, indexed — currently working it |
| `created_by` | UUID | Y | — | **FK** → `users` |
| `title` | String(255) | N | — | GIN trigram index (DB-only) |
| `ticket_type` | String(50) | N | — | indexed; **no FK to `categories`** |
| `current_status` | enum `ticket_status_enum` | N | `OPEN` | indexed |
| `current_priority` | enum `ticket_priority_enum` | N | `MEDIUM` | indexed; `CRITICAL` is intended to be system-set only (see §19 for a confirmed enforcement gap) |
| `custom_fields` | JSONB | N | `{}` | always `{}` in practice — no UI writes it |
| `version` | Integer | N | `1` | optimistic concurrency |
| `closed_at` / `closed_by` | DateTime(tz)/UUID | Y | — | **FK** (closed_by) → `users` |
| `created_at` | DateTime(tz) | N | now() | indexed |
| `updated_at` | DateTime(tz) | N | now()/onupdate | DB-only index |

**DB-only indexes** (not on the model, only via raw migration SQL): `ix_tickets_pool_view` (partial, `WHERE agent_id IS NULL AND current_status='OPEN'`), `ix_tickets_title_trgm` (GIN trigram), `ix_tickets_updated_at`.

**Query-time computed fields, never stored — do not model as real columns**: `is_escalated`, `escalation_level`, `escalation_status`, `escalation_ack_due_at`, `is_escalation_owner`, `escalation_pending_acceptance`, `resolution_sla_tier`, `client_name`, `client_company_name`, `agent_name`, `created_by_name`, `closed_by_name`, `related_tickets`.

#### `interactions`
*Model: `unified-backend/app/ticketing/models/interaction.py`. The unified timeline row for every email, reply, note, and attachment event — pre-ticket and post-ticket alike.*

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `interaction_id` | UUID | N | `uuid4()` | **PK** |
| `ticket_id` | UUID | **Y** | — | **FK** → `tickets`, indexed. NULL while unticketed |
| `interaction_type` | String(50) | N | — | **plain string, not a Postgres enum** |
| `status` | enum `interaction_status_enum` | N | `PENDING` | `PENDING/ASSIGNED/IGNORED` |
| `direction` | enum `interaction_direction_enum` | N | — | `INBOUND/OUTBOUND/INTERNAL` |
| `performed_by` | UUID | Y | — | **FK** → `users`; NULL for inbound email |
| `payload` | JSONB | N | `{}` | shape varies by type |
| `subject` | String(500) | Y | — | GIN trigram index; NULL for ATTACHMENT rows |
| `is_visible` | Boolean | N | `True` | soft-delete flag |
| `removed_by` / `removed_at` | UUID/DateTime(tz) | Y | — | **FK** (removed_by) → `users` |
| `claimed_by` / `claimed_at` | UUID/DateTime(tz) | Y | — | **FK** (claimed_by) → `users` |
| `tags` | JSONB (list) | N | `[]` | |
| `folder_id` | UUID | Y | — | **FK** → `mail_folders.folder_id` |
| `is_draft` | Boolean | N | `False` | |
| `message_id` | String(255) | Y | — | **Unique** — RFC 5322 Message-ID |
| `client_id` | UUID | Y | — | **FK** → `clients` |
| `parent_interaction_id` | UUID | Y | — | **FK (self)** → `interactions`; NULL = thread root |
| `received_at` | DateTime(tz) | Y | — | SLA clock start; NULL for replies/notes |
| `conversation_id` | String(255) | Y | — | Microsoft Graph thread id |
| `in_reply_to_message_id` | String(255) | Y | — | |
| `references` | JSONB (list) | Y | — | |
| `created_at` | DateTime(tz) | N | now() | |

**Unique partial index**: `ix_interactions_one_draft_per_thread_per_agent` on `(parent_interaction_id, performed_by) WHERE is_draft AND is_visible` — one active draft per thread per agent, enforced in Postgres.

**Removed column, do not include**: `snoozed_until` — added then later dropped (Snooze feature removed).

#### `attachments`
| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `attachment_id` | UUID | N | `uuid4()` | **PK** |
| `interaction_id` | UUID | **N** | — | **FK** → `interactions` — keyed on interaction, not ticket; no index |
| `filename` | String(255) | N | — | |
| `mime_type` | String(100) | Y | — | |
| `size_bytes` | BigInteger | Y | — | app-enforced max 25MB, max 10 files/upload |
| `storage_key` | Text | N | — | |
| `bucket_name` | String(255) | Y | — | |
| `scan_status` | String(20) | N | `"pending"` | **stub — no service/route/job ever reads or updates it; every attachment sits at "pending" forever** (confirmed by grep, not just documentation claim) |
| `uploaded_at` | DateTime(tz) | N | now() | |
| `created_at` / `updated_at` | DateTime(tz) | Y | now() | |

#### `clients`
| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `client_id` | UUID | N | `uuid4()` | **PK** |
| `name` | String(255) | N | — | |
| `inbox_email` | String(255) | N | — | **Unique**, always lowercased |
| `account_manager_id` | UUID | N | — | **FK** → `users`, indexed |
| `is_active` | Boolean | N | `True` | |
| `created_at` / `updated_at` | DateTime(tz) | N | now() | |

#### `ticket_relations`
Symmetric "Related Tickets" link (one relationship = two mirrored rows). **Composite PK** `(ticket_id, related_ticket_id)`, both **FK** → `tickets.ticket_id`. Plus `created_at`. No semantic weight beyond "an agent manually said these are related" — this is the closest existing analog to an automated recommendation feature, but it's entirely manual today.

#### `ticket_audit_logs`
*Ticketing-domain immutable compliance trail — named `ticket_audit_logs`, not `audit_logs`, since the RBAC table already owns that name.*

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `audit_id` | UUID | N | `uuid4()` | **PK** |
| `entity_type` | enum `audit_entity_type_enum` | N | — | `TICKET/INTERACTION/ATTACHMENT/CLIENT/USER` |
| `entity_id` | UUID | N | — | polymorphic, no FK |
| `event_type` | enum `audit_event_type_enum` | N | — | 34 values — see §6 |
| `actor_id` | UUID | Y | — | **FK** → `users` |
| `actor_name` | String(255) | N | — | stored at write time, durable (survives rename/deletion of the user) |
| `actor_role` | enum `audit_actor_role_enum` | N | — | `AGENT/CLIENT/SYSTEM` |
| `old_values` / `new_values` | JSONB | Y | — | |
| `ticket_id` | UUID | Y | — | **FK** → `tickets`, derived at write time for fast `list_by_ticket` |
| `created_at` | DateTime(tz) | N | now() | |

Indexes: `(entity_type, entity_id, created_at DESC)`, `(actor_id, created_at DESC)`, `(event_type, created_at DESC)`, `(ticket_id, created_at DESC)`.

#### `resolution_slas`
*1:1 clock per Ticket.*

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `resolution_sla_id` | UUID | N | `uuid4()` | **PK** |
| `ticket_id` | UUID | N | — | **FK** → `tickets`, **unique**, indexed |
| `client_id` | UUID | Y | — | **FK** → `clients`, denormalized |
| `priority` | enum `ticket_priority_enum` | N | — | snapshot at creation; stays at *original* priority through escalation (never becomes CRITICAL on this row) |
| `status` | enum `sla_clock_status_enum` | N | `RUNNING` | indexed |
| `started_at` / `due_at` | DateTime(tz) | N | — | `due_at` indexed |
| `active_target_minutes` | Integer | N | — | current real target (what the sweep's fraction math actually uses) |
| `paused_at` | DateTime(tz) | Y | — | non-null iff PAUSED |
| `total_paused_seconds` | Integer | N | `0` | |
| `completed_at` | DateTime(tz) | Y | — | |
| `escalation_cycle` | Integer | N | `0` | bumped on each handling-stage restart; treat as `NOT NULL DEFAULT 0` |
| `created_at` / `updated_at` | DateTime(tz) | N | now() | |

Index `(status, due_at)` — the sweep's primary query.

#### `first_response_slas`
*1:1 clock per thread-root Interaction (not the ticket). No `updated_at` column.*

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `first_response_sla_id` | UUID | N | `uuid4()` | **PK** |
| `interaction_id` | UUID | N | — | **FK** → `interactions`, **unique**, indexed |
| `client_id` | UUID | Y | — | **FK** → `clients` |
| `priority` | enum `ticket_priority_enum` | N | — | defaults MEDIUM for pre-ticket items (no real priority exists yet) |
| `status` | enum `sla_clock_status_enum` | N | `PENDING` | only PENDING/COMPLETED used in practice |
| `started_at` / `due_at` | DateTime(tz) | N | — | `due_at` indexed |
| `completed_at` | DateTime(tz) | Y | — | |
| `completion_reason` | String(30) | Y | — | free string: `ARCHIVED / REPLIED / ATTACHED_TO_TICKET / TICKET_CREATED` |
| `resulting_ticket_id` | UUID | Y | — | **FK** → `tickets`; set only for `TICKET_CREATED`/`ATTACHED_TO_TICKET` |
| `created_at` | DateTime(tz) | N | now() | |

#### `ticket_escalations`
*At most one non-CLOSED row per ticket, enforced by a partial unique index.*

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `escalation_id` | UUID | N | `uuid4()` | **PK** |
| `ticket_id` | UUID | N | — | **FK** → `tickets`, indexed |
| `resolution_sla_id` | UUID | Y | — | **FK** → `resolution_slas`, read-only link |
| `level` | enum `ticket_escalation_level_enum` | N | — | `TEAM_LEAD/MANAGER/SITE_LEAD` |
| `status` | enum `ticket_escalation_status_enum` | N | `ACTIVE` | `ACTIVE/ACKNOWLEDGED/CLOSED` |
| `owner_ids` | JSONB (list of user_id strings) | N | `[]` | wholesale-replaced on advance |
| `original_priority` | enum `ticket_priority_enum` | N | — | snapshot pre-CRITICAL-bump |
| `has_advanced_past_starting_level` | Boolean | N | `False` | |
| `handling_stage` | Integer | N | `0` | count of completed accept→assign→breach cycles |
| `handling_stage_started_at` / `handling_stage_due_at` | DateTime(tz) | Y | — | non-null iff a stage is currently running |
| `triggered_by` | String(20) | N | — | `MANUAL` or `AUTO_SLA_BREACH` (free string) |
| `triggered_by_user_id` | UUID | Y | — | **FK** → `users` |
| `created_at` / `level_started_at` | DateTime(tz) | N | now() | |
| `ack_due_at` | DateTime(tz) | N | — | indexed |
| `acknowledged_at` / `acknowledged_by` | DateTime(tz)/UUID | Y | — | **FK** (acknowledged_by) → `users` |
| `closed_at` / `closed_reason` | DateTime(tz)/String(30) | Y | — | reason: `TICKET_RESOLVED`/`MANUALLY_CLOSED` |
| `updated_at` | DateTime(tz) | N | now()/onupdate | |

Indexes: `(status, ack_due_at)`; partial `handling_stage_due_at WHERE NOT NULL`; **unique partial** `ix_ticket_escalations_one_active_per_ticket` on `ticket_id WHERE status != 'CLOSED'`.

#### `escalation_handling_slas`
*Second internal clock — as of the 2026-07-20 handling-stage redesign, this table is a dual-write, non-load-bearing mirror; the real stage counter/reshift lives on `ticket_escalations`/`resolution_slas` (see §10.6). Multiple rows per escalation allowed over time; at most one "open" at once.*

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `escalation_handling_sla_id` | UUID | N | `uuid4()` | **PK** |
| `escalation_id` | UUID | N | — | **FK** → `ticket_escalations`, indexed (non-unique) |
| `ticket_id` | UUID | N | — | **FK** → `tickets`, indexed |
| `status` | enum `sla_clock_status_enum` | N | `RUNNING` | only RUNNING/COMPLETED used |
| `target_seconds` | Integer | N | — | |
| `started_at` / `due_at` | DateTime(tz) | N | — | `due_at` indexed |
| `breached_at` / `completed_at` | DateTime(tz) | Y | — | `breached_at` stamped once |
| `created_at` | DateTime(tz) | N | now() | |

Unique partial index: `escalation_id WHERE breached_at IS NULL AND completed_at IS NULL`.

#### `sla_policies`
*One row per `TicketPriority`. No FKs — standalone lookup, seeded not app-created (though editable live via an admin UI — see §19 for a known live-value caveat).*

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `policy_id` | UUID | N | `uuid4()` | **PK** |
| `priority` | enum `ticket_priority_enum` | N | — | **unique** |
| `first_response_target_minutes` | Integer | N | — | |
| `resolution_target_minutes` | Integer | N | — | |
| `escalation_ack_target_minutes` | Integer | N | — | |
| `handling_sla_percentage` | Float | N | `25.0` | **deprecated, unread by current code** — kept only for schema compatibility |
| `handling_stage_percentages` | JSONB (list of float) | N | — (must be supplied) | ordered per-stage % of resolution target, e.g. `[25.0, 12.5, 6.25]` |
| `warning_1_percentage` / `warning_2_percentage` | Float | N | `50.0` / `80.0` | |
| `is_active` | Boolean | N | `True` | |
| `created_at` / `updated_at` | DateTime(tz) | N | now() | |

Exact seeded values for all 4 rows are in §17.

#### `sla_breach_notifications`
*Idempotency ledger for the breach sweep. Polymorphic `clock_id`, no FK (can't FK into one of two tables).*

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `sla_breach_notification_id` | UUID | N | `uuid4()` | **PK** |
| `clock_type` | String(20) | N | — | `FIRST_RESPONSE` or `RESOLUTION` |
| `clock_id` | UUID | N | — | polymorphic, **no FK** |
| `threshold` | String(20) | N | — | `AT_RISK/BREACHED/ESCALATED` (plus `HALF_ELAPSED`, used for the first threshold) |
| `cycle` | Integer | N | `0` | **known model-file bug**: `cycle` is defined twice in the same class body (once without `server_default`, once with `server_default="0"`); the second silently wins — treat as `NOT NULL DEFAULT 0` |
| `notified_at` | DateTime(tz) | N | now() | |

Unique index: `(clock_type, clock_id, threshold, cycle)`.

#### `notifications`
| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `notification_id` | UUID | N | `uuid4()` | **PK** |
| `user_id` | UUID | N | — | **FK** → `users` (no ondelete) |
| `notification_type` | String(50) | N | — | **plain string, not an enum** — see §14 for the full current value set |
| `title` | String(255) | N | — | |
| `message` | Text | N | — | |
| `link` | String(500) | Y | — | frontend route path, e.g. `/tickets/{id}` — not a full URL |
| `related_entity_type` | String(50) | Y | — | free-form, not an FK |
| `related_entity_id` | UUID | Y | — | no FK |
| `is_read` | Boolean | N | `False` | indexed |
| `created_at` | DateTime(tz) | N | now() | indexed |

#### Tables that exist but were flagged (not deep-dived) in earlier passes — read their model files directly before generating data against them
- `ticket_edit_access_requests` — backs the `ticket:editother_ticket` request/approve/reject workflow; own `edit_access_status_enum` (`PENDING/APPROVED/REJECTED`, no `REVOKED`).
- `mail_folders` — backs `Interaction.folder_id`; used by the Mail UI's folder assignment feature.

### 5.C — Entity-Relationship summary

```
Client (company) ──< Interaction (email/reply/note) >── Ticket ──< ResolutionSLA (1:1)
                             │                              │
                      (thread root) ──< FirstResponseSLA    ├──< TicketEscalation ──< EscalationHandlingSLA
                             │                              │
                      Attachment                     TicketRelation (self-link, symmetric)

Role ──< User ──< Client (account_manager_id)
User ──< User (manager_id / teamlead_id, self-referencing, no rank column)
Category ──< User (specialization)
Role ──< RolePermission >── Permission
User ──< UserPermissionOverride >── Permission (optionally ticket-scoped)
User ──< ReportingManagerTeam >── Category (many-to-many)
User ──< Notification (recipient)
```

**In prose**:
- A **User** holds one **Role** and, optionally, one specialization **Category**. Users can report to another User as `manager_id` (Account Manager line) and/or `teamlead_id` (Team Lead line) — both self-referencing FKs, no rank column; hierarchy is code-only.
- A **Client** is a company, owned by exactly one Account Manager, with one dedicated `inbox_email`.
- A **Ticket** belongs to a Client (`client_company_id` — the real column; `client_id` is legacy/dead), is optionally assigned to an agent User (`agent_id`), and records who created it (`created_by`). Its category is a **plain string** (`ticket_type`), not FK'd to `categories`.
- An **Interaction** is the atomic timeline unit — inbound email, outbound reply, internal note, or attachment event. Optionally belongs to a Ticket (NULL until promoted), optionally to a Client, threads to other Interactions via `parent_interaction_id`/`conversation_id`/`message_id` matching. **A Ticket cannot exist without a founding Interaction — there is no "blank ticket" creation path anywhere in this codebase.**
- An **Attachment** belongs only to an Interaction, never directly to a Ticket.
- **ResolutionSLA** is 1:1 with a Ticket (whole ticket lifetime); **FirstResponseSLA** is 1:1 with the *root* Interaction of a thread (not the ticket) — this is why a ticket has no "first response" column of its own.
- **TicketEscalation** sits on top of, but never mutates, ResolutionSLA's own `started_at`/`due_at`/`status` — a separate ownership hand-off chain. **EscalationHandlingSLA** sits on top of *that*.
- **SLAPolicy** is a global, priority-keyed config table (4 rows), not tied to any ticket/category/client.
- The **RBAC permission system** is entirely orthogonal to the ticketing business data — it governs who can see/do what, never the business content itself.

---

## 6. Enums — Full Member Lists

| Enum | Postgres type | Members (in order) |
|---|---|---|
| `TicketStatus` | `ticket_status_enum` | `OPEN, IN_PROGRESS, PENDING, WAITING_FOR_CLIENT, RESOLVED, CLOSED` |
| `TicketPriority` | `ticket_priority_enum` | `LOW, MEDIUM, HIGH, CRITICAL` (CRITICAL added later, intended to be system-set only) |
| `CategoryName` | `category_name_enum` | `Eligibility, Patient Calling, AR, Payment Posting, PA, Charge Entry, Claims` |
| `InteractionStatus` | `interaction_status_enum` | `PENDING, ASSIGNED, IGNORED` |
| `InteractionDirection` | `interaction_direction_enum` | `INBOUND, OUTBOUND, INTERNAL` |
| `EscalationLevel` | `ticket_escalation_level_enum` | `TEAM_LEAD, MANAGER, SITE_LEAD` |
| `EscalationStatus` | `ticket_escalation_status_enum` | `ACTIVE, ACKNOWLEDGED, CLOSED` |
| `SLAClockStatus` | `sla_clock_status_enum` | `PENDING, RUNNING, PAUSED, COMPLETED` |
| `AuditEntityType` | `audit_entity_type_enum` | `TICKET, INTERACTION, ATTACHMENT, CLIENT, USER` |
| `ActorRole` | `audit_actor_role_enum` | `AGENT, CLIENT, SYSTEM` |
| `EditAccessStatus` | `edit_access_status_enum` | `PENDING, APPROVED, REJECTED` (no `REVOKED`) |
| `PermissionRequestStatus` | *(plain string, no Postgres type)* | `PENDING, APPROVED, REJECTED, REVOKED` |

**`AuditEventType`** (`audit_event_type_enum`, 34 members, full list): `TICKET_CREATED, TICKET_UPDATED, TICKET_RESOLVED, STATUS_CHANGED, PRIORITY_CHANGED, AGENT_TRANSFERRED, TICKET_CLOSED, TICKET_REOPENED, INTERACTION_HIDDEN, ATTACHMENT_UPLOADED, NOTE_ADDED, REPLY_ADDED, EMAIL_RECEIVED, CLIENT_CREATED, INTERACTION_CLAIMED, INTERACTION_ARCHIVED, INTERACTION_SNOOZED, INTERACTION_UNSNOOZED, INTERACTION_TAGGED, INTERACTION_FOLDER_CHANGED, TICKET_RELATED, TICKET_UNRELATED, TICKET_CLAIMED, EDIT_ACCESS_REQUESTED, EDIT_ACCESS_APPROVED, EDIT_ACCESS_REJECTED, SLA_PAUSED, SLA_RESUMED, SLA_BREACH_DETECTED, SLA_ESCALATED, ESCALATION_CREATED, ESCALATION_ACKNOWLEDGED, ESCALATION_ADVANCED, ESCALATION_CLOSED`.

**`Interaction.interaction_type`** is a plain string, not a Postgres enum. Currently-written values: `EMAIL, REPLY, INTERNAL_NOTE, ATTACHMENT, SLA_PAUSED, SLA_RESUMED`.

### Retired / deprecated — must never appear as active/current in synthetic data
- Enum labels: `SLA_MANUALLY_PAUSED`, `SLA_MANUALLY_RESUMED` (renamed to `SLA_PAUSED`/`SLA_RESUMED`).
- `interaction_type` values: `STATUS_CHANGE, PRIORITY_CHANGE, AGENT_TRANSFER, CLAIM, EDIT_ACCESS_REQUESTED, EDIT_ACCESS_APPROVED, EDIT_ACCESS_REJECTED` — historical rows were hard-deleted; synthesized from audit logs at read time now, never written fresh.
- Permission names: `ticket:bulk_reassign`, `ticket:configure_routing`, `ticket:edit_ticket` (split into `editown_ticket`/`editother_ticket`), `ticket:close` (renamed `ticket:close_ticket`), `ticket:manage_attachments` (split into `upload_attachment`/`archive_attachment`) — all explicitly deleted, not just unassigned.
- `interactions.snoozed_until` — column no longer exists.

---

## 7. Business Rules & Validation

- **No enforced Category ↔ ticket mapping at the DB or schema layer.** `Ticket.ticket_type` is a bare `String(50)` with no FK/CHECK constraint — the only gate is the frontend dropdown. Sample from the real 7 values for realistic synthetic data anyway.
- **No `IssueType` concept exists anywhere** — category is the only classification axis on a ticket.
- **Pydantic-level field constraints** (the only schema-layer validation found): `TicketCreate.title` 1–255 chars; `TicketCreate.ticket_type` 1–100 chars; `InteractionCreate.interaction_type` 1–50 chars; `InteractionCreate.subject` ≤500 chars; `InternalNoteCreate.subject` 1–500 chars, `.note` 1–5000 chars; `ReplyCreate.message` 1–5000 chars; `DraftSaveRequest.message` min length 1. **No custom `@field_validator`/`@model_validator` exists on any Ticket/Interaction/Attachment/Client schema.**
- **Real business rules live at the service layer, not the schema layer**: permission checks (`ensure_has_permission`), assignment-hierarchy validation (`AssignmentService.resolve_target`), category-scoped visibility, escalation ownership (`owner_ids` membership).
- **Real invariants enforced at the DB level via partial unique indexes** (the actual hard constraints synthetic data must respect to be insertable as-is):
  - At most one non-CLOSED `TicketEscalation` per ticket.
  - At most one "open" `EscalationHandlingSLA` per escalation.
  - At most one active draft `Interaction` per `(parent_interaction_id, performed_by)`.
  - `interactions.message_id`, `clients.inbox_email`, `roles.name`, `permissions.permission_name`, `categories.category_name` are all globally unique.
  - `resolution_slas.ticket_id` and `first_response_slas.interaction_id` are each unique (true 1:1).
  - `reporting_manager_teams` unique on `(account_manager_id, category_id)` pair.
  - `user_permission_overrides` / `permission_requests` partial-unique on `(subject, permission, COALESCE(scope_ticket_id, sentinel))` under an active/pending condition.
- **Structural constraint that dictates generation order**: a `Ticket` cannot exist without a prior `Interaction`. Any synthetic dataset must generate the founding EMAIL interaction before its ticket, never the reverse.
- **Attachment validation**: max 10 files per upload call, max 25MB per file; allowed extensions `pdf, doc, docx, xls, xlsx, csv, png, jpg/jpeg, gif, txt, zip`, each checked against an explicit allow-listed MIME set; a mismatched declared content-type is rejected.
- **Ticket fields that are always system-derived, never human-typed**: `ticket_id`, `version`, `created_at`, `updated_at`, `current_status` (always starts `OPEN`), `created_by`, `client_company_id` (copied from the originating Interaction's `client_id`), `client_id` (always NULL), `closed_at`/`closed_by`, `current_priority` becoming `CRITICAL`, `custom_fields`.
- **Ticket fields that are direct human input** (Create Ticket dialog): `title` (free text), `ticket_type` (dropdown), `current_priority` (optional, defaults MEDIUM, CRITICAL excluded from the picker), `agent_id` (optional, server-revalidated against the caller's own assignment hierarchy — never trusted as submitted).

---

## 8. RBAC Permission System

### 8.1 Full permission list (51 permissions, from `unified-backend/scripts/rbac_seed/seed.py`)

**`user:*`**: `user:create`, `user:view`, `user:update`, `user:delete`, `user:disable` (activate/deactivate), `user:reset_password`.

**`role:*`**: `role:create`, `role:view`, `role:update`, `role:delete`.

**`permission:*`**: `permission:view`, `permission:update`, `permission:override_grant`, `permission:override_revoke`.

**`audit:*`**: `audit:view`, `audit:export`.

**`communication:*`**: `communication:create`, `communication:view_all`, `communication:view_assigned`, `communication:reply_external`, `communication:reply_internal`, `communication:forward`, `communication:convert_to_ticket`, `communication:attach_to_ticket`, `communication:merge`, `communication:archive`, `communication:view_timeline`, `communication:assign`, `communication:override_grant`.

**`ticket:*`**: `ticket:create`, `ticket:view_own`, `ticket:view_unassigned`, `ticket:view_others`, `ticket:assign`, `ticket:transfer`, `ticket:change_priority`, `ticket:change_category`, `ticket:change_sla`, `ticket:reply`, `ticket:editown_ticket`, `ticket:editother_ticket`, `ticket:update_status`, `ticket:close_ticket`, `ticket:reopen`, `ticket:escalate`, `ticket:upload_attachment`, `ticket:archive_attachment`, `ticket:hide_interaction`, `ticket:view_audit_trail`, `ticket:view_global_audit_log`, `ticket:view_dashboard_kpis`, `ticket:view_escalated`, `ticket:acknowledge_escalation`, `ticket:manage_agents`, `ticket:manage_roles_permissions`, `ticket:system_config`.

**`sla:*`**: `sla:manage_policies`.

**`org:*`**: `org:manage_reporting_managers`.

### 8.2 Per-role default grant matrix

Grants are **additive-only** in the seed script — anything removed from a role's default list must appear in an explicit `REVOKED_GRANTS` entry (with a comment explaining why) or it's assumed still granted.

| Role | Grant shape |
|---|---|
| **Super Admin** | Literally `"all"` — every one of the 51 permissions, unconditionally. |
| **Site Lead** | Every permission **except** `ticket:system_config` and `audit:export` — computed programmatically from the full list (49 of 51), not a hand-maintained list, so it can't drift. |
| **Account Manager** | Full: all `communication:*`, most `ticket:*` (create/view_own/view_unassigned/view_others/assign/transfer/change_priority/change_category/change_sla/update_status/reply/editown_ticket/editother_ticket/close_ticket/reopen/escalate/upload_attachment/archive_attachment/hide_interaction/view_audit_trail/view_dashboard_kpis/view_escalated/acknowledge_escalation/manage_agents/manage_roles_permissions), `user:view/create/update/disable/reset_password`, `role:view`, `permission:view/override_grant/override_revoke`. **Override-only** (explicitly excluded/revoked): `ticket:system_config`, `ticket:view_global_audit_log` (previously Full, deliberately downgraded during the RBAC compliance audit — see §19). |
| **Team Lead** | Full: `communication:view_assigned/reply_external/reply_internal/forward/view_timeline`, `ticket:view_own/view_unassigned/view_others/assign/transfer/update_status/reply/editown_ticket/editother_ticket/escalate/upload_attachment/view_audit_trail/view_dashboard_kpis/view_escalated/acknowledge_escalation`, `user:view/update`, `role:view`. **Override-only**: `ticket:close_ticket`, `ticket:reopen`, `ticket:hide_interaction`, `ticket:view_global_audit_log`, `communication:create` — all explicitly revoked with a rationale comment in the seed script (this role used to have an unconditional bypass on Close/Reopen that the RBAC compliance audit narrowed). |
| **Staff** | Full: `communication:reply_external/reply_internal/view_assigned/view_timeline`, `ticket:view_own/view_unassigned/view_others/update_status/reply/upload_attachment/editown_ticket/view_audit_trail/view_dashboard_kpis`, `user:view`. **Override-only**: `ticket:create`, `ticket:transfer`, `ticket:reopen`, `user:update`, `ticket:hide_interaction`, `ticket:close_ticket`, `ticket:system_config`, `communication:create` — each explicitly clawed back with a rationale comment. |
| **Viewer** | `user:view`, `role:view`, `permission:view` only — the one role outside the main hierarchy. |

### 8.3 Role-group constants (`unified-backend/app/ticketing/services/access_control.py`)

| Constant | Exact role names |
|---|---|
| `AGENT_ROLE_NAMES` | Staff, Team Lead, Account Manager, Site Lead, Super Admin |
| `SUPERVISOR_ROLE_NAMES` | Team Lead, Account Manager, Site Lead, Super Admin |
| `TEAM_LEAD_TRANSFER_ROLE_NAMES` | Account Manager, Site Lead, Super Admin |
| `CATEGORY_SCOPED_ROLE_NAMES` | Team Lead, Staff |
| `GLOBAL_INBOX_ROLE_NAMES` | Site Lead, Super Admin |
| `ESCALATION_TAB_ROLE_NAMES` | Account Manager, Team Lead, Site Lead, Super Admin |
| `DUMMY_MAIL_ROLE_NAMES` | Site Lead |
| `CLOSE_REOPEN_BYPASS_ROLE_NAMES` | Site Lead, Super Admin |

### 8.4 Permission-check function catalogue (`app/ticketing/services/access_control.py`)

- `has_permission(current_user, permission_name) -> bool` — checks the flat `current_user.permissions` list threaded from the JWT `permissions` claim.
- `has_permission_for_ticket(current_user, permission_name, ticket_id) -> bool` — true if `has_permission` OR the permission was granted scoped to that specific `ticket_id` via the JWT's `scoped_permissions` claim.
- `ensure_has_permission(...) -> None` — raises 403 if false.
- `ensure_ticket_not_closed(ticket)` — 400s if `CLOSED` (blocks everything except status-change-to-reopen/reopen itself).
- `ensure_agent_can_view_ticket(ticket, current_user)` — 403s if role isn't in `AGENT_ROLE_NAMES`, or (for `CATEGORY_SCOPED_ROLE_NAMES`) if the ticket's category doesn't match the user's own category.
- `ensure_ticket_not_frozen_by_escalation(ticket, escalation_repository=None, escalation_handling_sla_repository=None)` (async) — 403s **everyone including supervisors** if the ticket has an active, not-yet-accepted escalation. No-op entirely if `escalation_repository` isn't passed (a caller-choice skip, not a bypass).
- `ensure_agent_can_act_on_ticket(...)` (async) — the main "can you work this ticket" gate: view check → freeze check → supervisor bypass → own-ticket + `editown_ticket` → `editother_ticket`(scoped or unscoped) → edit-access-grant fallback → 403.
- `ensure_account_manager_owns_ticket_client(ticket, current_user, client_repository)` (async) — 403s an Account Manager acting on a ticket whose client they don't own; no-op for other roles.
- `ensure_agent_can_view_pending_interaction(interaction, current_user, client_repository)` (async) — gates a pre-ticket Mail item to its owning Account Manager or a global-inbox role.
- `ensure_can_compose_for_client(client, current_user)` — gates who may start a brand-new outbound thread to a client.
- `ensure_can_review_edit_access(ticket, current_user)` — gates approving/rejecting a per-ticket edit-access request.
- `ensure_can_close_ticket(current_user)` / `ensure_can_reopen_ticket(current_user)` — bypassed unconditionally only by `CLOSE_REOPEN_BYPASS_ROLE_NAMES`; else require `ticket:close_ticket`/`ticket:reopen`.
- `ensure_can_override_sla(current_user)` — bypassed by `GLOBAL_INBOX_ROLE_NAMES`, else requires `ticket:change_sla`.
- `ensure_can_manage_sla_policies(current_user)` — requires `sla:manage_policies`, no role bypass.
- `ensure_can_reassign_ticket(current_user)` — bypassed by `SUPERVISOR_ROLE_NAMES`, else requires `ticket:transfer`.

`unified-backend/app/rbac/services/access_control.py` is a much smaller, deliberately self-contained duplicate — just `has_permission`/`ensure_has_permission` against the same flat JWT claim, used to gate the RBAC domain's own routes (Users/Roles/Permissions/Audit Logs).

### 8.5 Token claims mechanism (cross-module identity)

`app.rbac`'s `create_access_token` is the **sole issuer** of JWT access/refresh tokens (HS256). `app.ticketing` is **verify-only** — no login/signup/refresh endpoint of its own. The access token carries: `permissions` (full effective flat list — role defaults ∪ active unscoped personal overrides, computed at login/refresh time), `scoped_permissions` (dict: permission name → list of ticket ids, for ticket-scoped overrides), and `name`/`role_id`/`category_id`/`category`/`permission_version` (all optional/backward-compatible). A stale or absent claim degrades to an empty list/dict rather than crashing. Granting/revoking a permission doesn't affect an already-issued token, only the next login/refresh. An in-memory, per-process, TTL-based cache (default 30s) avoids re-resolving the user from Postgres on every request, keyed on `(user_id, permission_version)`; a mismatch between the token's claimed `permission_version` and the DB's live value forces a 401 ("session outdated") rather than trusting stale data.

---

## 9. Ticket Lifecycle

### 9.1 Status

`OPEN → IN_PROGRESS → PENDING → WAITING_FOR_CLIENT → RESOLVED → CLOSED` — **not** a strict linear path; a ticket can move between several of these more than once before closing.

- A new ticket always starts at **OPEN** (system-set, never chosen).
- **`WAITING_FOR_CLIENT`** pauses the Resolution SLA clock (§10.1); any other status change resumes it.
- **`RESOLVED`** does **not** stop the Resolution SLA clock — only **`CLOSED`** does, and only via the dedicated Close action (never reachable through the generic status-change endpoint, which explicitly rejects `new_status == CLOSED`).
- **`CLOSED`** is terminal for every action except **Reopen** — blocks replies, notes, priority changes, transfers, attachment uploads until reopened. Reopen resets to `OPEN`, clears `closed_at`/`closed_by`, and deliberately never touches the (already-`COMPLETED`, never-resurrected) Resolution SLA clock or re-creates any escalation.
- Both Close and Reopen are bypassed unconditionally only for Site Lead/Super Admin (`CLOSE_REOPEN_BYPASS_ROLE_NAMES`); Account Manager/Team Lead/Staff need the real `ticket:close_ticket`/`ticket:reopen` permission (Full for Account Manager, Override-only for Team Lead/Staff by default).

### 9.2 Priority

`LOW / MEDIUM / HIGH` are the only manually-selectable tiers (an agent picks at ticket creation or via Change Priority). **`CRITICAL` is intended to be system-set only** — set exactly once, automatically, the moment a ticket's internal escalation workflow creates its first escalation (`EscalationService._create_escalation` → `_set_ticket_priority_to_critical`, idempotent, no-op if already CRITICAL), and it never reverts (not on acknowledge, not on closing the escalation, not on resolving/closing the ticket itself). See §19 for a confirmed gap: the `change_priority` endpoint itself has no enforcement blocking a permission-holder from manually forcing or reversing CRITICAL.

**A synthetic historical corpus should essentially never contain a manually-set `CRITICAL`-priority ticket** unless deliberately simulating an already-escalated ticket, or deliberately simulating the confirmed loophole above.

### 9.3 Internal escalation (a layer on top of, never mutating, status/priority's own semantics)

If a ticket's Resolution SLA breaches badly enough (reaches the `ESCALATED` fraction-elapsed threshold), or a supervisor manually escalates it, ownership hands off up a `TEAM_LEAD → MANAGER → SITE_LEAD` chain. Full mechanics in §12.

---

## 10. SLA Behavior

Two independent per-ticket/per-interaction clocks exist, each with its own lifecycle:

### 10.1 Resolution SLA clock (`resolution_slas`, one per Ticket)

- **Start** (`SLAService.start_resolution_clock`, called from ticket creation): looks up the `SLAPolicy` row for the ticket's priority; `started_at = now`; `due_at = started_at + resolution_target_minutes`; `active_target_minutes = policy.resolution_target_minutes`; `status = RUNNING`. No-ops (logs a warning) if no policy row exists for that priority.
- **Pause** (on entering `WAITING_FOR_CLIENT`): no-op unless currently `RUNNING`; sets `status=PAUSED`, `paused_at=now`, opens a `ResolutionSLAPauseInterval` row.
- **Resume** (on leaving `WAITING_FOR_CLIENT`, or a reply lands on a ticket whose clock is paused): no-op unless `PAUSED`; `due_at` shifts forward by exactly the elapsed pause duration (`due_at += (resumed_at - paused_at)`); `total_paused_seconds` accumulates; closes the pause interval; `status=RUNNING`.
- **Complete** (entering `RESOLVED`, or directly `CLOSED`): idempotent — a second completion call preserves the original `completed_at`. Entering `RESOLVED` completes the clock without closing the escalation (`close_escalation=False`); the dedicated Close action completes it (or confirms it's already complete) **and** closes any active escalation (`close_escalation=True`, default).
- **Reshift on a manual priority change** (`change_priority` endpoint): recomputes `due_at` proportionally — `remaining = new_target_minutes*60 - (elapsed_running_time)`; `due_at = now + remaining`. This preserves the fraction of "real work time" already consumed against the new target.
- **Restart on escalation acceptance** (`_complete_acceptance`, every handling-stage accept/re-accept — never on a manual priority change): sets `priority` and `active_target_minutes` to the **stage target** (a percentage of the *original* pre-escalation resolution target — see §12), and gives a **full fresh window** (`due_at = now + stage_target_minutes`, NOT proportional — deliberately different from the manual-reshift formula, because preserving elapsed time against a much shorter stage target routinely produced an already-past `due_at`). Increments `escalation_cycle`, which is what allows the breach-notification ledger to re-fire the same threshold names again after a restart.
- **Elapsed-fraction formula** used everywhere (pause/resume/reshift-consistent by construction, since it only reads `due_at` and the target, never `started_at` or pause history directly): `fraction = 1.0 - (due_at - now).total_seconds() / (target_minutes * 60)`.

### 10.2 First Response SLA clock (`first_response_slas`, one per thread-root Interaction, not the ticket)

- **Start**: only for a genuinely new thread root (never a reply threading onto an existing item). Priority defaults to `MEDIUM` always (a pending inbox item has no real priority yet — an accepted v1 limitation, not a bug). `due_at = received_at (or now) + first_response_target_minutes`. Starts at `status=PENDING`.
- **Completion reasons** (exact strings, one per triage action): `"TICKET_CREATED"` (interaction became a new ticket, `resulting_ticket_id` set), `"ATTACHED_TO_TICKET"` (attached to an existing ticket, `resulting_ticket_id` set), `"REPLIED"` (agent replied without ticketing it, no resulting ticket), `"ARCHIVED"` (reviewer archived as informational, no resulting ticket).
- This clock **never restarts and never pauses** — it measures triage speed only, once.
- A self-contained threshold check runs at completion time too (not just in the periodic sweep) — because a clock that breaches and then completes before the next sweep tick would otherwise never get its breach notification recorded.

### 10.3 SLASweepService.run_sweep — the periodic engine tying it together

Runs on a schedule (interval configurable — see §19 for a documented drift between what CLAUDE.md's project notes describe and what's actually hardcoded), and is also reachable via a shared-secret-protected manual endpoint. Each tick, in order:

1. Load all 4 `SLAPolicy` rows.
2. **First Response pass**: every still-`PENDING` clock; compute elapsed fraction against its target; check thresholds using **that priority's own `warning_1_percentage`/`warning_2_percentage`** (defaulting 50%/80% if unset) plus fixed 100% (`BREACHED`) and 150% (`ESCALATED`) cutoffs; record newly-crossed thresholds.
3. **Resolution pass**: every still-`RUNNING` clock; same threshold logic, using the clock's own `active_target_minutes` (not re-derived from current priority — this is what makes a post-restart stage target authoritative); if `ESCALATED` is newly reached and the ticket has no active escalation yet, the escalation is queued for creation **after** the notify loop (not inline — creating it earlier could feed the *new* owner into this same tick's recipient resolution for thresholds that logically belonged to the pre-escalation owner).
4. One **batched idempotency check** (`INSERT ... ON CONFLICT DO NOTHING ... RETURNING` on the unique `(clock_type, clock_id, threshold, cycle)` index) determines which crossings are genuinely new.
5. Notify loop (each in its own transaction savepoint, so one failure can't affect another) — see §14 for exact recipient rules per threshold.
6. Deferred auto-escalation creation for tickets that crossed `ESCALATED` with no existing escalation.
7. **Ack-window auto-advance** — `EscalationService.evaluate_overdue`: every `ACTIVE` escalation whose `ack_due_at` has passed gets advanced one level.
8. **Escalation-handling-SLA breach detection** — every escalation whose `handling_stage_due_at` has passed gets `advance_for_handling_sla_breach` called.
9. A legacy dual-write (`EscalationHandlingSlaService.evaluate_breaches`) updates the older mirror table's own `breached_at` for display purposes only — it no longer drives advancement itself.

**Threshold names and cutoffs**: `HALF_ELAPSED` (default 50%, per-priority overridable via `warning_1_percentage`), `AT_RISK` (default 80%, via `warning_2_percentage`), `BREACHED` (fixed 100%, never configurable), `ESCALATED` (fixed 150%, never configurable). A clock discovered already past 150% returns all four threshold names at once (all get recorded/notified together, since none were previously recorded).

### 10.4 SLA Policy configuration

Global, priority-keyed, 4 rows (`LOW/MEDIUM/HIGH/CRITICAL`), editable live via a Super-Admin-only admin UI (gated by `sla:manage_policies`) — **not just a one-time seed**. Exact currently-migrated values are in §17; a known live-database deviation from those values is flagged in §19.

**Mechanic worth knowing for synthetic timing data**: a Resolution SLA's `due_at` is computed and stored once when the clock starts — a policy change only affects clocks started *after* the change; already-running tickets keep their prior due date. The First Response badge, by contrast, has no stored `due_at` at all in the frontend display and is recomputed client-side on every render from `received_at` + the *current* policy value — so a policy edit instantly re-tiers every still-pending inbox item's displayed badge, even though the backend clock's own stored row is unaffected until the next sweep read.

---

## 11. Communication Workflow

### 11.1 Inbound email intake (step-by-step)

1. **Transport**: Microsoft Graph webhook/poller delivers a `message` payload, mapped into an internal `EmailRequest` (subject, body/html_body, from/to/cc, `message_id` from Graph's `internetMessageId` header, `received_at`, `conversation_id`, `in_reply_to`/`references` parsed from `internetMessageHeaders`).
2. **Duplicate check**: rejected (`ValueError`) if `message_id` was already processed.
3. **Client resolution**: match sender or recipient address against `clients.inbox_email`. Every real client now shares one configured Graph mailbox address; mail at that shared mailbox with no matching client routes to Site Lead rather than being rejected outright.
4. **Thread match**: `conversation_id` → `in_reply_to_message_id` → `references`, first hit wins, recursively walked to the true root via `find_thread_root`. If matched onto an already-ticketed thread, the row inherits that `ticket_id` immediately (`status → ASSIGNED`) and the Resolution SLA clock resumes if it was paused — the pipeline stops here, no ticket-creation step needed.
5. **Interaction row created**: `interaction_type="EMAIL"`, `direction=INBOUND`, `performed_by=NULL`, `ticket_id=NULL` (unless step 4 matched), `status=PENDING`, all Graph-derived fields populated.
6. **SLA/audit side effects**: a genuinely new thread root starts its First Response SLA clock; an `EMAIL_RECEIVED` audit row is written with `actor_role=CLIENT`.
7. **Sits in the shared Mail/Inbox pool** (`ticket_id=NULL`, `status=PENDING`) until an agent acts.
8. **Agent opens "Create Ticket"**: submits `title` (typed, often copied/lightly-edited from the email subject), `ticket_type` (picked from the category dropdown), optionally `current_priority` (defaults MEDIUM) and `agent_id` (optional, server-revalidated).
9. **`TicketCreate` built server-side**: `client_company_id` copied from the interaction's own `client_id` (never re-typed); `created_by` = the promoting agent; `client_id` left NULL; `custom_fields={}`.
10. **Every other interaction already filed under that same thread is moved onto the new ticket in one batch** (`assign_thread_to_ticket`) — not just the one interaction that was clicked.
11. `TICKET_CREATED` audit row written; First Response SLA clock completes (`reason="TICKET_CREATED"`); Resolution SLA clock starts.

**Existing prior art, not the same thing as an ML/AI recommendation feature**: `OpenEmailService._recommend_ticket` already offers a *deterministic, non-ML* "attach to existing ticket" suggestion — but purely via exact thread-root/reply/message-id/header re-matching, never subject/content similarity (there's no human-readable ticket number to parse from a subject line — everything is a UUID).

### 11.2 Reply / internal note / attachment / claim

- **Direction** is set explicitly per call site, never inferred: inbound email → `INBOUND`; agent replies/compose/drafts → `OUTBOUND`; internal notes → `INTERNAL`. (A draft in progress is stored as an `OUTBOUND` row with `is_draft=True`, not sent until an explicit Send.)
- **Internal note** (`add_internal_note`): requires `subject` (1–500 chars) + `note` (1–5000 chars); gated by ticket-not-closed, the full ownership/freeze check, Account-Manager-owns-client check, and both `ticket:reply` **and** `communication:reply_internal`. Writes `NOTE_ADDED` (note text itself is never audited — only that a note was added). Notifies ticket stakeholders (minus the actor) with `INTERNAL_NOTE_ADDED`.
- **External reply** (`add_reply`): requires `message` (1–5000 chars); optional cc/bcc, a `to_email` override, and an `attachment_source_interaction_id` (must belong to the same ticket). Requires `ticket:reply` **and** `communication:reply_external`. Builds a threaded outbound envelope from the ticket's latest inbound email (From = the address the mail actually arrived at, never a hardcoded client address; auto-CCs the client's own Account Manager). Writes `REPLY_ADDED` (body itself never audited), then dispatches (see §11.3).
- **Reply on a not-yet-ticketed thread** (`add_interaction_reply`) — same shape, but also flips the root interaction back to `ASSIGNED` and completes the First Response clock with reason `"REPLIED"`.
- **Hide interaction** (`hide_interaction`): soft-delete only (`is_visible=False`, `removed_by`/`removed_at` set, row never deleted) — gated by view access + Account-Manager-ownership + `ticket:hide_interaction`. Writes `INTERACTION_HIDDEN`.
- **Claim** (`claim_ticket`): any authenticated agent can claim any open/unclaimed ticket from the shared pool — no category/permission gate beyond "not closed" and "not already claimed" (409 if either fails; a race-guarded conditional write prevents two agents winning simultaneously). Writes `TICKET_CLAIMED`. Also completes escalation acceptance if the ticket had one pending (§12).
- **Transfer** (`transfer_agent`): supervisor-gated (`ticket:transfer` or a `SUPERVISOR_ROLE_NAMES` role), with real category/client-ownership scoping — see §13 Assignment Rules for the exact eligibility rules, which differ meaningfully from the "Assigned To" picker's own narrower rules used at ticket-creation time.

### 11.3 Outbound transport — two separate, deliberately distinct paths

1. **Client-facing replies/compose**: `OutboundDispatcher` → **Microsoft Graph's `sendMail` API** (`POST /users/{mailbox}/sendMail`, `saveToSentItems: true`), authenticated via a Graph auth client. A mock provider substitutes when Graph isn't configured. Graph returns 202 with no message-id in the body — this platform's own generated envelope message-id is the only id tracked afterward. Attachments are embedded inline as base64, capped at 3MB/file (larger ones are skipped and logged, not failed). A dispatch failure sets `payload.dispatch_status = "FAILED"` + an error detail and returns HTTP 502 to the caller — committed *before* raising, so the failure marker survives the request's own rollback.
2. **Internal system notification emails** (SLA breach alerts, escalation notices, etc.): a completely separate, simpler path via plain **SMTP** if `settings.smtp_host` is configured, else falls back to logging-only (no real email sent) until SMTP credentials are supplied.

### 11.4 Draft / auto-save ("Mail v2")

A draft is a normal `REPLY`/`OUTBOUND` interaction with `is_draft=True`, `status=PENDING`, `payload={"message", "cc": [], "bcc": [], "dispatch_status": "DRAFT"}`. Exactly one active draft per `(parent_interaction_id, performed_by)` pair, enforced by a Postgres partial unique index — a check-then-insert race between two near-simultaneous autosaves is resolved by catching the losing insert's integrity error and re-fetching the winner.

- `save_draft` — upserts (overwrites, never versions) the caller's draft; called continuously/debounced by the frontend.
- `upload_draft_attachment` — attaches files to the in-progress draft (creating an empty draft first if none exists), same validation as any other upload.
- `send_draft` — reads the saved message/cc/bcc, delegates to the normal reply-send path (so envelope-building/dispatch/audit logic lives in exactly one place), reassigns already-uploaded attachments onto the real outbound interaction, then deletes the draft row.
- `discard_draft` — deletes the draft row and any attachments already uploaded against it (both storage object and DB row) — no orphaned files left behind.

### 11.5 Attachments

Belong only to an Interaction (never a Ticket directly — to find a ticket's attachments, join through its interactions). Max 10 files/upload, 25MB/file, allow-listed extensions/MIME types (§7). `scan_status` defaults `"pending"` and **is a confirmed stub** — no code anywhere reads or updates it; there is no real malware scanning despite the column's name suggesting otherwise. One `ATTACHMENT_UPLOADED` audit row is written per file (metadata only — filename, mime_type, size_bytes — never file content). Ticket-scoped upload requires `ticket:upload_attachment` + the full ownership/freeze check + Account-Manager-ownership check; deletion requires the separate `ticket:archive_attachment` permission.

---

## 12. Assignment & Escalation Rules

### 12.1 Assignment (the "Assigned To" picker at ticket-creation time — `AssignmentService`)

`get_assignable_groups(current_user, category_name=None)`:
- **Account Manager**: Team Leads + Staff, both narrowed to the ticket's category when known; falls back to a company-wide Team Lead list and their own direct-report Staff when no category is known yet.
- **Team Lead**: only their own reporting Staff.
- **Site Lead**: Account Managers (unscoped) + Team Leads + Staff (category-narrowed when known, else company-wide).
- **Super Admin**: everyone — Super Admins + Site Leads + Account Managers (unscoped) + Team Leads + Staff (category-narrowed when known).
- **Staff or any other role**: no groups at all — self only.

`resolve_target(current_user, agent_id, category_name=None)` — the write-path guard: `None` passes through unchanged (ticket born unclaimed); self-assignment always allowed; otherwise requires `ticket:assign` and re-validates `agent_id` against `get_assignable_groups`' own output (400 if not in the allowed set) — scoped by the same category the picker used, so it can never reject a choice the picker legitimately offered.

**This picker-level narrowing does not apply to `transfer_agent`'s separate, wider rule for reassigning an already-existing ticket** (below) — the two code paths intentionally use different eligibility rules for different moments in the ticket's life.

### 12.2 Transfer (reassigning an existing ticket — `InteractionService.transfer_agent`)

Gated by: not-closed, category-scoped view access, Account-Manager-owns-client, and (`SUPERVISOR_ROLE_NAMES` role OR `ticket:transfer` permission). Candidate resolution, in order:
- **Self-assignment** by a supervisor during an active escalation — always valid, no category check.
- **An active Staff member** — subject to the category check below.
- **A Team Lead**, when the caller's role is Account Manager/Site Lead/Super Admin (`TEAM_LEAD_TRANSFER_ROLE_NAMES`) — allowed **unconditionally**, not category-scoped, both inside and outside an active escalation. This is the deliberate "any Account Manager can hand work to any Team Lead company-wide" business rule (§3.2, relationship #3) — it is not a bug, and it does not require the Team Lead's category to match the ticket's.
- **A Site Lead**, when the caller is Super Admin — allowed.
- **An Account Manager**, when the caller is Site Lead/Super Admin, an active escalation exists, and the candidate is validated against the Reporting Manager mapping for the ticket's category — allowed.

If none of the above matched, 400. If the target is already the assigned agent, 400. **Staff-target category scoping is unconditional** (a real, previously-existing gap that was closed — it used to only apply during an active escalation): unless the match came from one of the unconditional branches above, a Staff target's own category must equal the ticket's `ticket_type`, else 400.

A successful transfer writes `AGENT_TRANSFERRED`, notifies the new agent (`TICKET_ASSIGNED`) plus the client's Account Manager and the new agent's own Team Lead, and — if the ticket had a pending escalation — counts as accepting it (`acknowledge_via_assignment`).

### 12.3 Escalation lifecycle (`TicketEscalation`, `EscalationService`)

**Starting level is dynamic** (`_resolve_starting_level`) — escalation begins one level *above* whoever currently owns the ticket, since re-notifying the person already sitting on it achieves nothing:
- Unclaimed ticket (`agent_id IS NULL`), or an orphaned/not-found agent → `TEAM_LEAD`.
- Current agent holds the Team Lead role → `MANAGER` (skips Team Lead entirely).
- Current agent holds the Account Manager role → `SITE_LEAD`.
- Any other role (i.e., Staff) → `TEAM_LEAD`.

**Creation** (`_create_escalation`, shared by `manual_escalate` and `auto_escalate_if_needed`):
1. Snapshots `original_priority` before any mutation.
2. Bumps `Ticket.current_priority` to `CRITICAL` (idempotent no-op if already there) via the same `SLAService.reshift_resolution_clock_for_priority_change` path a manual priority change uses — so the Resolution SLA clock's own `priority` column (what the sweep's math actually keys off) stays consistent. Writes `PRIORITY_CHANGED` attributed to `ActorRole.SYSTEM`/"Escalation workflow." **This never reverts** — not on acknowledge, not on closing the escalation, not on ticket resolution/closure.
3. Resolves the starting level, then walks forward (`TEAM_LEAD → MANAGER → SITE_LEAD`) until a level has a non-empty owner set — an escalation is never created with zero actionable owners.
4. Ack window (`ack_due_at`) is computed from the **original** (pre-CRITICAL) priority's `SLAPolicy.escalation_ack_target_minutes` (default fallback 30 minutes if no policy row) — never CRITICAL's own policy row.
5. Writes `ESCALATION_CREATED`; notifies the new owners plus Site Lead/Super Admin (who always see every escalation) via both in-app notification and real email.

Re-escalating an already-escalated ticket manually instead advances it one level further (400 at the terminal `SITE_LEAD` level).

**Acknowledge vs. Acknowledge-via-Assignment vs. Confirm-Assignment — three distinct actions, only two of which start anything**:
- **`acknowledge()`** (bare click, requires strict `owner_ids` membership — no Site Lead/Super Admin bypass): only stops the ack-window auto-advance timer. Does **not** reshift the Resolution SLA clock and does **not** start the handling-stage clock.
- **`acknowledge_via_assignment()`** (called automatically from `transfer_agent`/`claim_ticket` right after a successful assignment/claim): calls `_complete_acceptance`.
- **`confirm_assignment()`** (the dedicated "keep the current assignee" endpoint, for the one case neither transfer nor claim reaches): also calls `_complete_acceptance`, same strict `owner_ids` membership requirement.

**`_complete_acceptance`** is the one place both the Resolution SLA and the handling-stage clock actually start/restart — guarded so it only fires if no stage is currently running (idempotent against repeated acknowledge/reassign calls): advances `handling_stage` by 1, computes that stage's target minutes (a percentage of the *original* resolution target — see 12.4), restarts the Resolution SLA clock with a full fresh window at that target, and dual-writes the legacy handling-SLA mirror table. Writes `ESCALATION_ACKNOWLEDGED`.

**Ack-window auto-advance** (`evaluate_overdue`, run every sweep tick): every `ACTIVE` escalation whose `ack_due_at` has passed gets moved to the next level (or re-notified at the terminal level if already `SITE_LEAD`) — new owners resolved the same way as creation, ack window reset from the original priority. Writes `ESCALATION_ADVANCED`.

**Handling-SLA-breach advance** (`advance_for_handling_sla_breach`, triggered when a running stage's `handling_stage_due_at` lapses): recomputes the starting level fresh (not `next_level` from the current one) — since a handling-SLA breach means someone accepted and then failed to resolve it in time, which is a new failure against *current* ownership, not proof the current level is unreachable. Writes `ESCALATION_ADVANCED` tagged `reason: "escalation_handling_sla_breach"` (reusing the same event type, distinguished by that tag).

**Closure** (`close_for_ticket_resolution`, called when the Resolution SLA clock completes): no-op if no active escalation; otherwise sets `status=CLOSED`, `closed_reason="TICKET_RESOLVED"` (or `"MANUALLY_CLOSED"` for a direct manual close). Writes `ESCALATION_CLOSED`.

### 12.4 EscalationHandlingSLA (second internal clock)

Target = `round(original_resolution_target_minutes * stage_percentage / 100)`, where `stage_percentage` comes from `SLAPolicy.handling_stage_percentages[stage-1]` (an ordered list, e.g. `[25.0, 12.5, 6.25]` — the first acceptance gets 25% of the original resolution window, the second re-acceptance after a breach gets 12.5%, etc.; clamped to the last configured percentage if the stage index exceeds the list). Falls back to a flat 60-minute default only if no policy/percentages exist at all. `start_if_not_started` is idempotent against an existing **active** row for that escalation — acknowledging or reassigning again never restarts an already-running stage clock. As of the 2026-07-20 redesign, this table is a **dual-write mirror only** — the actual stage counter and Resolution-SLA-clock restart live on `ticket_escalations.handling_stage`/`handling_stage_due_at` and are driven directly by `EscalationService`, not by this table's own breach detection (which still runs, but purely to keep this table's own `breached_at` accurate for any legacy display reading it).

### 12.5 The escalation freeze mechanism

`ensure_ticket_not_frozen_by_escalation`: if a ticket has an active, not-yet-accepted escalation, **every actor including supervisors** is blocked from acting on it — the one deliberate exception to "supervisors bypass everything," since every possible escalation owner is itself a supervisor. "Accepted" is determined by whether an `EscalationHandlingSLA` row exists for the escalation when that repository is supplied to the check (the precise signal); callers that don't supply it fall back to a coarser `status == ACTIVE` check. This freeze check is wired into `add_internal_note`, `add_reply`, and `change_status` via `ensure_agent_can_act_on_ticket`. **`change_priority` calls only the freeze check directly (not the full ownership check)** — any permission-holder can change priority on any ticket in their visibility scope, by design. See §19 for confirmed gaps where this freeze is skipped entirely on certain other action paths.

---

## 13. Notifications System

### 13.1 Model (`notifications` table — see §5.B for full column list)

`notification_type` is a plain string (not an enum) so new types don't require a migration. Current values in use: `MAIL_RECEIVED, CLIENT_REPLY, TICKET_ASSIGNED, PERMISSION_REQUESTED, PERMISSION_APPROVED, PERMISSION_REJECTED, PERMISSION_REVOKED, PERMISSION_GRANTED, EDIT_ACCESS_REQUESTED, EDIT_ACCESS_APPROVED, EDIT_ACCESS_REJECTED, SLA_HALF_ELAPSED, SLA_AT_RISK, SLA_BREACHED, SLA_ESCALATED, ESCALATION_CREATED, ESCALATION_ACKNOWLEDGED, ESCALATION_ADVANCED, ESCALATION_CLOSED, TICKET_STATUS_CHANGED, TICKET_PRIORITY_CHANGED, TICKET_RESOLVED, INTERNAL_NOTE_ADDED`. (`ESCALATION_ACKNOWLEDGED`/`ESCALATION_CLOSED` are defined constants but currently have **no active `.notify()` call site** — only their audit-log counterparts are actually written.)

### 13.2 Trigger catalogue

| Trigger | Type | Recipients | Link |
|---|---|---|---|
| Permission request submitted | `PERMISSION_REQUESTED` | The one selected approver | `/permission-requests` |
| Permission request approved/rejected/revoked | `PERMISSION_APPROVED`/`REJECTED`/`REVOKED` | The requester | `/permission-requests` |
| Direct permission grant/revoke (admin UI) | `PERMISSION_GRANTED`/`REVOKED` | Target user | `/profile` |
| New inbound email, no ticket yet | `MAIL_RECEIVED` | Client's Account Manager + all Site Lead/Super Admin (or just the latter if no client matched) | `/inbox` |
| Reply lands on an already-ticketed thread | `CLIENT_REPLY` | Ticket's assigned agent + that agent's Team Lead (deliberately not fanned to Site Lead/Super Admin, to avoid flooding at volume) | `/tickets/{id}` |
| Edit-access requested/approved/rejected | `EDIT_ACCESS_*` | Reviewer(s) / requester | `/tickets/{id}` |
| Internal note added | `INTERNAL_NOTE_ADDED` | Ticket stakeholders minus actor | `/tickets/{id}` |
| Status changed into RESOLVED | `TICKET_RESOLVED` | Stakeholders minus actor | `/tickets/{id}` |
| Any other status change | `TICKET_STATUS_CHANGED` | Stakeholders minus actor | `/tickets/{id}` |
| Priority changed | `TICKET_PRIORITY_CHANGED` | Stakeholders minus actor | `/tickets/{id}` |
| Ticket reassigned | `TICKET_ASSIGNED` | New agent + client's Account Manager + new agent's Team Lead | `/tickets/{id}` |
| Resolution SLA crosses HALF_ELAPSED/AT_RISK/BREACHED | `SLA_HALF_ELAPSED`/`SLA_AT_RISK`/`SLA_BREACHED` | Resolved current owner (assigned agent, or category team, or global inbox if unclaimed) | `/tickets/{id}` |
| First Response SLA crosses a threshold | Same 4 names, First-Response variant | Rule-resolved recipients | `/inbox?interaction_id={id}` — opens the specific message, not just the inbox |
| Escalation created (manual or auto) | `ESCALATION_CREATED` | New level's owners ∪ Site Lead/Super Admin | `/tickets/{id}` |
| Escalation advanced (ack-window timeout, manual re-escalate, or handling-SLA breach) | `ESCALATION_ADVANCED` | New level's owners ∪ Site Lead/Super Admin | `/tickets/{id}` |

Every SLA/escalation notification also triggers a real outbound email in parallel (subject = title, body = message + an absolute link), via the SMTP-or-log-only path described in §11.3.

### 13.3 Delivery mechanism — Server-Sent Events (real-time push, replacing 30s polling)

An in-memory, per-process pub/sub (`NotificationStreamManager`), keyed on `user_id`, mapping to a set of per-connection queues (one per open tab/device — several simultaneously-open tabs each get an independent copy of every event). `NotificationService.notify()` writes the DB rows, then publishes to any open queues for that recipient (skipped cheaply if nobody's connected). Route: `GET /notifications/stream`, authenticated via a dedicated dependency that accepts the token as a `?token=` query param (browsers' native `EventSource` can't set headers) and opens its own short-lived DB session for the one-time auth check rather than holding a pooled connection for the life of the (potentially hours-long) stream. Event shape: `event: notification` / `data: {"notification": {...}, "unread_count": N}`. A `: heartbeat` comment every 25 seconds keeps proxies from killing the idle connection and doubles as disconnect-detection. No Redis — single-process assumption, same tradeoff as the RBAC permission cache (§8.5); scaling to multiple worker processes would need a shared broker, not attempted today.

---

## 14. Audit Logging

Two entirely separate, disjoint audit tables, owned by different modules — never cross-referenced except conceptually (both FK into `users.user_id`).

### 14.1 Ticketing-domain: `ticket_audit_logs`

Full schema in §5.B. `event_type` is one of the 34 `AuditEventType` values (§6). Write path is a single stateless static method, `AuditLogService.log_event`, that never commits its own transaction (rides the caller's). `actor_role` is `AGENT` for an authenticated human caller, `SYSTEM` for a genuinely automatic write with no HTTP caller (e.g., the SLA sweep — `actor_name="SLA Sweep"`), and `CLIENT` specifically for inbound email (the client is the actor for `EMAIL_RECEIVED`).

**Reply/note bodies are never audited** — only the fact that a reply/note was added (`{ticket_id}` in `new_values`), never the message content itself. `TICKET_CREATED` is written only by the one real ticket-creation path (`InboxTicketService.create_ticket_from_interaction`) — a separate `TicketService.create()` exists in code but is never called from any route, so it produces no audit trail because nothing ever calls it.

### 14.2 RBAC-native: `audit_logs` (distinct table/name)

Full schema in §5.B — note `old_value`/`new_value` here are plain `Text` (manually `json.dumps`-serialized by callers), not JSONB like the ticketing table. `action` strings in active use: `auth.login`, `auth.login_failed` (with a `reason` of `invalid_email`/`account_inactive`/`invalid_password`), `auth.logout`, `auth.change_password`; `permission_request.create/approve/reject/revoke`; `permission_override.grant/revoke`; `role.create/update/delete/permissions_added/permissions_removed`; `user.create/update/role_changed/activate/deactivate/delete`. No login/logout/permission event ever touches the ticketing table — the two are fully domain-separated.

---

## 15. Entity Lifecycles — Consolidated Reference

| Entity | Created by | Terminal state | Notes |
|---|---|---|---|
| **User** | RBAC admin action (`user:create`) | Deactivated (`is_active=False`), never hard-deleted in normal flow | `permission_version` bumps on any RBAC-relevant change (role/category/manager/teamlead reassignment, activate/deactivate, permission override grant/revoke, role's own permission set changing) |
| **Client** | RBAC/ticketing admin action, or seed script | `is_active=False` | One `inbox_email`, one owning Account Manager |
| **Interaction** | Inbound email (system), or agent reply/note/attachment action | Soft-deleted (`is_visible=False`) via Hide — never hard-deleted | The only entity every Ticket must trace back to |
| **Ticket** | `InboxTicketService.create_ticket_from_interaction` only | `CLOSED` | Reopenable from CLOSED only |
| **Attachment** | Upload action, tied to an Interaction | Deleted (`archive_attachment`) or orphaned-cleanup on draft discard | Never has its own status beyond the inert `scan_status` stub |
| **ResolutionSLA** | Ticket creation (or re-created/resumed on reattachment) | `COMPLETED` (never resurrected) | Restarts (fresh window) only via escalation acceptance; reshifts (proportional) only via manual priority change |
| **FirstResponseSLA** | New thread-root Interaction | `COMPLETED` | Never pauses, never restarts — one-shot triage-speed measurement |
| **TicketEscalation** | First `ESCALATED` SLA crossing (auto) or manual escalate action | `CLOSED` (on Resolution SLA completion) | At most one non-CLOSED row per ticket; advances through levels, never regresses |
| **EscalationHandlingSLA** | Escalation acceptance (`_complete_acceptance`) | `COMPLETED` or `breached_at` set | Dual-write mirror as of the 2026-07-20 redesign — not the authoritative stage counter |
| **Notification** | Any of the ~20 trigger events in §13.2 | `is_read=True` | Never deleted by any code path found |
| **PermissionRequest** | User submits a request for a permission they lack | `APPROVED`/`REJECTED`/`REVOKED` | `PENDING` is the only non-terminal state |
| **UserPermissionOverride** | Direct grant, or approval of a PermissionRequest | Soft-revoked (`revoked_at` set, row never deleted) | Optionally ticket-scoped; optionally time-limited (`expires_at`) |

---

## 16. Organization Structure Detail

Beyond the RBAC role hierarchy (§3), the application computes a **dynamic org chart per viewed profile** (`OrganizationService`) — every chart is the full company chain from the top down through whoever is being viewed, then continuing down through their own subordinates; never one fixed, static tree.

- **Downward expansion**: Super Admin → all Site Leads → all Account Managers → **every** Team Lead (reflecting the unrestricted ticket-assignment relationship, §3.2 #3, directly in the chart) → that Team Lead's own Staff. Each Team-Lead-under-Account-Manager edge is tagged `relationship_to_parent`: `"reports_to"` (real `manager_id` match), `"reporting_manager"` (Reporting Manager category match), or `"assignable"` (neither — just the unrestricted ticket-assignment relationship). Site Lead is inserted as a single fixed layer (no `site_lead_id` column exists to resolve a specific one from — every Account Manager sits under the same company-wide Site Lead(s) by product convention).
- **Upward expansion**: stays narrow and specific, never fanning out to a sibling's unrelated branch. A Team Lead's connected Account Manager(s) are their real `manager_id` supervisor *and* every Account Manager who is Reporting Manager for that Team Lead's category (genuinely can be more than one) — each renders as a sibling ancestor showing only the one shared branch back down to the viewed profile.
- **`UserService` validates `manager_id`/`teamlead_id` for role/category consistency** on create/update (not retroactively against existing drift): `manager_id` must reference an Account Manager (or Site Lead/Super Admin, if the subject being set is itself an Account Manager); `teamlead_id` must reference a Team Lead whose own `category_id` matches the subject's.
- **`OrganizationService._build_subtree`/`get_subordinate_user_ids`** (used to scope an Account Manager's permission-override grant authority — a purely RBAC concept) are deliberately narrow and real-reporting-line-only — neither a Reporting Manager assignment nor the wider ticket-assignment relationship widens who an Account Manager can grant/revoke permissions for.

---

## 17. Reference / Seed Data

### 17.1 Categories (fixed UUIDs, `alembic_rbac` migration `cc5cf10fe410`)

| category_id | category_name |
|---|---|
| `a3efa585-dbbf-418c-85fc-314b569dce23` | Eligibility |
| `e219cf57-8be5-4296-b495-247d7a53dfc0` | Patient Calling |
| `804aced2-8833-4049-b506-8a260c4e18e8` | AR |
| `39146d2a-bfb9-4544-a27e-96af929a6794` | Payment Posting |
| `d1ac4422-17c3-4f77-827d-7245a3f2b657` | PA |
| `b90953f7-fabb-4803-9a7f-a03471dbcd6a` | Charge Entry |
| `d6e00cb2-a9e9-4df0-8407-70c4a2884193` | Claims |

### 17.2 Roles

No fixed UUIDs — created plainly by the seed script. Six roles: `Super Admin`, `Site Lead`, `Account Manager`, `Team Lead`, `Staff`, `Viewer`. ("Account Manager" is an in-place rename of a legacy "Manager" role, preserving `role_id`, done idempotently by the seed script rather than a migration.)

### 17.3 SLA Policy rows (exact seeded/migrated values, fixed UUIDs)

| Field | HIGH | MEDIUM | LOW | CRITICAL |
|---|---|---|---|---|
| `policy_id` | `2f6a5e9c-6b3e-4b58-9b3b-2d9f2a6e1a10` | `7d3c8f21-9a4e-4a2b-9d5b-4e7c1b2a8f31` | `c1a9b4d6-2e5f-4c7a-8b1d-9f3e6a4c2b52` | `a4e8c2f6-1b3d-4a5e-9c7f-2d6b8a0e4c91` |
| `first_response_target_minutes` | 1440 (24h) | 2880 (48h) | 4320 (72h) | 5 |
| `resolution_target_minutes` | 4320 (3d) | 7200 (5d) | 10080 (7d) | 60 (1h) |
| `escalation_ack_target_minutes` | 15 | 30 | 60 | 10 |
| `handling_stage_percentages` | `[25.0, 12.5, 6.25]` | `[25.0, 12.5, 6.25]` | `[25.0, 12.5, 6.25]` | `[25.0, 12.5, 6.25]` |
| `warning_1_percentage` / `warning_2_percentage` | 50.0 / 80.0 | 50.0 / 80.0 | 50.0 / 80.0 | 50.0 / 80.0 |

**⚠ See §19 for a confirmed, undocumented live-database deviation on the MEDIUM row** — the values above are what the migrations set; the live database may currently hold different numbers on that one row.

### 17.4 Demo users (27 seeded, `unified-backend/scripts/rbac_seed/seed.py`)

| Name | Email | Role | Category | Reports to (manager_id) | Team Lead (teamlead_id) |
|---|---|---|---|---|---|
| Super Admin | admin@rbac.com | Super Admin | — | — | — |
| Site Lead | sitelead@probeps.com | Site Lead | — | — | — |
| Account Manager | manager@probeps.com | Account Manager | — | — | — |
| Team Lead | teamlead@probeps.com | Team Lead | Eligibility | manager@probeps.com | — |
| Priya Nair | priya.nair@probeps.com | Team Lead | Patient Calling | manager@probeps.com | — |
| Staff | staff@probeps.com | Staff | Eligibility | manager@probeps.com | teamlead@probeps.com |
| John Carter | john.carter@probeps.com | Staff | Eligibility | manager@probeps.com | teamlead@probeps.com |
| Emma Watts | emma.watts@probeps.com | Staff | Patient Calling | manager@probeps.com | priya.nair@probeps.com |
| Liam Brooks | liam.brooks@probeps.com | Staff | Patient Calling | manager@probeps.com | priya.nair@probeps.com |
| Rahul Mehta | rahul.mehta@probeps.com | Team Lead | AR | manager@probeps.com | — |
| Ananya Rao | ananya.rao@probeps.com | Staff | AR | manager@probeps.com | rahul.mehta@probeps.com |
| Vikram Shah | vikram.shah@probeps.com | Staff | AR | manager@probeps.com | rahul.mehta@probeps.com |
| Neha Kapoor | neha.kapoor@probeps.com | Team Lead | Payment Posting | manager@probeps.com | — |
| Rohan Gupta | rohan.gupta@probeps.com | Staff | Payment Posting | manager@probeps.com | neha.kapoor@probeps.com |
| Isha Malhotra | isha.malhotra@probeps.com | Staff | Payment Posting | manager@probeps.com | neha.kapoor@probeps.com |
| Arjun Verma | arjun.verma@probeps.com | Team Lead | PA | manager@probeps.com | — |
| Kavya Iyer | kavya.iyer@probeps.com | Staff | PA | manager@probeps.com | arjun.verma@probeps.com |
| Aditya Kumar | aditya.kumar@probeps.com | Staff | PA | manager@probeps.com | arjun.verma@probeps.com |
| Simran Kaur | simran.kaur@probeps.com | Team Lead | Charge Entry | manager@probeps.com | — |
| Karan Singh | karan.singh@probeps.com | Staff | Charge Entry | manager@probeps.com | simran.kaur@probeps.com |
| Divya Pillai | divya.pillai@probeps.com | Staff | Charge Entry | manager@probeps.com | simran.kaur@probeps.com |
| Farhan Ali | farhan.ali@probeps.com | Team Lead | Claims | manager@probeps.com | — |
| Meera Joshi | meera.joshi@probeps.com | Staff | Claims | manager@probeps.com | farhan.ali@probeps.com |
| Sanjay Reddy | sanjay.reddy@probeps.com | Staff | Claims | manager@probeps.com | farhan.ali@probeps.com |
| Viewer | viewer@probeps.com | Viewer | — | — | — |
| Sophia Turner | sophia.turner@probeps.com | Viewer | — | — | — |

Passwords are seeded as plain demo strings (e.g. `Admin@123456`, `Welcome@123`) — obviously not representative of production credential hygiene; irrelevant to synthetic *business* data but worth knowing if the synthetic environment also needs working login credentials.

**Demo Reporting Manager assignment**: `manager@probeps.com` is seeded as Reporting Manager for the Eligibility category.

### 17.5 Demo clients (7 seeded, `unified-backend/scripts/ticketing_seed/seed_clients.py`)

| name | inbox_email |
|---|---|
| ABC Clinic | deva@painmedpa.com |
| XYZ Medical Group | shreyojit@probeps.com |
| Sunrise Health | revanth@probeps.com |
| Lakeside Pediatrics | lakeside@probeps.com |
| Metro Family Care | metro@probeps.com |
| Golden State Orthopedics | goldenstate@probeps.com |
| Riverbend Dental Group | gogineni@painmedpa.com |

No hardcoded UUIDs. `account_manager_id` is resolved at seed time by round-robin across every active Account Manager — on a fresh DB with only `manager@probeps.com` seeded, all 7 route to that one Account Manager.

---

## 18. Difficulty Taxonomy for an Evaluation/Test Query Set (if building one)

Useful if the synthetic environment will also be used to evaluate any matching/retrieval/triage-assist feature against real RCM scenarios:

| Tier | What it tests | RCM example |
|---|---|---|
| **Easy** | Clear, direct match to one ticket | "Following up on claim #48213 denial — any update?" |
| **Moderate** | Same meaning, different wording | "Checking back on that rejected claim from last week" |
| **Hard Semantic** | Vague/incomplete but still matchable | "Any update on this?" from a client with exactly one recently-active ticket |
| **Same-Customer Disambiguation** | One client, multiple open tickets, must resolve to the right one | A client with an open Claims ticket AND an open PA ticket both get a generic "any update?" |
| **Hard Negative** | Looks similar, but genuinely no matching ticket exists | A new denied claim for a different patient/claim number at a client with an unrelated open Claims ticket |
| **Boilerplate** | Very short, generic, low-signal | "Thanks!" / "Got it" / "Any update?" |

A realistic thread is typically 3–8 messages alternating INBOUND (client) / OUTBOUND (agent reply) direction, occasionally with an INTERNAL_NOTE mixed in for internal handoff context.

---

## 19. Known Bugs, Drift, and Live-State Caveats

These matter for a "production-aligned" synthetic environment because they determine whether the environment should model **intended** behavior (per this document's design descriptions) or **actual current enforcement** (which has confirmed gaps). This section distinguishes source-code-verifiable facts (re-checked while producing this document) from **project-memory-only** facts (point-in-time observations about live database state or a prior audit, which cannot be re-derived from source and should be re-verified before being trusted as still current).

### 19.1 Confirmed in source code (re-verified for this document)
- `alembic_ticketing` has had two unmerged migration heads in the past, and `sla_breach_notification.py`'s `cycle` column is defined twice in the same class body (the second definition silently wins) — a real, harmless-but-notable drift artifact.
- `Ticket.ticket_type` has no FK/CHECK constraint to `categories` at all — purely a frontend-enforced convention.
- `Attachment.scan_status` is a complete stub — confirmed by grep, no code path anywhere reads or writes it beyond the default.
- `TicketService.create()` exists in code but is never called from any route — the only real ticket-creation path is `InboxTicketService.create_ticket_from_interaction`.
- No ML/embedding/vector/recommendation/feedback infrastructure exists anywhere in this codebase (confirmed via repo-wide search) — no pgvector, no embedding columns, no feedback/rating tables. The only "recommendation"-shaped code is the deterministic, non-ML thread-matching heuristic in `open_email_service.py`.

### 19.2 Confirmed via a prior code audit (project memory, dated 2026-07-20 — 9 days old as of this document; **re-verify against current code before treating as still-present**, since fixes may have landed since)
A code-level audit of the SLA/escalation implementation found these confirmed bugs, contradicting some of this application's own intended-design claims:
1. **`TicketPriority.CRITICAL` was found to have zero enforcement on the manual `change_priority` path** — any `ticket:change_priority` holder could force or reverse CRITICAL on any ticket, despite the design intent (§9.2) that only the escalation workflow ever sets it.
2. **`EscalationService.manual_escalate` was found to never call `ensure_account_manager_owns_ticket_client`** — an Account Manager could escalate any ticket company-wide, not just their own clients'.
3. **The escalation freeze check (`ensure_ticket_not_frozen_by_escalation`) was found to be skipped entirely** (not just falling back to the coarser check) for `close_ticket`, `reopen_ticket`, and `AttachmentService.upload_attachment` — none of these three call sites pass the escalation repositories needed to run the check at all.
4. **An acknowledge-without-assign dead zone was found**: `evaluate_overdue` only scans `ACTIVE`-status escalations, so an escalation that reached `ACKNOWLEDGED` (via a bare `acknowledge()` click) but was never actually assigned/confirmed never times out or advances further — a permanent stall state.
5. Also found: the sweep interval was hardcoded to 10 seconds in `sla_scheduler.py`, not reading the settings field the rest of this application's documentation describes as configurable — real doc/code drift, separate from the four security-relevant findings above.

**A phased remediation plan was drafted but, as of that memory's date, not yet implemented.** If this synthetic environment is meant to model **intended, documented** behavior, treat items 1–4 as bugs to exclude from simulation. If it's meant to model **actual current production enforcement** (e.g., for security-test or adversarial-scenario data), these are real, exploitable gaps worth representing.

### 19.3 Live-database-only state (project memory, 16 days old as of this document — **cannot be re-verified from source code at all**; only a live query against the running database's `sla_policies` table would confirm current values)
The MEDIUM-priority `SLAPolicy` row (`policy_id 7d3c8f21-9a4e-4a2b-9d5b-4e7c1b2a8f31`) was live-PATCHed on 2026-07-13 via the admin SLA-policy-editing endpoint — **not** via a migration or the seed script — from `first_response_target_minutes: 20, resolution_target_minutes: 20` down to `2, 2`, specifically to speed up SLA-tier transitions for a live demo. The pre-demo value of `20/20` was itself already an earlier, unlogged deviation from the migration's own originally-set `2880/7200` (§17.3's table). So there are potentially **two layers of undocumented drift** stacked on this one row: `2880/7200` (as migrated) → `20/20` (earlier undocumented edit) → `2/2` (2026-07-13 demo edit) → possibly reverted back to `20/20` since (the memory records an intent to revert to `20/20`, not confirmation that it happened).

**If this synthetic environment's timing realism matters, do not trust §17.3's MEDIUM row values as the current live truth** — query the live `sla_policies` table directly, or use the §17.3 migrated values only if explicitly modeling "intended production timing" rather than "whatever this specific demo database currently holds."

### 19.4 Scope limitations acknowledged during the RBAC compliance audit (by design, not bugs)
- Personal permission overrides are **purely additive** — there is no mechanism to grant a user *less* than their role default (a "role allows, override revokes" scenario isn't buildable without new schema work).
- Related Tickets link/unlink and the Claim Ticket button have **no permission gate at all** in the permission matrix this application's RBAC was audited against — both are open to any authenticated agent with ticket view access, not a gap so much as an unresolved question for whoever maintains the permission matrix doc.

---

## 20. Planned But Not Implemented (design-only — do not model as existing behavior)

**Intelligent Workload-Based Ticket Assignment & Transfer Recommendation** — a design exists (not yet built, migrated, or verified) for a scoring/ranking layer on top of the existing eligibility logic in `AssignmentService`/`EscalationService.get_acknowledge_candidates`, which today return an eligible candidate *set* with no ordering signal. The design proposes scoring candidates by: open-ticket count weighted by priority, SLA-risk exposure of their open tickets, active-escalation ownership count, and category/skill fit — aggregated via batched `GROUP BY` queries, never per-candidate lookups. No `WorkloadRepository`, `WorkloadScoringService`, `workload_score` field, or ranking parameter exists in the codebase today. **If a synthetic environment is meant to represent the current, real application, this feature must not appear as functioning** — it is design documentation only, dated 2026-07-27, explicitly flagged as unbuilt.

---

## 21. Assumptions & Open Design Questions (genuine decisions, not facts derivable from code)

These are not answerable from the codebase and must be confirmed with a human stakeholder before being treated as fixed requirements for a synthetic environment:

1. **Scale** — how many synthetic clients, tickets per client, messages per ticket, and users per role/category to generate. No real historical distribution exists in this codebase to draw from.
2. **Category/priority/status distribution weights** — no real historical distribution exists. A reasonable starting assumption (not a derived fact): Claims/AR/Payment Posting likely carry the most ticket volume in a real RCM shop, Eligibility/Patient Calling moderate, PA/Charge Entry lighter — sanity-check this against whoever actually runs the represented business, don't treat it as fact.
3. **Time span to simulate** — a single current-state snapshot, or a realistic multi-month history with a mix of already-closed and still-open tickets (useful for recency-based features)?
4. **Whether to include SLA/escalation state at all** — every table in §5.B beyond `tickets`/`interactions`/`clients` is optional depending on whether the synthetic environment's consumers (dashboards, ML features, load tests, etc.) actually read SLA/escalation data or just need realistic ticket/conversation content.
5. **Whether to model the confirmed enforcement gaps in §19.2** as present (if the environment needs to exercise/test those specific bugs) or absent (if the environment should represent intended, corrected behavior) — this materially changes what "correct" synthetic behavior means for CRITICAL-priority assignment, escalation ownership, and freeze-check enforcement.
6. **Whether synthetic users need real, working login credentials** — the demo seed data's passwords are plaintext-in-source-and-obviously-fake; a genuinely "production-aligned" environment would need its own credential-generation policy, which is outside what this document can specify.
7. **PHI/compliance posture for generated content** — no real PHI or real payer/company identities should appear (synthetic client names, patient references as initials or clearly-fake full names, generic/plausible payer names) — this is a strong recommendation carried over from the companion ML-focused document, not a technical constraint enforced anywhere in the code itself.

---

## 22. File Map (for direct re-verification of any claim above)

| Area | Path |
|---|---|
| Shared identity models | `shared_models/shared_models/models/{user,role,category}.py` |
| RBAC seed data | `unified-backend/scripts/rbac_seed/seed.py` |
| Ticketing seed data | `unified-backend/scripts/ticketing_seed/seed_clients.py` |
| RBAC access control | `unified-backend/app/rbac/services/access_control.py` |
| Ticketing access control | `unified-backend/app/ticketing/services/access_control.py` |
| Ticket/Interaction/Attachment/Client models | `unified-backend/app/ticketing/models/{ticket,interaction,attachment,client,ticket_relation}.py` |
| SLA models | `unified-backend/app/ticketing/models/{resolution_sla,first_response_sla,sla_policy,sla_breach_notification,escalation_handling_sla}.py` |
| Escalation model | `unified-backend/app/ticketing/models/ticket_escalation.py` |
| SLA services | `unified-backend/app/ticketing/services/{sla_service,sla_sweep_service,sla_escalation_rules,escalation_rules}.py` |
| Escalation services | `unified-backend/app/ticketing/services/{escalation_service,escalation_handling_sla_service}.py` |
| Assignment | `unified-backend/app/ticketing/services/assignment_service.py` |
| Communication / mail | `unified-backend/app/ticketing/services/{interaction_service,email_service,open_email_service,mail_mapping_service,inbox_ticket_service,outbound_dispatcher,graph_client,attachment_service}.py` |
| Notifications | `unified-backend/app/notifications/{service,sse_manager,models,routes,schemas}.py` |
| Ticketing audit log | `unified-backend/app/ticketing/{models/audit_log.py, services/audit_log_service.py, enums/audit_enums.py}` |
| RBAC audit log | `unified-backend/app/rbac/{models/audit_log.py, services/audit_log_service.py, schemas/audit_log.py}` |
| Organization structure | `unified-backend/app/rbac/services/organization_service.py`, `unified-backend/app/rbac/models/reporting_manager_team.py` |
| Two Alembic chains | `unified-backend/alembic_rbac/versions/`, `unified-backend/alembic_ticketing/versions/` |
| Companion ML-scoped docs | `ML_TICKETING_SCHEMA_REFERENCE.md`, `RCM_TICKETING_KNOWLEDGE_BASE.md` (repo root) |
