# AI Recommendation Service — Production Integration Contract

**Status: authoritative reference, not a design document.** This file describes what `unified-backend` (the running production application) actually stores and actually exposes, as of a direct read of its current source on 2026-08-02. It is the **only source of truth** the AI Recommendation Service should treat as ground truth about the production app. Nothing below is aspirational, proposed, or redesigned — where production doesn't have something, this document says so explicitly rather than suggesting an addition.

**Verification method**: every table/column/type/nullability claim was checked directly against the SQLAlchemy model files, the Alembic migration files that created/altered each table (`unified-backend/alembic_ticketing/versions/`, `unified-backend/alembic_rbac/versions/`), and the Pydantic request/response schemas. Every API claim was checked directly against the FastAPI route decorators in `unified-backend/app/**/api/`. File paths are cited throughout so any claim can be re-verified independently.

**Relationship to other docs already in this repo**: `RCM_APPLICATION_KNOWLEDGE_BASE.md` and `ML_TICKETING_SCHEMA_REFERENCE.md` are broader, narrative companion references produced earlier in this same effort — this document draws on them but independently re-verified the load-bearing facts (routes, response schemas, index DDL) against current source rather than merely restating them. Where this document and those differ on a specific, re-checked detail, trust this document; where this document is silent on something those cover in more narrative depth (e.g. RCM domain glossary, difficulty taxonomies for an eval set), those remain valid supplementary reading. **One specific correction to flag**: those companion docs' description of a "Viewer" role is stale — see §11.2, the role was renamed to "Client" in-place and now serves a second, load-bearing purpose (§4).

**Re-verification pass (2026-08-02, same day as initial authoring)**: every section below was re-checked against current source a second time, at the requesting user's explicit request to establish this as the definitive pre-implementation reference. This pass found and corrected real drift, not just re-confirmed the original text — most notably: (1) the `interaction_type` "retired values" list in §2/§11.5 was incomplete and under-explained (missing `TICKET_CLOSED`/`TICKET_REOPENED`, missing the read-time synthesis mechanism entirely); (2) §4's User entity was missing a major, load-bearing fact — `/api/v1/users` routes present a **merged view** of real `users` rows and `clients` rows; (3) §11.2's role roster was wrong — "Viewer" no longer exists, renamed in-place to "Client"; (4) §14's "known gaps" were re-verified against current code rather than left as year-old hedges, and their status changed materially (two of four are now confirmed-still-present with higher confidence, one is confirmed fixed for two of its three call sites). Every changed claim below is marked inline rather than silently rewritten, so a prior reader can see exactly what moved.

---

## 0. How to read this document

**Field-status legend**, applied to every field discussed below:

- **[STORED]** — a real column in a real production table. Reading it via direct DB access would return this exact value; reading it via the API (where an API exposes it) returns this exact value too.
- **[DERIVED]** — not a stored column anywhere, but computable from stored data. The exact formula/join is given every time this label is used. Production itself computes several of these at query time (never persists them) — treat that as a hard rule for the recommendation service too: computing one of these and writing it back as if it were new stored data would create a value production's own code never produces and never reads.
- **[NOT AVAILABLE]** — does not exist in production today, in any form, stored or derivable. If the recommendation service needs it, that is a real gap to raise with whoever owns the production roadmap — not something to infer, approximate silently, or backfill from unrelated data.

**Two independent Alembic migration chains** write to one physical Postgres database (Neon): `alembic_rbac` (users/roles/permissions/categories — plus, non-obviously, `notifications`, see §8) and `alembic_ticketing` (tickets/interactions/SLA/escalation/attachments/clients). A table's chain is noted per entity below because it affects where to look for that table's own migration history.

**Two mounting facts that matter for API integration**: (1) Ticketing routes are mounted **unprefixed** at the app root (`/tickets`, `/interactions`, `/clients`, `/attachments`, `/sla`, `/internal/sla`, `/inbox`, `/emails`, `/agents`, `/categories`, `/folders`) — RBAC routes are mounted under `/api/v1` (`/api/v1/users`, `/api/v1/auth`, `/api/v1/roles`, `/api/v1/categories`, `/api/v1/audit-logs`, `/api/v1/permission-requests`, `/api/v1/reporting-managers`). Note there are **two different `/categories` endpoints** — `GET /categories` (ticketing, `app/ticketing/api/category.py`) and `GET /api/v1/categories` (RBAC, `app/rbac/api/v1/categories.py`) — both read the same one `categories` table, just mounted twice. (2) Every route requires a Bearer JWT issued by `POST /api/v1/auth/login` — there is no service-to-service API key or separate machine-credential path today; the recommendation service would authenticate as a real user account, same as any frontend client (see §14 for what this implies).

---

## 1. Entity: Client

**Purpose**: a client **company** (e.g. "Lakeside Medical Billing LLC") — never an individual person or patient. This is "the customer" for every purpose in this system. Any number of real people at that company can email in; all route to the same `Client` row via shared-inbox-address matching (see §12.7 — **corrected cross-reference in this pass; the original pointed at a non-existent §12.8**).

**Table name**: `clients` (chain: `alembic_ticketing`). Model: `unified-backend/app/ticketing/models/client.py`.

| Column | Type | Nullable | Default | Status |
|---|---|---|---|---|
| `client_id` | UUID | No | `uuid4()` | [STORED] — PK |
| `name` | String(255) | No | — | [STORED] |
| `inbox_email` | String(255) | No | — | [STORED] — unique; app-side lowercased before write |
| `account_manager_id` | UUID | No | — | [STORED] — FK → `users.user_id`, indexed (`ix_clients_account_manager_id`) |
| `is_active` | Boolean | No | `True` | [STORED] |
| `created_at` | DateTime(tz) | No | `now()` | [STORED] |
| `updated_at` | DateTime(tz) | No | `now()` | [STORED] |

**Required fields**: all seven columns above are `NOT NULL` — there are no nullable columns on this table at all.

**Optional fields**: none at the schema level. (`ClientCreate`, the only write-path Pydantic schema, requires `name`, `inbox_email`, `account_manager_id` — nothing on this table is optional input.)

**Relationships**:
- `account_manager_id` → `users.user_id` (many clients to one Account Manager).
- Referenced by: `tickets.client_company_id`, `interactions.client_id`, `resolution_slas.client_id`, `first_response_slas.client_id` — all point back to this table's `client_id`.

**Constraints**: `inbox_email` globally unique (DB-level unique constraint, confirmed in the initial migration and restated in both companion schema docs).

**Existing indexes**: `ix_clients_account_manager_id` on `account_manager_id` (confirmed: `unified-backend/alembic_ticketing/versions/b8d0f2a4c6e8_add_performance_indexes.py:48`). The unique constraint on `inbox_email` implies its own unique index. No other indexes exist on this table.

**Business meaning**: the client company is the unit of "customer" for every scoping/visibility rule in the app (Account Manager ownership, ticket visibility) and is the correct unit for "same customer" in any recommendation logic — **never** an individual sender. Individual sender identity (name/email address of the specific person who emailed in) is captured only as free-text inside `Interaction.payload` (see §2) — there is no modeled "Contact" or "Patient" entity.

**Lifecycle**: created via `POST /clients` (an onboarding action, gated to authenticated agents); no delete path — `is_active=False` is the only observed retirement mechanism, set via direct DB/admin action (no dedicated deactivate-client endpoint was found in the route list below). Never hard-deleted in any code path found.

**Existing APIs** (all under ticketing's unprefixed mount, tag `Clients`, file `unified-backend/app/ticketing/api/client.py`):

| Method | Path | Purpose | Auth |
|---|---|---|---|
| POST | `/clients` | Onboard a new client company | any authenticated agent |
| GET | `/clients` | List every client (used for pickers/filters) | any authenticated user |
| GET | `/clients/{client_id}/contacts` | Every distinct personal sender address this client has emailed from, most-recent-first | any authenticated user |

**[NOT AVAILABLE]** within `app/ticketing/api/client.py` itself: there is **no `GET /clients/{client_id}`** single-fetch-by-id endpoint in that router — confirmed by reading the full route file; only list, create, and the contacts sub-resource exist there.

**However — corrected in this re-verification pass — a single client row IS fetchable by id, just from a different, non-obvious router**: `GET /api/v1/users/{client_id}` (the RBAC-domain user-detail endpoint, §4) also resolves against `clients.client_id` and returns it in a `UserResponse`-shaped object, because `UserService._resolve_user_or_client` checks the `clients` table as a fallback whenever the id doesn't match a real `users` row. This is not a documentation convenience — it is a real, load-bearing mechanism (the "Client" RBAC role) covered in full in §4. A recommendation service should not rely on this as "the" way to fetch a client (it returns a narrower, user-shaped field set — `name`/`email`(=`inbox_email`)/`is_active`, not `ClientResponse`'s own shape), but it does mean a client-by-id lookup exists in production today, just not where a client-domain caller would first look. Absent that, a recommendation service needing one client's full `ClientResponse` row by id must call `GET /clients` and filter client-side, or read a ticket/interaction that already carries `client_company_id`/`client_name` and use those.

**Fields useful for recommendation and their status**:
| Field a recommendation system might want | Status |
|---|---|
| `name`, `inbox_email`, `account_manager_id`, `is_active` | [STORED] |
| Account manager's resolved name (`account_manager_name`) | [DERIVED] — `ClientResponse.account_manager_name`, resolved server-side via a join to `users`, not persisted on the `clients` row |
| Whether the account manager is still active in that role (`account_manager_active`) | [DERIVED] — computed at read time by checking the referenced user's current role/`is_active`, not stored |
| An individual sender/contact's own identity as a queryable entity | [NOT AVAILABLE] — only reachable as free-text inside interaction payloads; `GET /clients/{id}/contacts` derives a list of `{email, name}` pairs by scanning that client's own interaction history, it does not read from a dedicated contacts table (none exists) |
| Client industry/vertical/size, contract tier, SLA-exception flags | [NOT AVAILABLE] |

---

## 2. Entity: Interaction

**Purpose**: the single, unified timeline row for **every** email, reply, internal note, and attachment event — both before and after a ticket exists. This is the atomic unit of conversational content. A `Ticket` cannot exist without a founding `Interaction` — there is no "blank ticket" creation path anywhere in the codebase (confirmed: `TicketService.create()` exists but is never called from any route; the only real path is `InboxTicketService.create_ticket_from_interaction`).

**Table name**: `interactions` (chain: `alembic_ticketing`). Model: `unified-backend/app/ticketing/models/interaction.py`.

| Column | Type | Nullable | Default | Status |
|---|---|---|---|---|
| `interaction_id` | UUID | No | `uuid4()` | [STORED] — PK |
| `ticket_id` | UUID | **Yes** | — | [STORED] — FK → `tickets`, indexed. NULL while unticketed |
| `interaction_type` | String(50) | No | — | [STORED] — plain string, **not** a Postgres enum. Live values: `EMAIL, REPLY, INTERNAL_NOTE, ATTACHMENT, SLA_PAUSED, SLA_RESUMED` |
| `status` | enum `interaction_status_enum` | No | `PENDING` | [STORED] — `PENDING / ASSIGNED / IGNORED` |
| `direction` | enum `interaction_direction_enum` | No | — | [STORED] — `INBOUND / OUTBOUND / INTERNAL` |
| `performed_by` | UUID | Yes | — | [STORED] — FK → `users`; NULL for inbound email (no authenticated actor) |
| `payload` | JSONB | No | `{}` | [STORED] — shape varies by `interaction_type`, see below |
| `subject` | String(500) | Yes | — | [STORED] — GIN trigram index; NULL for `ATTACHMENT` rows |
| `is_visible` | Boolean | No | `True` | [STORED] — soft-delete flag |
| `removed_by` / `removed_at` | UUID / DateTime(tz) | Yes | — | [STORED] |
| `claimed_by` / `claimed_at` | UUID / DateTime(tz) | Yes | — | [STORED] |
| `tags` | JSONB (list) | No | `[]` | [STORED] |
| `folder_id` | UUID | Yes | — | [STORED] — FK → `mail_folders.folder_id` |
| `is_draft` | Boolean | No | `False` | [STORED] |
| `message_id` | String(255) | Yes | — | [STORED] — unique; RFC 5322 Message-ID |
| `client_id` | UUID | Yes | — | [STORED] — FK → `clients` |
| `parent_interaction_id` | UUID | Yes | — | [STORED] — FK (self) → `interactions`; NULL = thread root |
| `received_at` | DateTime(tz) | Yes | — | [STORED] — SLA clock start; NULL for replies/notes |
| `conversation_id` | String(255) | Yes | — | [STORED] — Microsoft Graph thread id |
| `in_reply_to_message_id` | String(255) | Yes | — | [STORED] |
| `references` | JSONB (list) | Yes | — | [STORED] |
| `created_at` | DateTime(tz) | No | `now()` | [STORED] |

**Required fields (NOT NULL)**: `interaction_id`, `interaction_type`, `status`, `direction`, `payload`, `is_visible`, `tags`, `is_draft`, `created_at`.

**Optional fields (nullable)**: `ticket_id`, `performed_by`, `subject`, `removed_by`, `removed_at`, `claimed_by`, `claimed_at`, `folder_id`, `message_id`, `client_id`, `parent_interaction_id`, `received_at`, `conversation_id`, `in_reply_to_message_id`, `references`.

