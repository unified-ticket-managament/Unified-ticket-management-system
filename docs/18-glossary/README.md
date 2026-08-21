# Glossary

Domain terminology as actually used in the codebase and by the product ("UTMS" — Unified Ticket Management System). Where a term maps to a specific database table, enum, or model, that mapping is given so a developer can jump straight to the implementation.

Terms are grouped by domain. See also [16-known-limitations](../16-known-limitations/README.md) for terms describing gaps, and [03-business-workflows](../03-business-workflows/README.md) for the workflows these terms participate in.

## Roles (RBAC)

| Term | Meaning |
|---|---|
| **Super Admin** | Highest-rank role (rank 5). Holds every permission by default. Unconditional authority over permission overrides, requests, org visibility. |
| **Site Lead** | Rank 4. All permissions except `ticket:system_config`/`audit:export`. Company-wide overseer — sits outside the `manager_id`/`teamlead_id` reporting tree (`OrganizationService.ROLE_HIERARCHY` excludes it), sees everything unconditionally. |
| **Account Manager** | Rank 3. Renamed in-place from "Manager" (same `role_id`, no data migration). Owns a set of Clients; can transfer tickets to *any* Team Lead company-wide (not just their own reports — see [organization-structure module](../04-functional-modules/organization-structure.md)). |
| **Team Lead** | Rank 2. Manages a category's Staff. Starting point for most escalations. |
| **Staff** | Rank 1. Front-line agent. Handles assigned/pool tickets within their category. |
| **Client** | External, ticket-submitting party — not the same as the `Viewer` RBAC role. See "Client" below. |
| **Viewer** | A client-facing RBAC role outside the rank ladder, with a small fixed permission set (`user:view`, `role:view`, `permission:view`). Do not confuse with the ticketing-domain "Client" entity. |
| **RBAC** | Role-Based Access Control. In this codebase specifically: `unified-backend/app/rbac/` — the module owning authentication, users, roles, permissions, and (as sole JWT issuer) session identity for the whole product. |
| **Reporting Manager** | An *additional* HR/people-management responsibility layered onto an existing Account Manager for one or more Categories — not a role, not automatic. See `reporting_manager_teams` table and [organization-structure module](../04-functional-modules/organization-structure.md). |

## Ticketing core entities

| Term | Meaning |
|---|---|
| **Client** | The external party (identified by email/domain) whose emails become Interactions/Tickets. Owned by an Account Manager. Table: `clients`. |
| **Interaction** | One atomic unit of communication on a ticket's timeline — an inbound email, an agent reply, an internal note, a forward, a status change record, etc. All represented as rows in one `interactions` table, differentiated by an interaction-type column. The "one activity, several representations" building block behind Timeline, Mail, and System Mail. |
| **Ticket** | A trackable unit of work created from (or attached to) a client communication thread. Carries `current_priority`, `current_status`, `ticket_number` (human-readable `TKT-<n>`), category, assigned agent. |
| **Ticket Number (`TKT-n`)** | Sequential, human-readable ticket reference generated from a dedicated Postgres `SEQUENCE` (`ticket_number_seq`), never `MAX()+1`. Assigned once, never reused, even if the ticket is later deleted. |
| **Thread / Thread Root** | The originating Interaction of an email conversation. SLA clocks and ticket association are always resolved to the thread root, never to an individual reply. |
| **Category** | A department/queue grouping that scopes Staff/Team Lead visibility and ticket routing. **As of 2026-08-21, dynamically created at runtime** through the Category CRUD API (`category:create` permission) — no longer a fixed `CategoryName` enum (that Python enum and its backing Postgres type were both deleted). Distinct from the Profile module's free-text `department`/`team` display fields, which carry no authorization weight. |
| **Open Pool** | The set of unclaimed, category-visible tickets any eligible Staff member in that category can claim. Escalated-but-unclaimed tickets are excluded from the pool (see Escalation below). |
| **Assignment / Transfer / Claim** | Three ways a ticket's `agent_id` changes: assignment (supervisor picks an agent), transfer (`POST /tickets/{id}/transfer`), claim (agent self-assigns from the pool, `POST /tickets/{id}/claim`). |
| **Attachment** | A file associated with an Interaction (inbound Graph attachment, or agent-uploaded). Governed by `ticket:upload_attachment` / `ticket:archive_attachment` permissions. |

## SLA

