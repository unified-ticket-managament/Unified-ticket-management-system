# Tickets API

Source: `app/ticketing/api/ticket.py` (prefix `/tickets`). Service: `TicketService` (`app/ticketing/services/ticket_service.py`), backed by `TicketRepository`, `InteractionService`, `SLAService`, `EscalationService`, `AssignmentService`, `AttachmentService` as needed per action. See [03-business-workflows/ticket](../03-business-workflows/ticket/) for the full lifecycle narrative this API implements.

| Method | Path | Purpose | Auth |
|---|---|---|---|
| POST | `/tickets/from-interaction` | Create a ticket from a pending inbox interaction | `get_current_agent` |
| POST | `/tickets/{id}/attach-interaction` | Attach an existing interaction to an existing ticket | `get_current_agent` |
| GET | `/tickets/{id}/interactions` | Ticket's interaction/timeline feed | `get_current_user` |
| GET | `/tickets/{id}/attachments` | Ticket's attachments | `get_current_user` |
| GET | `/tickets/{id}/audit-logs` | Ticket's own (ticketing-domain) audit trail | `get_current_user` |
| POST | `/tickets/{id}/notes` | Add an internal note (with optional real recipients) | `get_current_agent` |
| GET | `/tickets/internal-notes/recipients` | Unscoped list of every active user, for the note "To" picker | `get_current_agent` |
| POST | `/tickets/{id}/reply` | Reply to the client on this ticket | `get_current_agent` |
| POST | `/tickets/{id}/claim` | Claim an unassigned pool ticket | `get_current_agent` |
| POST | `/tickets/{id}/status` | Change ticket status | `get_current_agent` |
| POST | `/tickets/{id}/priority` | Change ticket priority (never to CRITICAL — that's escalation-only) | `get_current_agent` |
| POST | `/tickets/{id}/attachments` | Upload attachment(s) | `get_current_agent` |
| POST | `/tickets/{id}/interactions/{interaction_id}/hide` | Hide/soft-delete one interaction | `get_current_agent` |
| GET | `/tickets/{id}/transfer-candidates` | Who the caller may transfer this ticket to | `get_current_agent` |
| POST | `/tickets/{id}/transfer` | Transfer ticket ownership | `get_current_agent` |
| POST | `/tickets/{id}/close` | Close ticket (completes Resolution SLA) | `get_current_agent` |
| POST | `/tickets/{id}/reopen` | Reopen a closed ticket | `get_current_agent` |
| POST | `/tickets/{id}/related` | Link to another ticket | `get_current_agent` |
| DELETE | `/tickets/{id}/related/{related_id}` | Unlink a related ticket | `get_current_agent` |
| PATCH | `/tickets/{id}` | Update ticket fields (title, type, custom fields, closed_at) | `get_current_agent` |
| GET | `/tickets` | List tickets — `view=mine\|pool\|all\|escalated`, paginated, optional `client_company_id` filter | `get_current_user` |
| GET | `/tickets/view-counts` | Tab badge counts matching the `view=` filters above | `get_current_user` |
| GET | `/tickets/dashboard-stats` | Dashboard stat cards, optional `client_company_id` filter | `get_current_user` |
| GET | `/tickets/sla-overview-counts` | SLA overview tile counts (single-query, replaced a former N+1), optional `client_company_id` filter | `get_current_user` |
| GET | `/tickets/audit-logs` | Audit logs across every visible ticket — `centralized=true` requires `ticket:view_global_audit_log`; optional `client_company_id` filter; response now includes `client_company_name` per row | `get_current_user` |
| GET | `/tickets/interactions` | Interactions across every visible ticket (cursor/paginated), optional `client_company_id` filter | `get_current_user` |
| GET | `/tickets/{id}` | Ticket detail | `get_current_user` |

## Key business rules

**Ticket creation** (`POST /tickets/from-interaction`): validates the client association, initializes ticket state (`current_status`, `current_priority`), assigns a `ticket_number` from the dedicated Postgres sequence, initializes both SLA clocks (First Response completes as soon as the founding interaction already has a reply; Resolution starts fresh), and records the initial audit event. See [03-business-workflows/ticket/ticket-creation.md](../03-business-workflows/ticket/ticket-creation.md).

**`view=` scoping**: `pool` excludes any ticket with an active escalation (escalated-but-unclaimed tickets are reachable only via the Escalated tab, never the open pool). `escalated` is scoped to the escalation's *current* `owner_ids`, not merely "this ticket has an active escalation" — see [03-business-workflows/escalation](../03-business-workflows/escalation/).

**Client filter (`client_company_id`, added 2026-08-21)**: narrows `GET /tickets`, `/dashboard-stats`, `/sla-overview-counts`, `/audit-logs`, and `/interactions` to one client's data — always applied **within** whatever the caller's own role scope already allows, never widening it (an Account Manager passing a `client_company_id` they don't own simply yields zero rows, the same as omitting the filter would for that client). Backed by the shared `ClientFilterSelect.tsx` frontend component, reused across the Tickets List, Audit Log, Interactions, Dashboard, and Reports pages, sourced from the already-cached `GET /clients` list rather than a per-page fetch.

**`view == "mine"` ordering**: `TicketRepository.list_visible_page`'s SQL `ORDER BY` puts actively-escalated tickets first, then HIGH priority, then nearest Resolution SLA deadline, then the caller's chosen sort, then `ticket_id` as a deterministic tie-breaker — computed entirely in SQL, no client-side sorting.

**Priority change**: `POST /tickets/{id}/priority` can never set `CRITICAL` manually — that value is written only by the escalation-creation code path (`EscalationService._bump_priority_to_critical`). See [03-business-workflows/sla/sla-calculation.md](../03-business-workflows/sla/sla-calculation.md).

**Close vs. Resolve**: entering `RESOLVED` does **not** complete the Resolution SLA clock; only `CLOSED` does (`POST /tickets/{id}/close`, supervisor-gated with `CLOSE_REOPEN_BYPASS_ROLE_NAMES` = Site Lead/Super Admin unconditionally, Account Manager/Team Lead/Staff via the real `ticket:close_ticket` permission).

**Internal Notes with real recipients** (`POST /tickets/{id}/notes`): `recipient_user_ids` (optional, default empty) snapshots into the Interaction's own `payload` JSON. When given, `notify()` is called for exactly that set; when empty, the legacy stakeholder-notify fallback (assigned agent + their Team Lead + the client's Account Manager) fires instead. Recipients are drawn from `GET /tickets/internal-notes/recipients` — a deliberately unscoped, hierarchy-free list (see [04-functional-modules/communication-management.md](../04-functional-modules/communication-management.md)).

## Side effects common to most mutating endpoints

- A `ticket_audit_logs` row (`AuditEventType`-typed), attributed to the acting user (or `ActorRole.SYSTEM` for automated changes like the CRITICAL-priority bump).
- One or more `NotificationService.notify()` calls (assignment, status change, reply received, etc.), which may also trigger a real outbound email per `EMAIL_ELIGIBLE_NOTIFICATION_TYPES`.
- SLA clock effects: `WAITING_FOR_CLIENT` transitions pause/resume the Resolution SLA; priority changes reshift `resolution_slas.due_at`.