**Removed column — must never appear as current**: `snoozed_until` was added (`b8d0f2a4c6e8_add_performance_indexes.py`) then dropped entirely (`c3e5a7f9b1d4_drop_snoozed_until_from_interactions.py`) once the Snooze feature was removed. Do not reference it.

**`payload` shape by `interaction_type`** (JSONB, not separately validated column-by-column — only the values a given code path chooses to write actually appear):
- `EMAIL` (inbound): `client_id`, `client_name`, `to_email`, `from_email`, `from_name`, `subject`, `body`, `html_body`, `cc: []`, `to_recipients: []` — mapped from a Microsoft Graph `message` payload by `mail_mapping_service.py`.
- `REPLY` (outbound, sent or draft): `message`, `cc: []`, `bcc: []`, `dispatch_status` (`"QUEUED" | "SENT" | "FAILED" | "DRAFT"`), plus an error detail key on `FAILED`.
- `INTERNAL_NOTE`: `note` text plus `subject`.
- `ATTACHMENT`: attachment-descriptive metadata only (the file itself lives in object storage — see §5).

**Relationships**:
- `ticket_id` → `tickets.ticket_id` (many interactions to one ticket, nullable).
- `client_id` → `clients.client_id`.
- `performed_by`, `removed_by`, `claimed_by` → `users.user_id`.
- `parent_interaction_id` → `interactions.interaction_id` (self-referencing thread link).
- `folder_id` → `mail_folders.folder_id` (this table was flagged but not deep-dived by the companion docs — read `unified-backend/app/ticketing/models/mail_folder.py` directly if the recommendation service needs its exact columns).
- Referenced by: `attachments.interaction_id`, `first_response_slas.interaction_id`.

**Constraints**:
- `message_id` globally unique.
- Unique **partial** index `ix_interactions_one_draft_per_thread_per_agent` on `(parent_interaction_id, performed_by) WHERE is_draft AND is_visible` — at most one active draft per thread per agent, enforced in Postgres itself.

**Existing indexes** (confirmed against `b8d0f2a4c6e8_add_performance_indexes.py` plus later composite migrations): `ticket_id`, `parent_interaction_id`, `client_id`, `status`, `interaction_type`, `performed_by`, `claimed_by`, `folder_id`, `created_at`, `received_at`, individually indexed; plus composite indexes `idx_interactions_ticket_created` (`7b3d5f9a1c4e_add_production_scale_composite_indexes.py`) and `idx_interactions_parent_visible` (`8e1c4a6f2d9b_add_composite_index_for_thread_traversal.py`, for thread traversal). `subject` carries a GIN trigram index.

**Business meaning**: this is the single richest source of conversational content in the system — subject lines and message bodies (inside `payload`) are the actual text a recommendation feature would embed/search over. Everything else on this row is metadata/plumbing (threading, visibility, assignment).

**Lifecycle**: created by inbound email intake (system-authored) or an agent action (reply/note/draft/claim). Soft-deleted only (`is_visible=False` via Hide) — never hard-deleted. `status` flips `PENDING → ASSIGNED` once ticketed (or once replied-to on a still-unticketed thread, with reason `"REPLIED"`).

### 2.1 Interaction-type census — real vs. synthesized, and exactly how each links to a ticket

**Corrected in this re-verification pass**: the original text above understated this. There are **15** distinct `interaction_type`-shaped labels a caller can see on a ticket's timeline (`GET /tickets/{ticket_id}/interactions`), not 6 — because that endpoint merges two genuinely different categories of row. Conflating them is a real accuracy risk for anything counting or classifying "interactions."

**A. Six real, persisted `interactions.interaction_type` values** (`EMAIL, REPLY, INTERNAL_NOTE, ATTACHMENT, SLA_PAUSED, SLA_RESUMED` — as already listed in the column table above) — plus the exact `ticket_id` linkage mechanism for each, verified against `interaction_service.py`/`email_service.py`/`attachment_service.py`/`sla_service.py`/`interaction_repository.py`:

- **Set at INSERT time** (a ticket already exists): `REPLY` on an already-ticketed thread, `INTERNAL_NOTE` (requires an existing ticket to even be called), `ATTACHMENT` on a ticketed thread, `SLA_PAUSED`/`SLA_RESUMED` (**manual-override only** — see the caveat below), and inbound `EMAIL` when the deterministic thread-matcher resolves it onto an already-ticketed conversation (`ticket_id = matched.ticket_id`, `email_service.py`) — all pass `ticket_id` directly into the row.
- **`NULL` at INSERT, filled in later by a batch update**: inbound `EMAIL` (first message of a new thread), outbound `EMAIL` (agent Compose to a client — `interaction_service.py` explicitly passes `ticket_id=None`, same as inbound), and `REPLY` on a not-yet-ticketed thread (linked only via `parent_interaction_id` to the thread root until promoted). For all three, `ticket_id` is only ever set later, in one batch, by `InteractionRepository.assign_thread_to_ticket(root_interaction_id, ticket_id)` — called from both `POST /tickets/from-interaction` and `POST /tickets/{id}/attach-interaction` — which stamps the thread root **and every reply chained to it via `parent_interaction_id`** with the same `ticket_id` and `status=ASSIGNED` in one flush. A reply created while its thread was still unticketed only becomes linked at the moment its root gets promoted, not at its own creation time.

**Corrected caveat, not previously documented**: `SLA_PAUSED`/`SLA_RESUMED` interaction rows are written **only** by the manual-override endpoints (`SLAService.manual_pause`/`manual_resume`, backing `POST /tickets/{id}/sla/pause`/`/sla/resume`). The far more common **automatic** pause/resume — every time a ticket enters/leaves `WAITING_FOR_CLIENT` via `InteractionService.change_status` — writes an `SLA_PAUSED`/`SLA_RESUMED` row **only to `ticket_audit_logs`** (§9) and creates **no `interactions` row at all**. A recommendation/analytics consumer reading the Interactions timeline for SLA-pause history will only ever see manual overrides there; automatic pauses (the common case) are invisible on that endpoint and only visible via the ticket's audit log.

**B. Nine synthesized, non-stored "virtual" rows** — not real `interactions` rows at all, fabricated only at the moment `GET /tickets/{ticket_id}/interactions` is called (`InteractionService.get_ticket_interactions`, `interaction_service.py`), by `synthesize_interaction_from_audit` (`unified-backend/app/ticketing/services/audit_to_interaction.py`). These replaced real interaction rows that used to be written for the same actions; the write side was retired and the read side now reconstructs a display-shaped row from the corresponding `ticket_audit_logs` entry instead:

| Synthesized `interaction_type` | Sourced from `AuditEventType` |
|---|---|
| `STATUS_CHANGE` | `STATUS_CHANGED` |
| `PRIORITY_CHANGE` | `PRIORITY_CHANGED` |
| `AGENT_TRANSFER` | `AGENT_TRANSFERRED` |
| `CLAIM` | `TICKET_CLAIMED` |
| `TICKET_CLOSED` | `TICKET_CLOSED` |
| `TICKET_REOPENED` | `TICKET_REOPENED` |
| `EDIT_ACCESS_REQUESTED` | `EDIT_ACCESS_REQUESTED` |
| `EDIT_ACCESS_APPROVED` | `EDIT_ACCESS_APPROVED` |
| `EDIT_ACCESS_REJECTED` | `EDIT_ACCESS_REJECTED` |

**Linkage mechanism for these 9 is fundamentally different from category A — there is no FK to inherit, because there is no row to have one.** `InteractionService.get_ticket_interactions` calls `AuditLogRepository.list_by_ticket(ticket_id)` (a plain `WHERE ticket_id = :ticket_id` against `ticket_audit_logs`, which already carries a real, denormalized `ticket_id` column set at audit-write time by whatever action logged it), and for each qualifying event type, `synthesize_interaction_from_audit(log, ticket_id, ...)` simply **echoes that same `ticket_id` straight into the fabricated response object**. The association exists only for the duration of that one API call and is rebuilt fresh every time — never persisted, never joinable. The synthetic row's `interaction_id` is set to the audit log's own `audit_id` (a real UUID, but one that does not exist in `interactions` — calling Hide against it would 404). `ATTACHMENT_UPLOADED` is deliberately excluded from synthesis since `ATTACHMENT` already gets a real row; synthesizing it too would double it up.

**Net effect for the recommendation service**: if consuming "all interactions on a ticket" via the API, expect up to 15 distinct type labels, only 6 of which correspond to a real, independently-queryable `interactions` row with its own `interaction_id`/`payload`/`message_id`. The other 9 are ephemeral, read-time-only reconstructions of `ticket_audit_logs` rows and should be treated as such — e.g., don't expect to look one up by its `interaction_id` via any other endpoint.

**Existing APIs**:

| Method | Path | Purpose |
|---|---|---|
| GET | `/interactions/{interaction_id}/thread` | Full thread (root + all children, chronological) for a given interaction id — resolves up to the root first |
| POST | `/interactions/{interaction_id}/hide` | Soft-delete (Hide) an interaction |
| GET | `/inbox` | The shared Mail/Inbox pool listing (pending, unticketed items) |
| GET | `/inbox/{interaction_id}` | Single pending inbox item detail |
| POST | `/inbox/{interaction_id}/claim` | Claim a pending inbox item |
| POST | `/inbox/{interaction_id}/archive` | Archive (informational, no ticket needed) |
| POST | `/inbox/{interaction_id}/reply` | Reply on a not-yet-ticketed thread |
| PATCH | `/inbox/{interaction_id}/tags`, `/inbox/{interaction_id}/folder` | Tag/folder assignment |
| PUT/POST/DELETE | `/inbox/{interaction_id}/draft`, `/draft/attachments`, `/draft/send` | Draft lifecycle (auto-save reply) |
| GET | `/inbox/folder-counts`, `/inbox/view-counts`, `/inbox/sent`, `/inbox/replied`, `/inbox/drafts` | Mail-UI list views |
| GET | `/tickets/{ticket_id}/interactions` | A ticket's own interaction timeline |
| GET | `/tickets/interactions` (query-param batched) | Interactions across many tickets in one call — used to avoid an N+1 fetch pattern |
| POST | `/tickets/{ticket_id}/notes`, `/tickets/{ticket_id}/reply` | Add internal note / external reply to a ticketed thread |
| POST | `/tickets/{ticket_id}/interactions/{interaction_id}/hide` | Hide within a ticket context |
| POST | `/tickets/{ticket_id}/attach-interaction` | Attach a pending interaction onto an existing ticket |

Full file: `unified-backend/app/ticketing/api/{interaction,inbox,ticket}.py`.

**Fields useful for recommendation and their status**:
| Field | Status |
|---|---|
| `subject`, `payload.body`/`payload.html_body` | [STORED] — the actual retrieval content |
| `interaction_type`, `direction`, `received_at`, `created_at`, `client_id`, `ticket_id` | [STORED] |
| `message_id`, `conversation_id`, `in_reply_to_message_id`, `references` | [STORED] — deterministic threading plumbing, not semantic content |
| Sender's individual name/address (`payload.from_name`/`from_email`) | [STORED] — inside `payload`, free text, no separate contact entity |
| An embedding/vector representation of `subject`+body | [NOT AVAILABLE] |
| A classification/intent label (e.g. "Follow-up", "Documentation Provided") | [NOT AVAILABLE] — no such column or concept exists anywhere in the schema |
| "This interaction was previously suggested as a match for ticket X" | [NOT AVAILABLE] — no recommendation-logging table exists |

---

## 3. Entity: Ticket

**Purpose**: the core work item — what a support conversation gets promoted into once an agent decides it needs operational tracking.

**Table name**: `tickets` (chain: `alembic_ticketing`). Model: `unified-backend/app/ticketing/models/ticket.py`.

| Column | Type | Nullable | Default | Status |
|---|---|---|---|---|
| `ticket_id` | UUID | No | `uuid4()` | [STORED] — PK |
| `client_id` | UUID | Yes | — | [STORED] — FK → `users`. **Legacy — always NULL for every ticket created via the real (only) creation path. Do not treat as the client-ownership column.** |
| `client_company_id` | UUID | Yes | — | [STORED] — FK → `clients.client_id`, indexed. **This is the real client-ownership column.** |
| `agent_id` | UUID | Yes | — | [STORED] — FK → `users`, indexed. Currently assigned worker; NULL = unclaimed |
| `created_by` | UUID | Yes | — | [STORED] — FK → `users` |
| `title` | String(255) | No | — | [STORED] — GIN trigram index (DB-only, not declared on the ORM model) |
| `ticket_type` | String(50) | No | — | [STORED] — indexed. **No FK to `categories` — see Constraints below** |
| `current_status` | enum `ticket_status_enum` | No | `OPEN` | [STORED] — indexed |
| `current_priority` | enum `ticket_priority_enum` | No | `MEDIUM` | [STORED] — indexed |
| `custom_fields` | JSONB | No | `{}` | [STORED] — always `{}` in practice; no UI writes it |
| `version` | Integer | No | `1` | [STORED] — optimistic concurrency counter |
| `closed_at` / `closed_by` | DateTime(tz) / UUID | Yes | — | [STORED] — `closed_by` FK → `users` |
| `created_at` | DateTime(tz) | No | `now()` | [STORED] — indexed |
| `updated_at` | DateTime(tz) | No | `now()`/onupdate | [STORED] — DB-only index |