| Term | Meaning |
|---|---|
| **SLA (Service Level Agreement)** | A target response/resolution time. This system has two independent per-ticket clocks — see below. |
| **First Response SLA** | Clock starting when a ticket's founding (thread-root) interaction lands; completes on the first agent reply, an OTP-rule match, or another human triage action (archive/attach/create-ticket). Table: `first_response_slas` (name confirmed in [06-database](../06-database/README.md)). |
| **Resolution SLA** | Clock starting at ticket creation; pauses while status is `WAITING_FOR_CLIENT`; reshifts its `due_at` on a priority change; completes only when a ticket is **closed** (not merely resolved). Table: `resolution_slas`. |
| **SLA Policy** | Per-priority-tier configuration row (target minutes for First Response/Resolution, warning-threshold percentages, escalation ack window, handling-SLA percentage). Table: `sla_policies`. Editable live via the Super-Admin-only SLA Timing Matrix page — not hardcoded. |
| **Half-Elapsed / At-Risk / Breached / Escalated** | The four threshold tiers a clock's elapsed-fraction is compared against every sweep tick. Each `(clock, threshold)` pair notifies exactly once (idempotency ledger: `SLABreachNotificationRepository`). |
| **SLA Sweep** | The periodic background job (`SLASweepService.run_sweep`) that evaluates every active clock, records breach notifications, and triggers escalation/handling-SLA evaluation. Runs in-process via APScheduler. |
| **Handling SLA (`EscalationHandlingSLA`)** | A second, independent clock measuring time-to-resolve *after* an escalation has been accepted (acknowledged + assigned). Target = 25% of the original Resolution SLA target. Breaching it auto-advances the escalation to the next level. |
| **Pause / Resume** | Resolution SLA clock behavior tied to a ticket entering/leaving `WAITING_FOR_CLIENT` status. Logged as `SLA_PAUSED`/`SLA_RESUMED` audit events (also used, tagged differently, for the manual-override path). |

## Escalation

| Term | Meaning |
|---|---|
| **Escalation** | A separate ownership-handoff workflow (`TicketEscalation`) layered on top of — but never mutating — the Resolution SLA clock's own columns. Auto-creates on a Resolution SLA `BREACHED`/`ESCALATED` crossing, or can be triggered manually. |
| **Escalation Level** | `TEAM_LEAD → MANAGER (Account Manager) → SITE_LEAD`. Starting level is dynamic — one level *above* whoever currently owns the ticket, not always `TEAM_LEAD`. |
| **Acknowledge** | Step 1 of 2: the current escalation owner acknowledges receipt. Stops the ack-window auto-advance clock; does **not** by itself restart the Resolution SLA or start the Handling SLA. |
| **Acknowledge & Assign** | The full two-step acceptance flow. Assigning (or explicitly confirming the current assignee via `confirm_assignment`) is what actually completes acceptance (`_complete_acceptance`) — reshifting the Resolution SLA and starting the Handling SLA. |
| **CRITICAL priority** | A fourth `TicketPriority` tier, escalation-only and permanent — the only writer is the escalation-creation path; it's never manually selectable and never reverts, even after the escalation closes. |
| **Escalated tab** | A role-gated ticket-list view (`view=escalated`) scoped to the escalation's *current* `owner_ids` — not merely "this ticket has an active escalation." |

## Notifications & Audit

| Term | Meaning |
|---|---|
| **Notification** | An in-app record (Bell + System Mail) created by `NotificationService.notify()` — the single write path every trigger in the app goes through. Optionally also emailed, per a fixed type allowlist (`EMAIL_ELIGIBLE_NOTIFICATION_TYPES`). |
| **SSE (Server-Sent Events)** | The real-time push channel (`GET /notifications/stream`) that replaced 30-second bell polling. |
| **Audit Log / Audit Event** | An immutable record of a significant action. Two *separate* tables/systems share the phrase "Audit Log": RBAC-native `audit_logs` (`app.rbac`) and the ticketing domain's own `ticket_audit_logs` (`AuditEventType` enum, `app.ticketing`) — never conflate them. |
| **Permission Override** | A per-user, additive exception to a role's default permission bundle. Can optionally be scoped to one specific ticket (`scope_ticket_id`). |
| **Permission Request** | A self-service request for a permission, addressed to one specific selected approver (not a role). |

## Misc / process

| Term | Meaning |
|---|---|
| **OTP Rule** | A Mail/OTP Rules-engine rule (`RuleCategory.OTP_RULE`) that controls folder filing and forwarding for OTP-like emails. **As of 2026-08-21, no longer tied to SLA completion** — see OTP Classifier below. |
| **OTP Classifier** | `app/ticketing/services/otp_classifier.py` — a pure, dependency-free heuristic text scorer (regex/weighted-pattern based, not ML/LLM) that decides whether an inbound email is a genuine one-time-passcode delivery. Its output (compared against `Settings.otp_nlp_confidence_threshold`, default 0.90) is what completes the First Response SLA clock as of 2026-08-21 — replacing the previous OTP-Rule-keyword-match trigger. See [04-functional-modules/ai-nlp.md](../04-functional-modules/ai-nlp.md). |
| **Graph** | Microsoft Graph API — the optional mailbox integration used for receiving/sending ticket-related email. |
| **Permission Version** | An integer column on `User`, bumped on any role/category/hierarchy/override change, used as the RBAC session cache's invalidation key. |