**Required fields (NOT NULL)**: `ticket_id`, `title`, `ticket_type`, `current_status`, `current_priority`, `custom_fields`, `version`, `created_at`, `updated_at`.

**Optional fields (nullable)**: `client_id` (legacy, never written), `client_company_id`, `agent_id`, `created_by`, `closed_at`, `closed_by`.

**Relationships**:
- `client_company_id` → `clients.client_id`.
- `agent_id`, `created_by`, `closed_by` → `users.user_id`.
- Referenced by (1:1 or 1:many): `interactions.ticket_id`, `resolution_slas.ticket_id` (1:1), `ticket_escalations.ticket_id` (at most one non-CLOSED), `ticket_audit_logs.ticket_id`, `ticket_relations.ticket_id`/`.related_ticket_id` (self-link).

**Constraints**: **`ticket_type` has no FK or CHECK constraint to `categories` at all** — it is a bare `String(50)`; nothing at the database level stops an arbitrary string here. Only the frontend dropdown (populated from `GET /categories`) enforces the 7 real `CategoryName` values in practice. Do not assume a recommendation service can trust `ticket_type` to always be one of the 7 canonical values without validating it.

**Existing indexes**: `client_company_id`, `agent_id`, `ticket_type`, `current_status`, `current_priority`, `created_at` individually indexed (confirmed `b8d0f2a4c6e8_add_performance_indexes.py`). **DB-only indexes** not declared on the ORM model, only via raw migration SQL: `ix_tickets_pool_view` (partial, `WHERE agent_id IS NULL AND current_status='OPEN'`), `ix_tickets_title_trgm` (GIN trigram on `title`), `ix_tickets_updated_at`.

### 3.1 Unique-identifier analysis — every field that could identify a ticket besides `ticket_id`

Checked directly against the model file, every migration touching `tickets`, and a repo-wide grep for `ticket_number|claim_number|patient_id|account_number|invoice_number|authorization_number|reference_number|case_number|external_id` (zero matches anywhere in `unified-backend`) — this is a complete accounting, not a sample.

| Candidate identifier | Status |
|---|---|
| **Primary key** — `ticket_id` (UUID, `default=uuid.uuid4`) | [STORED] — the only real identifier this table has |
| **Ticket number** (human-readable, sequential) | [NOT AVAILABLE] — no such column, no sequence/counter. Confirmed elsewhere in this same codebase's own comments (`open_email_service.py`): "no human-readable ticket number to parse from a subject line — everything is a UUID." Every reference to a ticket anywhere in the system (URLs, audit logs, notifications' `link` field, API responses) is the raw `ticket_id` UUID. |
| **Claim number** | [NOT AVAILABLE] as a column. May appear as free text inside a linked `Interaction.payload.body`/`.html_body` (e.g. "Claim #48213") — unstructured message content, not indexed, not queryable, not reliably present. |
| **Patient ID** | [NOT AVAILABLE] — no patient entity exists anywhere in this schema (see §12.7: "the customer" is the Client company, never an individual). At most, free text inside an interaction body. |
| **Account number** | [NOT AVAILABLE] on `Ticket`. The closest real thing is `client_company_id` (FK → `clients.client_id`) — identifies the client *company*, not a billing/account number, and it's a UUID FK, not a business-facing number. |
| **Invoice number** | [NOT AVAILABLE] — no invoicing concept exists in this schema at all. |
| **Authorization number** (prior-auth #) | [NOT AVAILABLE] — same as claim number: at most, free text in a message body. |
| **`title`** | [STORED], but explicitly **not unique** — no `UniqueConstraint`/`unique=True` on this column (confirmed by reading the model directly); two tickets can share an identical title. GIN-trigram-indexed for search, not identity. |
| **`custom_fields`** (JSONB) | [STORED] as a column, but confirmed **empty on every ticket by construction**, not merely in a sample checked: the only real write path (`InboxTicketService.create_ticket_from_interaction`) writes `custom_fields={}` explicitly, and no other service-layer write site sets it to anything else. This is the one column shaped like it could hold a claim/account/invoice number without a migration — but nothing does today. |

**Any unique constraints (besides the PK)**: none on `tickets` itself. One adjacent fact worth not confusing with a "second identifier": `resolution_slas.ticket_id` and `first_response_slas.interaction_id` are each unique (true 1:1 relationships) — but that's the same `ticket_id`/`interaction_id` UUID re-enforced as unique on a *different* table, not an alternate way to identify a ticket.

**Database indexes**: see "Existing indexes" just above — all six are query-performance indexes (equality/sort filters, a partial pool-view filter, a trigram search index), **none unique**.

**Implication for the recommendation service**: none of the five RCM business identifiers you'd naturally want for exact-match candidate retrieval (claim/patient/account/invoice/authorization number) exist as queryable fields anywhere in production today. If matching on one of these is required, it is new work — either a schema addition (a real column, or a parsed-out `custom_fields`/interaction-payload key) or a text-extraction step over `Interaction.payload.body`, which is unstructured and not currently parsed by any pipeline in this codebase. Do not assume any of the five can be read directly; only `ticket_id` and (unreliably, as free text) `title`/interaction body content exist to key off today.

**Business meaning**: the unit of work assignment, SLA measurement, and (implicitly) recommendation target/candidate — a recommendation feature that suggests "attach this new email to an existing ticket" is choosing among rows of this table.

**Lifecycle**: `OPEN → IN_PROGRESS → PENDING → WAITING_FOR_CLIENT → RESOLVED → CLOSED` (not strictly linear — a ticket can revisit several of these before closing). Created only via `POST /tickets/from-interaction`. Terminal at `CLOSED`, reachable back to `OPEN` only via the dedicated Reopen action. See §12.7 for the full lifecycle narrative including why `RESOLVED` is not terminal.

**Fields that look like ticket columns but are computed at read time, never stored** — do not model these as real columns under any circumstance: `is_escalated`, `escalation_level`, `escalation_status`, `escalation_ack_due_at`, `is_escalation_owner`, `escalation_pending_acceptance`, `resolution_sla_tier`, `client_name`, `client_company_name`, `agent_name`, `created_by_name`, `closed_by_name`, `related_tickets`. Each is marked [DERIVED] below with its exact source.

**Existing APIs** (`unified-backend/app/ticketing/api/ticket.py`, all under `/tickets`, tag `Tickets`):

| Method | Path | Purpose |
|---|---|---|
| POST | `/tickets/from-interaction` | The one real ticket-creation path |
| POST | `/tickets/{ticket_id}/attach-interaction` | Attach a pending interaction to an existing ticket |
| GET | `/tickets` | List (paginated, filterable — see below) |
| GET | `/tickets/{ticket_id}` | Full detail (`TicketResponse`) |
| PATCH | `/tickets/{ticket_id}` | Generic update |
| POST | `/tickets/{ticket_id}/status` | Status change (explicitly rejects `new_status == CLOSED` — Close is its own endpoint) |
| POST | `/tickets/{ticket_id}/priority` | Priority change (`LOW/MEDIUM/HIGH` only from this endpoint) |
| POST | `/tickets/{ticket_id}/claim` | Claim from the shared pool |
| POST | `/tickets/{ticket_id}/transfer` | Reassign to another agent |
| POST | `/tickets/{ticket_id}/close`, `/tickets/{ticket_id}/reopen` | Close / Reopen |
| POST / DELETE | `/tickets/{ticket_id}/related`, `/tickets/{ticket_id}/related/{related_ticket_id}` | Related-Tickets link management |
| GET | `/tickets/view-counts`, `/tickets/dashboard-stats`, `/tickets/sla-overview-counts` | Aggregate/summary endpoints |
| GET | `/tickets/audit-logs`, `/tickets/{ticket_id}/audit-logs` | Audit trail (batched-all vs. per-ticket) |
| POST | `/tickets/{ticket_id}/edit-access/request`, `/{request_id}/approve`, `/{request_id}/reject`; GET `/tickets/{ticket_id}/edit-access` | Edit-access request workflow |

**`GET /tickets` query parameters** (exact, from the route signature): `limit` (1–200), `offset`, `status` (aliases `ticket_status`), `priority`, `ticket_type`, `view` (`pool|mine|all|escalated`), `search`, `date_from`, `date_to`, `sort_by` (`created_at|updated_at|title`), `sort_dir` (`asc|desc`). Returns `X-Total-Count` header when `limit` is supplied. `view=mine` resolves against the caller's own id server-side (never client-supplied). Visibility scoping (Account Manager → own clients; Team Lead/Staff → own category; Site Lead/Super Admin → everything) is applied unconditionally underneath whatever filters are passed — a recommendation service authenticating as a given role will only ever see what that role is allowed to see, same as the human UI.

**Direct human input at creation** (via `TicketFromInteractionCreate`): `interaction_id` (required — the founding interaction), `title` (1–255 chars), `ticket_type` (1–100 chars, free string), `current_priority` (optional, defaults MEDIUM, **CRITICAL is not offered as a choice**), `agent_id` (optional, server-revalidated against the caller's own assignment hierarchy — never trusted as submitted).

**System-derived fields, never human input**: `ticket_id`, `version`, `created_at`, `updated_at`, `current_status` (always starts `OPEN`), `created_by` (the acting agent, not typed), `client_company_id` (copied from the founding interaction's own `client_id`), `client_id` (permanently NULL), `closed_at`/`closed_by`, `current_priority` becoming `CRITICAL` (escalation workflow only — see §10), `custom_fields` (always `{}`).

**Fields useful for recommendation and their status**:
| Field | Status |
|---|---|
| `title` | [STORED] — essential retrieval signal |
| `ticket_type`, `current_priority`, `current_status`, `client_company_id`, `agent_id`, `created_at`/`closed_at`/`updated_at` | [STORED] — filter/metadata |
| `client_name`, `client_company_name`, `agent_name`, `created_by_name`, `closed_by_name` | [DERIVED] — resolved via a join to `users`/`clients` inside `TicketService`/`TicketRepository`, never persisted on the row |
| `is_escalated` | [DERIVED] — `EXISTS` a non-CLOSED `ticket_escalations` row for this `ticket_id` (LEFT JOIN in `TicketRepository.list_visible_page`) |
| `escalation_level`, `escalation_status`, `escalation_ack_due_at` | [DERIVED] — same LEFT JOIN, the matching `ticket_escalations` columns |
| `is_escalation_owner` | [DERIVED] — `ticket_escalations.owner_ids @> [viewer's own user_id]` (JSONB containment), **per-viewer** — not a global property of the ticket |
| `escalation_pending_acceptance` | [DERIVED] — true while `is_escalated` and no `EscalationHandlingSLA` row exists yet for the active escalation (acknowledged-but-not-accepted state) |
| `resolution_sla_tier` | [DERIVED] — a `healthy/at_risk/breached/escalated` classification computed from a LEFT JOIN against `resolution_slas`/`sla_policies`, using the same elapsed-fraction formula the SLA sweep uses (see §7) |
| `related_tickets` | [DERIVED] — populated only on `GET /tickets/{id}` (never the list endpoint) by joining `ticket_relations`; see §11 for why this must not be repurposed as the recommendation output store |
| An `IssueType` distinct from `ticket_type`/category | [NOT AVAILABLE] — confirmed no such concept exists anywhere in the codebase; category is the only classification axis |
| Individual patient identity/reference on a ticket | [NOT AVAILABLE] — if present at all, it is buried inside a linked interaction's free-text `payload.body`, never a modeled field |

---

## 4. Entity: User

**Purpose**: the single cross-cutting identity record for every internal team member — authentication, RBAC role, work-specialization category, org-chart position, and self-service profile data. Shared by both the RBAC and Ticketing domains (one physical table, one FK target for both).

**Table name**: `users` (chain: `alembic_rbac`). Model: `shared_models/shared_models/models/user.py` — the one real copy; never edit a service's own copy, there isn't one.

| Column | Type | Nullable | Default | Status |
|---|---|---|---|---|
| `user_id` | UUID | No | `uuid4()` | [STORED] — PK |
| `name` | String(100) | No | — | [STORED] |
| `email` | String(255) | No | — | [STORED] — unique, indexed |
| `password_hash` | String(255) | No | — | [STORED] — **never exposed by any API response schema** (confirmed: absent from `UserResponse`) |
| `role_id` | UUID | No | — | [STORED] — FK → `roles.role_id` |
| `manager_id` | UUID | Yes | — | [STORED] — FK (self) → `users.user_id` |
| `teamlead_id` | UUID | Yes | — | [STORED] — FK (self) → `users.user_id` |
| `category_id` | UUID | Yes | — | [STORED] — FK → `categories.category_id` |
| `is_active` | Boolean | No | `True` | [STORED] |
| `permission_version` | Integer | No | `1` | [STORED] — cache-busting counter; **not exposed by `UserResponse`** |
| `date_of_birth` | Date | Yes | — | [STORED] |
| `alternate_email` | String(255) | Yes | — | [STORED] |
| `phone_number` | String(30) | Yes | — | [STORED] |
| `office_location` | String(255) | Yes | — | [STORED] |
| `department` | String(100) | Yes | — | [STORED] — display-only, independent of `category_id` (one-time backfilled from category name; not kept in sync afterward) |
| `team` | String(100) | Yes | — | [STORED] — display-only, no edit surface writes it |
| `language` | String(10) | Yes | `'en'` | [STORED] |
| `date_format` | String(20) | Yes | `'MM/DD/YYYY'` | [STORED] |
| `time_format` | String(10) | Yes | `'12h'` | [STORED] |
| `time_zone` | String(50) | Yes | — | [STORED] |
| `default_dashboard` | String(50) | Yes | `'Dashboard'` | [STORED] |
| `created_at` / `updated_at` | DateTime(tz) | No | `now()` | [STORED] |

**Required fields (NOT NULL)**: `user_id`, `name`, `email`, `password_hash`, `role_id`, `is_active`, `permission_version`, `created_at`, `updated_at`.

**Optional fields (nullable)**: `manager_id`, `teamlead_id`, `category_id`, and all ten profile columns (`date_of_birth` through `default_dashboard`).

**Relationships**: `role_id` → `roles.role_id`; `category_id` → `categories.category_id`; `manager_id`/`teamlead_id` → `users.user_id` (self, no rank column — hierarchy is application-code-only). No `ondelete` on any of these four FKs (deliberate, app-enforced). Referenced by nearly every other table in the schema (`tickets.agent_id`/`created_by`/`closed_by`, `clients.account_manager_id`, `interactions.performed_by`/`removed_by`/`claimed_by`, `notifications.user_id`, `ticket_escalations.acknowledged_by`/`triggered_by_user_id`, etc.).

**Constraints**: `email` globally unique.

**Existing indexes**: `email` (implied by unique constraint, plus explicitly indexed per the model).

**Business meaning**: represents an internal agent/supervisor/admin — never a client-side person. Role (`role_id`) plus category (`category_id`) determine what work this user can see/do; `manager_id`/`teamlead_id` determine real reporting lines (a separate concept from the Reporting Manager mapping and from ticket-assignment eligibility — three genuinely independent relationships, see the root `CLAUDE.md`'s "Organization Structure" section if the recommendation service's future workload-ranking idea needs this distinction).

**Lifecycle — corrected in this re-verification pass**: `is_active=False` (via `PATCH /api/v1/users/{id}/deactivate`) is the *conventional* retirement mechanism, but it is **not the only one**: `DELETE /api/v1/users/{user_id}` performs a genuine, unconditional hard SQL `DELETE` when `user_id` resolves to a real `users` row — confirmed directly in `UserRepository.delete` (`unified-backend/app/rbac/repositories/user_repository.py`): `await self.db.delete(user); await self.db.flush()`, no soft-delete guard anywhere in that path. The previous text's "never hard-deleted in the normal flow" claim was wrong and is corrected here. Practical caveat (not independently tested in this pass): every FK into `users.user_id` elsewhere in the schema (`tickets.agent_id`/`created_by`/`closed_by`, `interactions.performed_by`, `ticket_escalations.acknowledged_by`, etc.) is declared with **no `ondelete`** — Postgres's default is to reject the delete with a foreign-key-violation error if any referencing row exists, so in practice this endpoint likely only succeeds against a user with zero historical references; it is not a documented "safe cascade," just an unrestricted `DELETE` statement. `permission_version` bumps on any RBAC-relevant change (role/category/manager/teamlead reassignment, activate/deactivate, permission override grant/revoke, or the user's role's own permission set changing) — this is an internal cache-invalidation signal, not itself business-meaningful data, and is not exposed via any response schema.

**Existing APIs** (`unified-backend/app/rbac/api/v1/users.py`, mounted at `/api/v1/users`):

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/users` | Create |
| GET | `/api/v1/users` | List — **merges in `clients` rows, see §4.1** |
| GET | `/api/v1/users/{user_id}` | Fetch one — **`user_id` may resolve to a `clients.client_id` instead, see §4.1** |
| PUT | `/api/v1/users/{user_id}` | Update — same dual-resolution as GET |
| DELETE | `/api/v1/users/{user_id}` | **Confirmed hard delete for a real user** (see Lifecycle above); soft-deactivates the underlying client instead if `user_id` resolves to one (§4.1) |
| PATCH | `/api/v1/users/{user_id}/activate`, `/{user_id}/deactivate` | Activate/deactivate — same dual-resolution |
| GET | `/api/v1/users/me/organization-chart` | Dynamic org-chart for the caller's own profile (see §11's Organization Structure note) |

**Response schema exposure (`UserResponse`, `unified-backend/app/rbac/schemas/user.py`)** — confirmed exact field list: `user_id`, `name`, `email`, `role_id`, `manager_id`, `teamlead_id`, `category_id`, `is_active`, all ten profile fields, `created_at`, `updated_at`. **Confirmed absent from every response schema**: `password_hash` (correctly, for security), `permission_version` (a real column with no API exposure at all today).

### 4.1 Merged identity — `/api/v1/users` is not purely the `users` table (new finding, this re-verification pass)

**This is a load-bearing fact missing from the original contract, confirmed directly against `unified-backend/app/rbac/services/user_service.py`.** Every one of the five id-based/list operations above resolves against **either** the real `users` table **or** the `clients` table, transparently, via `UserService._resolve_user_or_client(user_id)`: it looks up `user_id` against `users` first, and if nothing matches, falls back to looking it up against `clients.client_id`. This is not a coincidental overlap — it is how the `Client` RBAC role (§11.2's renamed-from-`Viewer` role) is implemented: a `clients` company row is presented as a pseudo-user via `_client_to_user_response`, which maps `client.client_id → user_id`, `client.name → name`, `client.inbox_email → email`, `role = "Client"`, and leaves every category/manager/teamlead/profile field null (a Client company has none of those).

**Concretely, what this means for each operation**:
- **`GET /api/v1/users` (list)** — `UserService.list_users`: fetches real `users` rows (paginated, `OFFSET`/`LIMIT` applied in the query) via the normal path, **then**, unless a `category_id` filter was supplied (clients never have one, so nothing to merge in that case), separately fetches **every** `clients` row via `client_repository.list_all()`, filters it in-process by the same `search` term if supplied, converts each to a pseudo-user dict, and appends the whole batch after the real users. The returned `total` is `(paginated users total) + len(client_rows)`. **Confirmed pagination inconsistency, not previously documented**: the client rows are appended *unpaginated* — every matching client appears on every page of this endpoint, not just the page whose offset window it would fall into if it were a real, uniformly-paginated row. A recommendation service paging through this endpoint expecting a stable, non-overlapping page-by-page traversal will see the same set of client-shaped rows repeated on every page.
- **`GET`/`PUT`/`PATCH .../activate`/`PATCH .../deactivate`/`DELETE` by id** — each calls `_resolve_user_or_client` first; if the id matches a `clients.client_id` instead of a real `users.user_id`, the operation is redirected onto the `clients` table (e.g. `DELETE` becomes `client.is_active = False`, never a real delete of the client row; `PATCH .../deactivate` likewise; `PUT` routes through `_update_client_user`, which only ever touches `name`/`inbox_email`/`account_manager_id`/`is_active` — role/category/manager/teamlead fields are meaningless for a client and are not settable through this path).

**Why this matters for the recommendation service**: a `user_id` obtained from `GET /api/v1/users` (or `GET /api/v1/users/{id}`) is **not guaranteed to exist in the real `users` table at all** — if its `role` field reads `"Client"`, that id is actually a `clients.client_id`, and looking it up against any FK that points at `users.user_id` (e.g. treating it as a possible `tickets.agent_id` or `interactions.performed_by`) will never match, because it was never a real user row to begin with. Filter on `role != "Client"` (or simply prefer `GET /clients` for anything client-domain) before assuming an id from this endpoint identifies an internal agent.

**Fields useful for recommendation (e.g. a future workload-based assignment feature) and their status**:
| Field | Status |
|---|---|
| `role_id`, `category_id`, `manager_id`, `teamlead_id`, `is_active` | [STORED] |
| This user's open-ticket count, weighted by priority | [NOT AVAILABLE] as a stored field — [DERIVED] is possible via a `GROUP BY agent_id` query over `tickets`, but no such aggregate is computed or exposed by any existing endpoint today (this is exactly the not-yet-built "Workload-Based Assignment" feature described in the root `CLAUDE.md` — design-only, confirmed unbuilt as of 2026-07-27) |
| This user's real-time online/availability/shift status | [NOT AVAILABLE] — confirmed no such table or column exists in the current schema at all |
| Historical average resolution speed per agent/category | [NOT AVAILABLE] — would require a new rolling-window aggregate; nothing today computes or stores this |

---

## 5. Entity: Attachment

**Purpose**: a file uploaded against a specific interaction (email, reply, or note) — never against a ticket directly.

**Table name**: `attachments` (chain: `alembic_ticketing`). Model: `unified-backend/app/ticketing/models/attachment.py`.

| Column | Type | Nullable | Default | Status |
|---|---|---|---|---|
| `attachment_id` | UUID | No | `uuid4()` | [STORED] — PK |
| `interaction_id` | UUID | No | — | [STORED] — FK → `interactions`. **Confirmed: no index at all on this column** (verified against the initial migration — no `create_index` call for `attachments` exists anywhere in the ticketing chain) |
| `filename` | String(255) | No | — | [STORED] |
| `mime_type` | String(100) | Yes | — | [STORED] |
| `size_bytes` | BigInteger | Yes | — | [STORED] |
| `storage_key` | Text | No | — | [STORED] — object-storage key, not a public URL |
| `bucket_name` | String(255) | Yes | — | [STORED] |
| `scan_status` | String(20) | No | `"pending"` | [STORED] — **confirmed stub: no code path anywhere reads or updates this column beyond its default write**; there is no real malware/virus scanning despite the name |
| `uploaded_at` | DateTime(tz) | No | `now()` | [STORED] |
| `created_at` / `updated_at` | DateTime(tz) | Yes | `now()` | [STORED] |

**Required fields (NOT NULL)**: `attachment_id`, `interaction_id`, `filename`, `storage_key`, `scan_status`, `uploaded_at`.

**Optional fields (nullable)**: `mime_type`, `size_bytes`, `bucket_name`, `created_at`, `updated_at`.

**Relationships**: `interaction_id` → `interactions.interaction_id`. **There is no direct FK to `tickets`** — to find a ticket's attachments, join `attachments.interaction_id → interactions.interaction_id → interactions.ticket_id`.

**Constraints**: none beyond the FK and NOT NULL columns above (no unique constraint on `storage_key` or `filename`).

**Existing indexes**: none beyond the implicit PK index. Confirmed by direct inspection of the initial migration — no `create_index` targeting `attachments` exists in the ticketing migration chain.

**Business meaning**: file evidence attached to a specific message in a thread (a corrected superbill, an EOB scan, etc.) — operationally important, but the file content itself is opaque to this system (no OCR/content-extraction pipeline exists).

**Validation (app-layer, not DB-layer)**: max 10 files per upload call, max 25MB per file, an explicit allow-listed extension set (`pdf, doc, docx, xls, xlsx, csv, png, jpg/jpeg, gif, txt, zip`) each cross-checked against an allow-listed MIME type — a mismatched declared content-type is rejected. None of this is a database CHECK constraint; it is enforced entirely in `AttachmentService`.

**Lifecycle**: created on upload (tied to an interaction, or to an in-progress draft — reassigned to the real outbound interaction on send). Deleted via the dedicated archive/delete action (gated by a separate permission from upload); orphaned draft attachments are cleaned up (storage object + DB row) if the draft itself is discarded.

**Existing APIs** (`unified-backend/app/ticketing/api/attachment.py`, mounted at `/attachments`, plus upload endpoints living on the owning resource):

| Method | Path | Purpose |
|---|---|---|
| GET | `/attachments/{attachment_id}` | Metadata only (`AttachmentMetadata`) |
| GET | `/attachments/{attachment_id}/download` | 307 redirect to a short-lived presigned URL — file bytes never pass through this backend's own response body |
| DELETE | `/attachments/{attachment_id}` | Delete |
| POST | `/tickets/{ticket_id}/attachments` | Upload against a ticketed thread |
| POST | `/inbox/{interaction_id}/draft/attachments` | Upload against an in-progress draft |

**`AttachmentResponse` schema exposure** (`unified-backend/app/ticketing/schemas/attachment.py`) — confirmed exact fields: `attachment_id`, `interaction_id`, `filename`, `mime_type`, `size_bytes`, `storage_key`, `bucket_name`, `scan_status`, `uploaded_at`, `created_at`, `updated_at`. Note `storage_key` is exposed in this raw response shape (internal key, not a usable URL on its own) — the presigned, directly-usable download link is a separate field (`download_url`) only present on the lighter-weight `AttachmentMetadata` shape embedded inside interaction/upload responses, not on `AttachmentResponse` itself.

**Fields useful for recommendation and their status**:
| Field | Status |
|---|---|
| `filename`, `mime_type`, `size_bytes`, `uploaded_at` | [STORED] |
| Which ticket an attachment belongs to | [DERIVED] — via the `interaction_id → interactions.ticket_id` join described above |
| Extracted text/content of the attachment itself | [NOT AVAILABLE] — no OCR or document-parsing pipeline exists |
| Real malware/virus scan result | [NOT AVAILABLE] — `scan_status` is a confirmed inert stub |

---

## 6. Entity: "TicketAttachment"

**Status: does not exist in production as a distinct entity.** There is no `ticket_attachments` table, model, schema, or API anywhere in this codebase. An attachment is keyed **only** on `interaction_id` (see §5) — never on `ticket_id` directly.

If the recommendation service's design assumes a `TicketAttachment` join-table shape (ticket ↔ attachment, direct), that assumption does not match production. The correct way to enumerate "this ticket's attachments" is:

```
attachments.interaction_id = interactions.interaction_id
  AND interactions.ticket_id = <the ticket in question>
```

This is exactly how production's own code finds a ticket's attachments (there is no shortcut/denormalized column anywhere that avoids this join) — `GET /tickets/{ticket_id}/interactions` returns each interaction with its own `attachments: list[AttachmentMetadata]` already embedded (via `InteractionResponse.attachments`), so a consumer does not need to perform the join itself if it's willing to fetch the full interaction list rather than attachments alone.

**[NOT AVAILABLE]**: a direct `GET /tickets/{ticket_id}/attachments` endpoint that returns only attachments (flattened, without their owning interactions) does not exist.

---

## 7. Entity: SLA (five related tables, all chain `alembic_ticketing`)

Two independent per-ticket/per-interaction clocks exist, plus a global policy table, plus two supporting tables. None of these five tables should be treated as one entity for schema purposes — they are related but distinct.

### 7.1 `sla_policies` — the global, priority-keyed configuration lookup

*Model: `unified-backend/app/ticketing/models/sla_policy.py`. One row per `TicketPriority` value (4 rows: LOW/MEDIUM/HIGH/CRITICAL). No FKs — a standalone lookup, seeded, but editable live via an admin UI.*

| Column | Type | Nullable | Default | Status |
|---|---|---|---|---|
| `policy_id` | UUID | No | `uuid4()` | [STORED] — PK |
| `priority` | enum `ticket_priority_enum` | No | — | [STORED] — unique |
| `first_response_target_minutes` | Integer | No | — | [STORED] |
| `resolution_target_minutes` | Integer | No | — | [STORED] |
| `escalation_ack_target_minutes` | Integer | No | — | [STORED] |
| `handling_sla_percentage` | Float | No | `25.0` | [STORED] — **deprecated, unread by current code**; kept only for schema compatibility |
| `handling_stage_percentages` | JSONB (list of float) | No | — (must be supplied) | [STORED] — ordered per-stage %, e.g. `[25.0, 12.5, 6.25]` |
| `warning_1_percentage` / `warning_2_percentage` | Float | No | `50.0` / `80.0` | [STORED] |
| `is_active` | Boolean | No | `True` | [STORED] |
| `created_at` / `updated_at` | DateTime(tz) | No | `now()` | [STORED] |

**Constraints**: `priority` unique (exactly one row per priority tier).

**⚠ Live-data caveat, not re-verifiable from source code**: per prior project notes, the MEDIUM row was live-PATCHed via the admin endpoint for a demo (values temporarily lowered from their migrated `20/20`-minute-style values). **Do not trust any cached/prior snapshot of this table's MEDIUM row as current** — always read `GET /sla/policies` live rather than assuming the migrated defaults are what's currently active.

**Existing APIs**: `GET /sla/policies` (open to any authenticated user), `PATCH /sla/policies/{policy_id}` (Site Lead/Super Admin only, `sla:manage_policies`). File: `unified-backend/app/ticketing/api/sla.py`.

### 7.2 `resolution_slas` — 1:1 clock per Ticket

*Model: `unified-backend/app/ticketing/models/resolution_sla.py`.*

| Column | Type | Nullable | Default | Status |
|---|---|---|---|---|
| `resolution_sla_id` | UUID | No | `uuid4()` | [STORED] — PK |
| `ticket_id` | UUID | No | — | [STORED] — FK → `tickets`, **unique** (true 1:1), indexed |
| `client_id` | UUID | Yes | — | [STORED] — FK → `clients`, denormalized |
| `priority` | enum `ticket_priority_enum` | No | — | [STORED] — snapshot at creation; **stays at the original priority through escalation, never becomes CRITICAL on this row** even though `Ticket.current_priority` does |
| `status` | enum `sla_clock_status_enum` | No | `RUNNING` | [STORED] — `PENDING/RUNNING/PAUSED/COMPLETED`, indexed |
| `started_at` / `due_at` | DateTime(tz) | No | — | [STORED] — `due_at` indexed |
| `active_target_minutes` | Integer | No | — | [STORED] — the real, current target the sweep's math uses (not re-derived from priority after a handling-stage restart) |
| `paused_at` | DateTime(tz) | Yes | — | [STORED] — non-null iff currently `PAUSED` |
| `total_paused_seconds` | Integer | No | `0` | [STORED] |
| `completed_at` | DateTime(tz) | Yes | — | [STORED] |
| `escalation_cycle` | Integer | No | `0` | [STORED] — bumped on each handling-stage restart |
| `created_at` / `updated_at` | DateTime(tz) | No | `now()` | [STORED] |

**Constraints**: `ticket_id` unique. **Existing indexes**: `client_id`, `due_at`, `status`, composite `(status, due_at)` (the sweep's primary query), `ticket_id` (unique). All confirmed in `317e5570c7df_add_sla_tables.py`.

**Elapsed-fraction formula [DERIVED]** (used everywhere production itself computes SLA risk — a recommendation service wanting the same "how close to breach" signal should use this exact formula, not invent its own): `fraction = 1.0 - (due_at - now).total_seconds() / (active_target_minutes * 60)`. This formula is pause/resume/reshift-consistent by construction since it only reads `due_at` and the target, never `started_at` or pause history directly.

### 7.3 `first_response_slas` — 1:1 clock per thread-root Interaction (not the ticket)

*Model: `unified-backend/app/ticketing/models/first_response_sla.py`. No `updated_at` column (asymmetric with `resolution_slas`).*

| Column | Type | Nullable | Default | Status |
|---|---|---|---|---|
| `first_response_sla_id` | UUID | No | `uuid4()` | [STORED] — PK |
| `interaction_id` | UUID | No | — | [STORED] — FK → `interactions`, **unique**, indexed |
| `client_id` | UUID | Yes | — | [STORED] |
| `priority` | enum `ticket_priority_enum` | No | — | [STORED] — always defaults MEDIUM for pre-ticket items (no real priority exists yet) |
| `status` | enum `sla_clock_status_enum` | No | `PENDING` | [STORED] — only `PENDING`/`COMPLETED` used in practice |
| `started_at` / `due_at` | DateTime(tz) | No | — | [STORED] |
| `completed_at` | DateTime(tz) | Yes | — | [STORED] |
| `completion_reason` | String(30) | Yes | — | [STORED] — free string: `ARCHIVED / REPLIED / ATTACHED_TO_TICKET / TICKET_CREATED` |
| `resulting_ticket_id` | UUID | Yes | — | [STORED] — FK → `tickets`; set only for `TICKET_CREATED`/`ATTACHED_TO_TICKET` |
| `created_at` | DateTime(tz) | No | `now()` | [STORED] |

This clock never pauses and never restarts — a one-shot triage-speed measurement, completed exactly once.

### 7.4 `ticket_escalations` and 7.5 `escalation_handling_slas`

Covered in full in §10 (Escalation) below, since they are conceptually part of that entity, not the SLA-policy entity.

### 7.6 `sla_breach_notifications` — idempotency ledger, not itself a business entity

*Model: `unified-backend/app/ticketing/models/sla_breach_notification.py`. Polymorphic `clock_id` — no FK, since it can point at either `resolution_slas` or `first_response_slas`.*

| Column | Type | Nullable | Default | Status |
|---|---|---|---|---|
| `sla_breach_notification_id` | UUID | No | `uuid4()` | [STORED] — PK |
| `clock_type` | String(20) | No | — | [STORED] — `FIRST_RESPONSE` or `RESOLUTION` |
| `clock_id` | UUID | No | — | [STORED] — polymorphic, no FK |
| `threshold` | String(20) | No | — | [STORED] — `HALF_ELAPSED / AT_RISK / BREACHED / ESCALATED` |
| `cycle` | Integer | No | `0` | [STORED] — **known model-file bug**: `cycle` is defined twice in the same class body; the second (`server_default="0"`) silently wins. Treat as `NOT NULL DEFAULT 0` |
| `notified_at` | DateTime(tz) | No | `now()` | [STORED] |

**Constraints**: unique on `(clock_type, clock_id, threshold, cycle)` — the mechanism that guarantees a given threshold crossing is only ever notified once per cycle. This table exists purely so the periodic sweep doesn't re-notify every tick; a recommendation service has no reason to write to it and should treat it as read-only, if read at all.

**Existing APIs for the SLA family** (ticket-scoped, `unified-backend/app/ticketing/api/sla.py`, mounted under `/tickets`):

| Method | Path | Purpose |
|---|---|---|
| GET | `/tickets/{ticket_id}/sla` | Both clocks' current state (`TicketSLAResponse`: `first_response`, `resolution`, `escalation`, `escalation_handling_sla`) |
| POST | `/tickets/{ticket_id}/sla/pause`, `/sla/resume` | Manual override (supervisor-restricted) |
| POST | `/tickets/{ticket_id}/escalate` | Manually raise/advance escalation |

Plus the manual-trigger/shared-secret-protected sweep itself: `POST /internal/sla/sweep` (`unified-backend/app/ticketing/api/sla_internal.py`) — not intended for the recommendation service to call.

**Fields useful for recommendation and their status**:
| Field | Status |
|---|---|
| `resolution_slas.priority`, `.status`, `.due_at`, `.active_target_minutes` | [STORED] |
| "Is this ticket currently SLA at-risk/breached" | [DERIVED] via the elapsed-fraction formula above, or read directly via `GET /tickets/{id}/sla` |
| A numeric SLA-risk score suitable for ranking | [NOT AVAILABLE] as a stored field — the elapsed fraction is the closest real signal and is itself [DERIVED], not stored |

---

## 8. Entity: Notification

**Purpose**: an in-app (and, in parallel, real outbound email) notice of a business event to one specific user.

**Table name**: `notifications`. **Chain: `alembic_rbac`** — a genuinely non-obvious fact worth flagging explicitly: despite being triggered almost entirely by ticketing-domain events (mail arrival, SLA breach, escalation, assignment), this table's migration (`f3a7c9e1b5d2_add_notifications_table.py`) lives in the RBAC chain, added there deliberately because that chain's `include_object` filtering is denylist-style (new tables are picked up automatically) versus the ticketing chain's allowlist style. If searching for this table's migration history, look in `alembic_rbac/versions/`, not `alembic_ticketing/versions/`.

Model: `unified-backend/app/notifications/models.py`.

| Column | Type | Nullable | Default | Status |
|---|---|---|---|---|
| `notification_id` | UUID | No | `uuid4()` | [STORED] — PK |
| `user_id` | UUID | No | — | [STORED] — FK → `users.user_id` (no `ondelete`), indexed |
| `notification_type` | String(50) | No | — | [STORED] — **plain string, not an enum**, indexed. Live values in use: `MAIL_RECEIVED, CLIENT_REPLY, TICKET_ASSIGNED, PERMISSION_REQUESTED, PERMISSION_APPROVED, PERMISSION_REJECTED, PERMISSION_REVOKED, PERMISSION_GRANTED, EDIT_ACCESS_REQUESTED, EDIT_ACCESS_APPROVED, EDIT_ACCESS_REJECTED, SLA_HALF_ELAPSED, SLA_AT_RISK, SLA_BREACHED, SLA_ESCALATED, ESCALATION_CREATED, ESCALATION_ACKNOWLEDGED, ESCALATION_ADVANCED, ESCALATION_CLOSED, TICKET_STATUS_CHANGED, TICKET_PRIORITY_CHANGED, TICKET_RESOLVED, INTERNAL_NOTE_ADDED` |
| `title` | String(255) | No | — | [STORED] |
| `message` | Text | No | — | [STORED] |
| `link` | String(500) | Yes | — | [STORED] — a frontend route path (e.g. `/tickets/{id}`), **not a full URL** |
| `related_entity_type` | String(50) | Yes | — | [STORED] — free-form, not FK'd |
| `related_entity_id` | UUID | Yes | — | [STORED] — no FK |
| `is_read` | Boolean | No | `False` | [STORED] — indexed |
| `created_at` | DateTime(tz) | No | `now()` | [STORED] — indexed |

**Required fields (NOT NULL)**: `notification_id`, `user_id`, `notification_type`, `title`, `message`, `is_read`, `created_at`. **Optional fields**: `link`, `related_entity_type`, `related_entity_id`.

**Existing indexes** (confirmed, `f3a7c9e1b5d2_add_notifications_table.py`): `user_id`, `notification_type`, `is_read`, `created_at` — each individually indexed, no composite index on this table.

**Business meaning**: a real, visible byproduct of nearly every business action modeled elsewhere in this schema — never independently meaningful content on its own, always a pointer back to the triggering event (via `related_entity_type`/`related_entity_id`, though those are not FK-enforced).

**Lifecycle**: created exclusively by `NotificationService.notify()` — never any other write path. `is_read` flips `True` via the mark-read action; no code path was found that deletes a notification.

**Existing APIs** (`unified-backend/app/notifications/routes.py`, mounted at `/notifications`):

| Method | Path | Purpose |
|---|---|---|
| GET | `/notifications` | List (`NotificationListResponse`: `total`, `unread_count`, `items`) |
| GET | `/notifications/stream` | Server-Sent Events push — see below |
| POST | `/notifications/{notification_id}/read` | Mark one read |
| POST | `/notifications/read-all` | Mark all read |

**The SSE stream is a real, existing push mechanism — with real constraints a recommendation service must respect if it ever consumes it**: authenticated via a `?token=` query parameter (not a header — browsers' native `EventSource` can't set one), scoped to exactly one `user_id` per connection, in-memory/per-process only (no Redis, no cross-process fan-out — a second backend worker process would not see events published on the first). Event shape: `event: notification` / `data: {"notification": {...same shape as a GET /notifications item...}, "unread_count": N}`, plus a `: heartbeat` comment every 25 seconds. This is the **only** real-time push channel that exists in production today, and it delivers `Notification` rows only — not raw domain events (see §13 for why this matters for future event subscription).

**Fields useful for recommendation and their status**:
| Field | Status |
|---|---|
| `notification_type`, `title`, `message`, `link`, `created_at` | [STORED] |
| Which ticket/interaction a notification refers to | [DERIVED with a caveat] — `related_entity_id` is present but **not FK-enforced**, and `related_entity_type` is a free string; joining on it is only as reliable as the writer was careful, there is no database-level guarantee it resolves to a real row |
| A structured "what changed" payload beyond the human-readable `title`/`message` | [NOT AVAILABLE] — notifications carry pre-rendered display text, not the underlying old/new value diff (that lives in the audit log instead, see §9) |

---

## 9. Entity: TicketAuditLog (plus the separate, unrelated RBAC `audit_logs`)

**Two entirely separate, disjoint audit tables exist — never cross-referenced except conceptually.** Do not conflate them.

### 9.1 `ticket_audit_logs` — ticketing-domain, the one most relevant to recommendation

**Purpose**: the immutable, compliance-grade trail of every mutating action on a ticket/interaction/attachment/client/user **within the ticketing domain**.

**Table name**: `ticket_audit_logs` (chain: `alembic_ticketing`, added by `9b3e5f1a7c2d_add_ticket_audit_logs_table.py`; its actor column was originally named `changed_by` and renamed to `actor_id` by a later migration, `3f7c9a1e5b2d_add_actor_fields_to_ticket_audit_logs.py` — a real rename to know about if querying migration history directly). Model: `unified-backend/app/ticketing/models/audit_log.py`.

| Column | Type | Nullable | Default | Status |
|---|---|---|---|---|
| `audit_id` | UUID | No | `uuid4()` | [STORED] — PK |
| `entity_type` | enum `audit_entity_type_enum` | No | — | [STORED] — `TICKET / INTERACTION / ATTACHMENT / CLIENT / USER` |
| `entity_id` | UUID | No | — | [STORED] — polymorphic, no FK |
| `event_type` | enum `audit_event_type_enum` | No | — | [STORED] — 34 members, full list below |
| `actor_id` | UUID | Yes | — | [STORED] — FK → `users` |
| `actor_name` | String(255) | No | — | [STORED] — stored at write time, durable (survives the actor's own rename/deactivation) |
| `actor_role` | enum `audit_actor_role_enum` | No | — | [STORED] — `AGENT / CLIENT / SYSTEM` |
| `old_values` / `new_values` | JSONB | Yes | — | [STORED] |
| `ticket_id` | UUID | Yes | — | [STORED] — FK → `tickets`, denormalized at write time for fast per-ticket lookup |
| `created_at` | DateTime(tz) | No | `now()` | [STORED] |

**Existing indexes**: `(entity_type, entity_id, created_at DESC)`, `(actor_id, created_at DESC)`, `(event_type, created_at DESC)`, `(ticket_id, created_at DESC)` — all composite, confirmed across `9b3e5f1a7c2d_...`/`4f7a9c2e6b8d_add_dedicated_ticket_id_column_to_audit_logs.py`/`6a1d3f5b7c9e_add_audit_log_ticket_id_jsonb_index.py`.

**`event_type` full member list (34)**: `TICKET_CREATED, TICKET_UPDATED, TICKET_RESOLVED, STATUS_CHANGED, PRIORITY_CHANGED, AGENT_TRANSFERRED, TICKET_CLOSED, TICKET_REOPENED, INTERACTION_HIDDEN, ATTACHMENT_UPLOADED, NOTE_ADDED, REPLY_ADDED, EMAIL_RECEIVED, CLIENT_CREATED, INTERACTION_CLAIMED, INTERACTION_ARCHIVED, INTERACTION_SNOOZED, INTERACTION_UNSNOOZED, INTERACTION_TAGGED, INTERACTION_FOLDER_CHANGED, TICKET_RELATED, TICKET_UNRELATED, TICKET_CLAIMED, EDIT_ACCESS_REQUESTED, EDIT_ACCESS_APPROVED, EDIT_ACCESS_REJECTED, SLA_PAUSED, SLA_RESUMED, SLA_BREACH_DETECTED, SLA_ESCALATED, ESCALATION_CREATED, ESCALATION_ACKNOWLEDGED, ESCALATION_ADVANCED, ESCALATION_CLOSED`.

**Important content caveat**: reply/internal-note **bodies are never audited** — only the fact that a reply/note was added (`{ticket_id}` in `new_values`), never the message text. If the recommendation service needs message content history, it must come from `interactions`, not from this table.

**Business meaning**: the evidentiary "what changed and who did it" trail — the closest thing production has to a state-transition history usable for time-to-resolve / time-to-first-reply style features.

**Lifecycle**: append-only, write-once. No update or delete path exists for any row (`AuditLogService.log_event` is the sole writer, a stateless static method that never commits its own transaction — it rides the caller's).

**Existing APIs**: `GET /tickets/{ticket_id}/audit-logs` (per-ticket), `GET /tickets/audit-logs` (batched-all — see the root `CLAUDE.md`'s RBAC-compliance-audit note: this was deliberately reworked into a scoped-by-default view, not gated behind a single blanket permission, so different roles see different real slices rather than the page being blocked outright for non-privileged roles).

### 9.2 RBAC-native `audit_logs` — a distinct table, not relevant to ticket content

**Table name**: `audit_logs` (chain: `alembic_rbac`). Model: `unified-backend/app/rbac/models/audit_log.py`. Columns: `audit_log_id`, `user_id` (FK → `users`, `ondelete=SET NULL`), `action` (free string, e.g. `"auth.login"`), `entity_type` (free string, not the same enum as §9.1), `entity_id` (plain string, no FK), `old_value`/`new_value` (**plain `Text`, manually `json.dumps`-serialized — not JSONB**, unlike the ticketing table), `ip_address`, `user_agent`, `timestamp`. Active `action` values: `auth.login`, `auth.login_failed`, `auth.logout`, `auth.change_password`, `permission_request.create/approve/reject/revoke`, `permission_override.grant/revoke`, `role.create/update/delete/permissions_added/permissions_removed`, `user.create/update/role_changed/activate/deactivate/delete`. **No login/logout/permission event ever touches `ticket_audit_logs`** — the two tables are fully domain-separated. Existing APIs: `POST/GET /api/v1/audit-logs`, `GET /api/v1/audit-logs/{id}`, `GET /api/v1/audit-logs/user/{user_id}`, `DELETE /api/v1/audit-logs/{id}` (`unified-backend/app/rbac/api/v1/audit_logs.py`). This table has essentially no recommendation-relevant content — it's login/permission history, not ticket/conversation data.

---

## 10. Entity: Escalation

**Purpose**: an internal ownership hand-off chain that activates when a ticket's Resolution SLA breaches badly enough (or a supervisor manually triggers it) — layered **on top of, and never mutating,** `Ticket.current_status`/`current_priority`'s own semantics except for one deliberate, permanent priority bump (see below).

### 10.1 `ticket_escalations`

*Model: `unified-backend/app/ticketing/models/ticket_escalation.py`. At most one non-CLOSED row per ticket, enforced by a partial unique index.*

| Column | Type | Nullable | Default | Status |
|---|---|---|---|---|
| `escalation_id` | UUID | No | `uuid4()` | [STORED] — PK |
| `ticket_id` | UUID | No | — | [STORED] — FK → `tickets`, indexed |
| `resolution_sla_id` | UUID | Yes | — | [STORED] — FK → `resolution_slas`, read-only link |
| `level` | enum `ticket_escalation_level_enum` | No | — | [STORED] — `TEAM_LEAD / MANAGER / SITE_LEAD` |
| `status` | enum `ticket_escalation_status_enum` | No | `ACTIVE` | [STORED] — `ACTIVE / ACKNOWLEDGED / CLOSED`, indexed |
| `owner_ids` | JSONB (list of user_id strings) | No | `[]` | [STORED] — wholesale-replaced on advance, never appended to |
| `original_priority` | enum `ticket_priority_enum` | No | — | [STORED] — snapshot taken pre-CRITICAL-bump |
| `has_advanced_past_starting_level` | Boolean | No | `False` | [STORED] |
| `handling_stage` | Integer | No | `0` | [STORED] — count of completed accept→assign→breach cycles |
| `handling_stage_started_at` / `handling_stage_due_at` | DateTime(tz) | Yes | — | [STORED] — non-null iff a stage is currently running |
| `triggered_by` | String(20) | No | — | [STORED] — `MANUAL` or `AUTO_SLA_BREACH` (free string, not an enum) |
| `triggered_by_user_id` | UUID | Yes | — | [STORED] — FK → `users` |
| `created_at` / `level_started_at` | DateTime(tz) | No | `now()` | [STORED] |
| `ack_due_at` | DateTime(tz) | No | — | [STORED] — indexed |
| `acknowledged_at` / `acknowledged_by` | DateTime(tz) / UUID | Yes | — | [STORED] — `acknowledged_by` FK → `users` |
| `closed_at` / `closed_reason` | DateTime(tz) / String(30) | Yes | — | [STORED] — reason: `TICKET_RESOLVED` / `MANUALLY_CLOSED` |
| `updated_at` | DateTime(tz) | No | `now()`/onupdate | [STORED] |

**Existing indexes** (confirmed, `a7c9e1f3b5d6_add_ticket_escalations.py` plus a later handling-stage migration): `ticket_id`, `status`, `ack_due_at` individually; composite `(status, ack_due_at)`; partial index on `handling_stage_due_at WHERE NOT NULL`; **unique partial** `ix_ticket_escalations_one_active_per_ticket` on `ticket_id WHERE status != 'CLOSED'` — the hard invariant that guarantees at most one live escalation per ticket.

### 10.2 `escalation_handling_slas`

*Model: `unified-backend/app/ticketing/models/escalation_handling_sla.py`. A second, independent internal clock — as of a later redesign, this table is a dual-write mirror; the authoritative stage counter/reshift live on `ticket_escalations.handling_stage`/`resolution_slas` directly.*

| Column | Type | Nullable | Default | Status |
|---|---|---|---|---|
| `escalation_handling_sla_id` | UUID | No | `uuid4()` | [STORED] — PK |
| `escalation_id` | UUID | No | — | [STORED] — FK → `ticket_escalations`, indexed (non-unique — multiple rows per escalation allowed over time) |
| `ticket_id` | UUID | No | — | [STORED] — FK → `tickets`, indexed |
| `status` | enum `sla_clock_status_enum` | No | `RUNNING` | [STORED] — only `RUNNING`/`COMPLETED` used in practice |
| `target_seconds` | Integer | No | — | [STORED] |
| `started_at` / `due_at` | DateTime(tz) | No | — | [STORED] |
| `breached_at` / `completed_at` | DateTime(tz) | Yes | — | [STORED] |
| `created_at` | DateTime(tz) | No | `now()` | [STORED] |

**Constraints**: unique partial index on `escalation_id WHERE breached_at IS NULL AND completed_at IS NULL` — at most one "open" row per escalation at a time.

**Business meaning of the escalation entity as a whole**: a `TEAM_LEAD → MANAGER → SITE_LEAD` ownership chain, distinct from both `current_status` and the SLA clocks. **One permanent, deliberate side effect worth flagging for a recommendation feature that might use `current_priority` as a signal**: the moment a ticket's first escalation is created, `Ticket.current_priority` is force-set to `CRITICAL` and **never reverts** — not on acknowledgment, not on closing the escalation, not on resolving/closing the ticket. A recommendation feature treating `current_priority == CRITICAL` as "this ticket is currently in a hot state" would be wrong for a ticket that escalated once, long ago, and has since been calmly handled — `is_escalated`/`escalation_status` (both [DERIVED], see §3) are the more accurate live-state signals, not `current_priority` alone.

**Existing APIs**: `GET /tickets/{ticket_id}/sla` (returns `escalation`/`escalation_handling_sla` sub-objects — see §7's `TicketEscalationState`/`EscalationHandlingSLAState` schemas for exact fields, including `owner_ids`, `owner_names`, `overdue_seconds` [DERIVED, computed lazily at request time], `original_priority`), `POST /tickets/{ticket_id}/escalate`, `POST /tickets/{ticket_id}/escalation/acknowledge`, `POST /tickets/{ticket_id}/escalation/confirm-assignment`, `GET /tickets/{ticket_id}/escalation/acknowledge-candidates`. File: `unified-backend/app/ticketing/api/sla.py`.

**Fields useful for recommendation and their status**:
| Field | Status |
|---|---|
| `level`, `status`, `owner_ids`, `handling_stage`, timestamps | [STORED] |
| `owner_names` | [DERIVED] — resolved via a join to `users`, not persisted |
| `overdue_seconds` | [DERIVED] — computed lazily at request time from `ack_due_at` vs. now, same idiom as the SLA elapsed-fraction formula |
| A count of "how many times this ticket has ever escalated" (historical, not just the current chain) | [DERIVED, with effort] — not a stored counter anywhere; would require counting `ESCALATION_CREATED` rows in `ticket_audit_logs` for that `ticket_id`, since `ticket_escalations` itself only ever holds the current/most-recent chain state per ticket (old CLOSED rows are not deleted, so a `COUNT(*) WHERE ticket_id = ... ` against `ticket_escalations` directly would also work and is simpler) |

---

## 11. Lookup / reference tables

### 11.1 `categories` (chain `alembic_rbac`)

*Model: `shared_models/shared_models/models/category.py`. The one and only classification axis for a ticket.*

| Column | Type | Nullable | Status |
|---|---|---|---|
| `category_id` | UUID | No | [STORED] — PK |
| `category_name` | native enum `category_name_enum` | No | [STORED] — unique |

**7 fixed rows** (per prior verified seed-migration read; re-verify the exact UUIDs live via `GET /categories` before hardcoding them, since this document does not re-confirm UUID literals): `Eligibility, Patient Calling, AR, Payment Posting, PA, Charge Entry, Claims`. No timestamps on this table. **Read-only from the ticketing side** — ticketing never writes to this table, only reads it to populate the `ticket_type` dropdown.

**Critical integration fact, repeated from §3 because it is easy to miss**: `Ticket.ticket_type` (the field a ticket actually carries) is a **plain string with no FK to this table**. `GET /categories` / `GET /api/v1/categories` are the two APIs that expose this lookup (same table, two mount points — see §0).

### 11.2 `roles` (chain `alembic_rbac`)

Columns: `role_id` (UUID, PK), `name` (String(100), unique). **No `rank`/`level`/`description` column** — the hierarchy (Super Admin > Site Lead > Account Manager > Team Lead > Staff; the sixth role outside it) is implicit in application code only, never a stored value.

**Corrected in this re-verification pass**: six seeded role names, but **`Viewer` no longer exists** — confirmed via `unified-backend/scripts/rbac_seed/seed.py` and migration `alembic_rbac/versions/a8c0e2f4b6d9_rename_viewer_role_to_client.py`: the role was renamed **in place** (same `role_id`, same default permission grant — `user:view, role:view, permission:view`, unchanged) to **`Client`**. The current, correct roster is `Super Admin, Site Lead, Account Manager, Team Lead, Staff, Client`. This is not a cosmetic rename — the "Client" role now has a second, load-bearing purpose beyond the original "Viewer, not a ticket actor" framing: see §4's merged-identity mechanism, where this exact role is used to present `clients` table rows as pseudo-users. Any reference elsewhere (including this repo's own companion docs, `RCM_APPLICATION_KNOWLEDGE_BASE.md`/`ML_TICKETING_SCHEMA_REFERENCE.md`) to a "Viewer" role or `viewer@probeps.com`/`sophia.turner@probeps.com` as "Viewer"-role demo users is describing the pre-rename state — those same seeded users now hold the `Client` role instead, same emails, same `role_id`.

Existing APIs: `POST/GET/PUT/DELETE /api/v1/roles`, `GET/PUT /api/v1/roles/{role_id}/permissions`.

### 11.3 `permissions` / `role_permissions` (chain `alembic_rbac`)

`permissions`: `permission_id` (PK), `permission_name` (unique, e.g. `"ticket:create"`), `description`, `created_at`. `role_permissions`: pure join table, composite PK `(role_id, permission_id)`, both `ondelete="CASCADE"`, no extra columns. Existing APIs: `POST/GET/PUT/DELETE /api/v1/permissions`. Entirely an authorization concern — relevant to a recommendation service only as filtering context ("what can this authenticated caller see"), never as retrieval content.

### 11.4 `ticket_relations` — the closest existing analog to a recommendation output, and a naming trap to avoid

*Model: `unified-backend/app/ticketing/models/ticket_relation.py`. Chain `alembic_ticketing`.* Symmetric "Related Tickets" link — one relationship stored as two mirrored rows. **Composite PK** `(ticket_id, related_ticket_id)`, both columns FK → `tickets.ticket_id`. Plus `created_at`. No semantic weight beyond "a human agent manually said these two tickets are related" — **entirely manual today, no automated writer exists**. Existing APIs: `POST /tickets/{ticket_id}/related`, `DELETE /tickets/{ticket_id}/related/{related_ticket_id}`; surfaced read-only as `TicketResponse.related_tickets` (populated only on the single-ticket detail view, never the list view).

**Explicit warning, carried forward from this repo's own architecture-reconciliation notes**: if the recommendation service's design contemplates writing its own suggestions somewhere, **this table must not be silently repurposed as that output store**. It is a human-authored, sparse, symmetric link with no "suggested by AI" / "confidence score" / "accepted or rejected" concept on it at all — those columns are [NOT AVAILABLE] here and adding them would change what this table means to every existing caller. If a recommendation-logging table is ever built, it should be a new, separate table (see §14).

### 11.5 Full enum reference (all Postgres-native unless noted)

| Enum | Postgres type | Members |
|---|---|---|
| `TicketStatus` | `ticket_status_enum` | `OPEN, IN_PROGRESS, PENDING, WAITING_FOR_CLIENT, RESOLVED, CLOSED` |
| `TicketPriority` | `ticket_priority_enum` | `LOW, MEDIUM, HIGH, CRITICAL` (CRITICAL is escalation-only — see §10) |
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

`Interaction.interaction_type` is a plain string, **not** a Postgres enum (live values listed in §2). `Ticket.ticket_type` is likewise a plain string (§3).

**Retired values — must never appear as current/active**: enum labels `SLA_MANUALLY_PAUSED`/`SLA_MANUALLY_RESUMED` (renamed to `SLA_PAUSED`/`SLA_RESUMED`); `interaction_type` values `STATUS_CHANGE, PRIORITY_CHANGE, AGENT_TRANSFER, CLAIM, TICKET_CLOSED, TICKET_REOPENED, EDIT_ACCESS_REQUESTED, EDIT_ACCESS_APPROVED, EDIT_ACCESS_REJECTED` — **corrected in this pass: 9 values, not 7 (`TICKET_CLOSED`/`TICKET_REOPENED` were missing)** — no longer written as real `interactions` rows; synthesized from `ticket_audit_logs` at read time instead, never written fresh. See §2.1 for the full mechanism, the exact `AuditEventType` each maps from, and why these must not be treated as real, independently-queryable rows; permission names `ticket:bulk_reassign`, `ticket:configure_routing`, `ticket:edit_ticket`, `ticket:close`, `ticket:manage_attachments` (all split/renamed); `interactions.snoozed_until` (column dropped entirely).

---

## 12. Production workflows relevant to recommendation

### 12.1 Incoming email processing

1. **Transport**: Microsoft Graph delivers a `message` payload, mapped by `mail_mapping_service.py` into an internal `EmailRequest` — see the exact field-source table in §2. Live route: `POST /emails/incoming` (also `POST /api/mail/incoming` — a second, parallel mail-integration transport exists; both ultimately produce the same `Interaction` shape). A `POST /emails/dummy` route exists for local simulation without a real Graph connection.
2. **Duplicate check**: rejected outright if `message_id` was already processed.
3. **Client resolution**: sender or recipient address matched against `clients.inbox_email`. For the one shared Graph mailbox every real client now sends into, resolution is by `from_email` (sender) rather than `to_email`, since every client shares the same arrival address. Unmatched mail routes to Site Lead rather than being rejected.
4. **Thread match**: see §12.4 below — if matched onto an already-ticketed thread, the pipeline stops here; no new pool item, no ticket-creation step.
5. **`Interaction` row created**: `interaction_type="EMAIL"`, `direction=INBOUND`, `performed_by=NULL`, `ticket_id=NULL` (unless step 4 matched), `status=PENDING`.
6. **Side effects**: a genuinely new thread root starts its `FirstResponseSLA`; an `EMAIL_RECEIVED` audit row is written with `actor_role=CLIENT`.
7. Sits in the shared Mail/Inbox pool (`GET /inbox`) until an agent acts.

### 12.2 Interaction creation (general — covers reply/note/attachment/draft, not just inbound email)

`direction` is set explicitly per call site, never inferred: inbound email → `INBOUND`; agent reply/compose/draft → `OUTBOUND`; internal note → `INTERNAL`. A draft-in-progress is stored as an `OUTBOUND` row with `is_draft=True` (`payload.dispatch_status="DRAFT"`), not sent until an explicit Send action, which reuses the same send code path as a non-draft reply.

### 12.3 Ticket creation

The **only** real path: `POST /tickets/from-interaction` → `InboxTicketService.create_ticket_from_interaction`. Exact steps: build `TicketCreate` server-side (`client_company_id` copied from the founding interaction's own `client_id`, never re-typed; `created_by` = promoting agent; `client_id` left NULL; `custom_fields={}`) → every other interaction already filed under that same thread is moved onto the new ticket in one batch (`assign_thread_to_ticket`) → `TICKET_CREATED` audit row written → `FirstResponseSLA` completed (`reason="TICKET_CREATED"`) → `ResolutionSLA` started. `TicketService.create()` exists in code but is confirmed never called from any route — do not treat it as a real alternate creation path.

### 12.4 Thread detection (deterministic, non-ML — the existing prior art most relevant to a recommendation feature)

`conversation_id → in_reply_to_message_id → references`, first hit wins, recursively walked to the true root (`find_thread_root`). This is a **header/id-matching mechanism only** — it never inspects subject or body text for similarity. `OpenEmailService._recommend_ticket` (`unified-backend/app/ticketing/services/open_email_service.py`) is a second, related but distinct piece of prior art: a deterministic "suggest attaching to an existing ticket" heuristic used as a safety net for threads that should have auto-matched at intake but didn't — it explicitly does not do subject/content similarity either (there is no human-readable ticket number to parse from a subject line; every id is a UUID). **A recommendation feature targeting "this new, thread-unlinked email is semantically about an existing active ticket" is a strict superset of what either mechanism covers today** — neither is ML, and neither would conflict with a genuine similarity-based feature.

### 12.5 Attachment handling

Covered fully in §5 — belongs only to an Interaction, validated at the app layer (10 files/upload, 25MB/file, allow-listed extensions/MIME types), `scan_status` a confirmed inert stub.

### 12.6 Ticket lifecycle

Covered fully in §3's Lifecycle note and §10 for the escalation overlay. One fact worth restating here since it directly affects any recommendation candidate-pool decision: **`RESOLVED` does not stop the Resolution SLA clock — only `CLOSED` does**, and only a supervisor can close a ticket. This means a `RESOLVED` ticket is not, in this system's own terms, "done" — a follow-up email logically belongs there, not as a fresh duplicate, if a recommendation feature is choosing among ticket-status candidates for a match.

### 12.7 Customer identification

There is **no individual-person "Customer"/"Contact" entity** in this schema. The customer, for every purpose (ownership, visibility scoping, "same customer" disambiguation), is the **Client company** row (§1), resolved purely by matching an email address against `clients.inbox_email`. Any number of real people at that company can be the actual sender of a given message; their individual name/address is captured only as free text inside `Interaction.payload` (`from_name`/`from_email`), never as a separate queryable row. `GET /clients/{client_id}/contacts` derives a list of distinct sender addresses for a client by scanning that client's own interaction history at request time — it is not backed by a dedicated contacts table.

---

## 13. Events the recommendation service could subscribe to in the future

**Read this section's framing carefully before building against it.** Production has **no domain-event bus, no webhook mechanism, and no "subscribe to ticket/interaction changes" API for an external service today** — confirmed: the only real push channel that exists is `GET /notifications/stream` (§8), which delivers pre-rendered `Notification` rows to one specific authenticated `user_id`, in-process only, not raw domain events, and not designed for service-to-service integration. **[NOT AVAILABLE]**: any of the event names below as an actual subscribable API. Building one would be new work, not a hookup to something that already exists.

What follows instead is a mapping: for each event name the recommendation service is likely to care about, **where that event's real, current equivalent already fires inside production code** (an audit-log write, a notification trigger, or a direct state transition), and **exactly what data is genuinely available at that moment** today — so that if a real event-emission mechanism is built later (the natural extension point is `AuditLogService.log_event`, since every one of these already routes through it), the payload shape can be designed against real data rather than invented.

| Requested event | Real production trigger point today | Data genuinely available at that moment |
|---|---|---|
| **Interaction Created** (inbound email) | `EmailService`/`OpenEmailService` receive path → `Interaction` row insert + `EMAIL_RECEIVED` audit write | Full `Interaction` row (§2) including `payload` (subject/body/from/to/cc), `client_id` (if resolved), `conversation_id`/threading headers, `received_at`. `ticket_id` is NULL at this instant unless thread-matched. |
| **Interaction Created** (reply/note) | `InteractionService.add_reply`/`add_internal_note` → `Interaction` row insert + `REPLY_ADDED`/`NOTE_ADDED` audit write | Full `Interaction` row, `ticket_id` set, `performed_by` (the acting agent), `direction`. Body text is in `payload` but **is never itself written into the audit row** (§9) — only the fact that it happened. |
| **Interaction Updated** (tags/folder/hide/claim) | `InteractionService`'s respective methods → `INTERACTION_TAGGED`/`INTERACTION_FOLDER_CHANGED`/`INTERACTION_HIDDEN`/`INTERACTION_CLAIMED` audit writes | The specific changed field(s) in `new_values`/`old_values` (per that event's own write call — not every field on the row, only what that action actually changed), `actor_id`/`actor_name`. |
| **Ticket Created** | `InboxTicketService.create_ticket_from_interaction` → `TICKET_CREATED` audit write | Full new `Ticket` row (§3), the founding `interaction_id`, `created_by`. |
| **Ticket Updated** (generic field change) | `TicketService.update` → `TICKET_UPDATED` audit write | `old_values`/`new_values` diff of whichever fields the `PATCH /tickets/{id}` request actually changed. |
| **Ticket Status/Priority Changed** | `InteractionService.change_status`/`change_priority` → `STATUS_CHANGED`/`PRIORITY_CHANGED` audit writes, plus `TICKET_STATUS_CHANGED`/`TICKET_PRIORITY_CHANGED`/`TICKET_RESOLVED` notifications | Old and new enum value, `ticket_id`, actor. A `PRIORITY_CHANGED` row attributed to `ActorRole.SYSTEM`/"Escalation workflow" specifically marks the CRITICAL-bump case (§10) — distinguishable from a human-initiated change by `actor_role`. |
| **Reply Received** (client-side follow-up on a ticketed thread) | Same as "Interaction Created" (reply path) when `direction=INBOUND` and `ticket_id` is already set → also triggers a `CLIENT_REPLY` notification to the assigned agent + their Team Lead | Full `Interaction` row, plus the notification's own recipient-resolution logic (assigned agent's identity) if that signal is wanted rather than just the raw interaction. |
| **Attachment Added** | `AttachmentService.upload_attachment` → `Attachment` row insert + `ATTACHMENT_UPLOADED` audit write (metadata only — filename/mime_type/size_bytes; file content is never in the audit row) | Full `Attachment` row (§5), the owning `interaction_id` (and, by join, `ticket_id`). |
| **Ticket Closed / Reopened** | `TicketService.close`/`reopen` → `TICKET_CLOSED`/`TICKET_REOPENED` audit writes | `closed_at`/`closed_by` (on close), actor, `ticket_id`. |
| **Escalation Created / Acknowledged / Advanced / Closed** | `EscalationService`'s respective methods → `ESCALATION_CREATED`/`ESCALATION_ACKNOWLEDGED`/`ESCALATION_ADVANCED`/`ESCALATION_CLOSED` audit writes, plus matching notifications to the new level's owners | Full `TicketEscalation` row state at that instant (§10) — `level`, `owner_ids`, `triggered_by`, `ack_due_at`. Note `ESCALATION_ACKNOWLEDGED`/`ESCALATION_CLOSED` are defined notification-type constants with **no active `.notify()` call site today** — only their audit-log counterparts actually fire; if the recommendation service were to key off the notification stream specifically (rather than the audit log) for these two, it would see nothing. |
| **SLA Threshold Crossed** (half-elapsed / at-risk / breached / escalated, either clock) | `SLASweepService.run_sweep`'s per-tick threshold check → `SLA_BREACH_DETECTED`/`SLA_ESCALATED` audit writes, plus `SLA_HALF_ELAPSED`/`SLA_AT_RISK`/`SLA_BREACHED`/`SLA_ESCALATED` notifications, plus an `sla_breach_notifications` ledger row (§7.6) | Which clock (`FIRST_RESPONSE`/`RESOLUTION`), which threshold, the clock's own `due_at`/target at that instant. This is the one event family with a real idempotency guarantee (the ledger's unique constraint) — a given threshold-crossing is guaranteed to fire at most once per `escalation_cycle`. |
| **Ticket Claimed / Transferred** | `InteractionService.claim_ticket`/`transfer_agent` → `TICKET_CLAIMED`/`AGENT_TRANSFERRED` audit writes, plus a `TICKET_ASSIGNED` notification to the new agent + client's Account Manager + new agent's Team Lead | Old and new `agent_id`, actor, `ticket_id`. |

**What a future event mechanism would need that doesn't exist today, if built**: a persistent, ordered, replayable event log or message queue (Kafka/SQS/Postgres-`LISTEN`-`NOTIFY`-style) — none exists; every trigger point above fires synchronously inline within the HTTP request that caused it, with no buffering, retry, or replay semantics beyond what the audit-log table itself durably records. **[NOT AVAILABLE]**: event versioning, schema registry, or an at-least-once delivery guarantee for anything except the SLA-threshold ledger's own narrow idempotency check.

---

## 14. Known gaps that materially affect integration reliability

The first four items below were originally carried forward from a prior audit (dated 2026-07-20) with a "not re-verified in this pass" hedge. **This re-verification pass actually re-checked all four directly against current source code** rather than repeating the hedge — their status has changed, in both directions, and each is now a confirmed, current finding rather than a year-old note of uncertain relevance.

- **`CRITICAL` priority is still forceable via the ordinary `change_priority` endpoint — CONFIRMED STILL PRESENT.** Checked directly: `PriorityChangeRequest.new_priority` (`unified-backend/app/ticketing/schemas/ticket_action.py`) is typed as the full `TicketPriority` enum with no validator excluding `CRITICAL`, and `InteractionService.change_priority` (`interaction_service.py:1642`) has no check blocking `request.new_priority == TicketPriority.CRITICAL` — it only checks view access, client ownership, and the escalation-freeze state, then applies whatever priority was submitted. Any holder of `ticket:change_priority` can force a ticket to `CRITICAL` (or reverse it away from `CRITICAL`) outside the escalation workflow entirely, contradicting the design intent documented in §3/§10 that `CRITICAL` is escalation-only and permanent. If the recommendation service treats `current_priority == CRITICAL` as "definitely escalation-caused," that assumption is confirmed unsafe as of this pass.
- **`EscalationService.manual_escalate` still has no client-ownership check — CONFIRMED STILL PRESENT.** Checked directly against `unified-backend/app/ticketing/services/escalation_service.py:312`: `manual_escalate` calls `ensure_agent_can_view_ticket`, `ensure_has_permission("ticket:escalate")`, and `ensure_ticket_not_closed` — but never `ensure_account_manager_owns_ticket_client`, and the route calling it (`POST /tickets/{id}/escalate`, `sla.py`) adds no ownership check of its own either. An Account Manager can manually escalate any ticket company-wide today, not just one belonging to their own clients.
- **The escalation-freeze skip is PARTIALLY FIXED since the original 2026-07-20 audit** — a genuine improvement, confirmed by direct comparison, not just a restated hedge. `close_ticket` and `reopen_ticket` (`interaction_service.py:1470` and `:1569`) now both call `ensure_agent_can_act_on_ticket` **with the escalation repositories passed in**, so the freeze check (`ensure_ticket_not_frozen_by_escalation`) is genuinely enforced on both paths today — the original audit's finding that these two skipped it entirely no longer holds. `AttachmentService.upload_attachment`, however, is **confirmed still unfixed** — the current root `CLAUDE.md` states outright that it "has never passed an escalation repository at all" and "keeps its prior behavior rather than becoming newly, incorrectly frozen." Net: 2 of the original 3 skip sites are fixed; 1 remains.
- **The acknowledge-without-assignment dead zone is CONFIRMED STILL PRESENT.** Checked directly against `TicketEscalationRepository.list_overdue_active` (`unified-backend/app/ticketing/repositories/ticket_escalation_repository.py:204`): the sweep's auto-advance candidate query filters `TicketEscalation.status == EscalationStatus.ACTIVE` only. An escalation that reaches `ACKNOWLEDGED` (a bare `EscalationService.acknowledge()` click) but is never actually assigned/confirmed (`acknowledge_via_assignment`/`confirm_assignment`, which alone advance it past `ACKNOWLEDGED`) is permanently excluded from this query — it will never time out or auto-advance again, a genuine stall state requiring manual intervention to notice and fix.
- **New finding, this pass — the `/api/v1/users` merged-identity mechanism (§4.1).** `GET`/`PUT`/`PATCH`/`DELETE /api/v1/users/{id}` and the `GET /api/v1/users` list all transparently resolve against **either** `users` **or** `clients`, presenting client companies as `role: "Client"` pseudo-users with `user_id` actually being a `clients.client_id`. Not previously documented anywhere in this contract. A recommendation service treating every id from this endpoint as a real `users.user_id` (e.g. for an FK lookup against `tickets.agent_id`) will silently fail for every client-shaped row.
- **No service-to-service authentication path.** Every route requires a Bearer JWT from `POST /api/v1/auth/login`, issued to a real human-shaped user account. There is no API key, no client-credentials OAuth flow, no machine-account concept distinct from a regular user row. The recommendation service will need a real `users` row (likely a dedicated service account) to call any of the APIs in this document.
- **`Ticket.ticket_type` and `Interaction.interaction_type` are both unconstrained strings at the database level.** Neither can be trusted to only ever contain the documented value sets without the recommendation service validating them itself.
- **No recommendation/embedding/feedback infrastructure of any kind exists.** No pgvector extension enabled, no embedding columns, no feedback/rating/recommendation-log table, no ML dependency in the backend's own requirements. Anything the recommendation service needs beyond what's cataloged in §1–§11 is genuinely new work on the production side, not a lookup gap in this document.
- **`sla_policies`' live values can drift from migrated defaults via the admin UI** (§7.1) — always read live, never assume a cached snapshot (including this document's own examples) reflects the current table state.

---

## 15. Verification pointers (file map)

| Area | Path |
|---|---|
| Client model / schema / API | `unified-backend/app/ticketing/{models/client.py, schemas/client.py, api/client.py}` |
| Interaction model / schema / API | `unified-backend/app/ticketing/{models/interaction.py, schemas/interaction.py, api/interaction.py, api/inbox.py}` |
| Interaction-timeline synthesis (§2.1) | `unified-backend/app/ticketing/services/audit_to_interaction.py`, `services/interaction_service.py` (`get_ticket_interactions`) |
| Ticket model / schema / API | `unified-backend/app/ticketing/{models/ticket.py, schemas/ticket.py, api/ticket.py}` |
| User model / schema / API | `shared_models/shared_models/models/user.py`, `unified-backend/app/rbac/{schemas/user.py, api/v1/users.py}` |
| User/Client merged identity (§4.1) | `unified-backend/app/rbac/services/user_service.py` (`_resolve_user_or_client`, `_client_to_user_response`, `list_users`), `repositories/user_repository.py` (`delete`) |
| Role roster / Viewer→Client rename (§11.2) | `unified-backend/scripts/rbac_seed/seed.py` (`DEFAULT_ROLES`), `alembic_rbac/versions/a8c0e2f4b6d9_rename_viewer_role_to_client.py` |
| Attachment model / schema / API | `unified-backend/app/ticketing/{models/attachment.py, schemas/attachment.py, api/attachment.py}` |
| SLA models / schemas / API | `unified-backend/app/ticketing/{models/{resolution_sla,first_response_sla,sla_policy,sla_breach_notification,escalation_handling_sla}.py, schemas/sla.py, api/sla.py}` |
| Escalation model / service | `unified-backend/app/ticketing/{models/ticket_escalation.py, services/escalation_service.py}` |
| §14 confirmed-gap re-verification | `unified-backend/app/ticketing/services/interaction_service.py` (`change_priority`), `services/escalation_service.py` (`manual_escalate`, `close_ticket`/`reopen_ticket` freeze calls), `repositories/ticket_escalation_repository.py` (`list_overdue_active`), `services/attachment_service.py` (`upload_attachment`) |
| Notification model / schema / API | `unified-backend/app/notifications/{models.py, schemas.py, routes.py, sse_manager.py, service.py}` |
| Ticketing audit log | `unified-backend/app/ticketing/{models/audit_log.py, schemas/audit_log.py, services/audit_log_service.py, enums/audit_enums.py}` |
| RBAC audit log | `unified-backend/app/rbac/{models/audit_log.py, api/v1/audit_logs.py}` |
| Category / Role / Permission | `shared_models/shared_models/models/{category,role}.py`, `unified-backend/app/rbac/models/permission.py` |
| Two Alembic chains | `unified-backend/alembic_rbac/versions/`, `unified-backend/alembic_ticketing/versions/` |
| Route mounting | `unified-backend/app/main.py` |
| Deterministic thread-match / open-email logic | `unified-backend/app/ticketing/services/open_email_service.py`, `mail_mapping_service.py` |
