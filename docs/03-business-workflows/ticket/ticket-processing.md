# Ticket Processing Workflow

## 1. Purpose
Cover the day-to-day work done on an open ticket: replying to the client, adding internal notes, changing category/priority, uploading attachments, linking related tickets.

## 2. Trigger
Any of: `POST /tickets/{id}/reply`, `POST /tickets/{id}/notes`, `POST /tickets/{id}/priority`, `PATCH /tickets/{id}`, `POST /tickets/{id}/attachments`, `POST /tickets/{id}/related`.

## 3. Actors
Any agent with visibility into the ticket (category-scoped for Staff/Team Lead, client-ownership-scoped for Account Manager, unrestricted for Site Lead/Super Admin).

## 4. Preconditions
Ticket exists, is not closed (most actions), and the caller passes `ensure_agent_can_act_on_ticket` (category/client-ownership check, plus an escalation-ownership freeze if applicable).

## 5. High-Level Flow
Agent action → permission/ownership check → mutation → Interaction/audit record → notification (where applicable).

## 6. Detailed Workflow

**Reply** (`POST /tickets/{id}/reply`): creates an outbound `Interaction`, dispatches via the configured mail provider, completes the First Response SLA clock if this is the first agent reply on the thread.

**Internal Note** (`POST /tickets/{id}/notes`): optionally carries `recipient_user_ids` — validated (must be active, sender auto-dropped), snapshotted into the Interaction's `payload`. When given, `notify()` targets exactly that set; when empty, falls back to the legacy stakeholder set (assigned agent + their Team Lead + the client's Account Manager). See [04-functional-modules/communication-management.md](../../04-functional-modules/communication-management.md).

**Priority change** (`POST /tickets/{id}/priority`): reshifts the Resolution SLA's `due_at` proportionally (see [sla/sla-calculation.md](../sla/sla-calculation.md)); can never set `CRITICAL`.

**Category change**: writes a `CATEGORY_TRANSFERRED` audit event (added in a recent migration, `b5d7f9a1c3e6`).

**Attachment upload** (`POST /tickets/{id}/attachments`): authorization is checked (historically a real bug here — a missing `await` silently skipped the check entirely; fixed during the 2026-07-14/15 audit — see [15-architecture-decisions](../../15-architecture-decisions/README.md)).

## 7. Business Rules
- **The freeze on the previous owner during an active, accepted escalation is enforced here too** — `ensure_agent_can_act_on_ticket`, when given an `EscalationHandlingSLA` repository, checks whether acceptance has actually completed (an `EscalationHandlingSLA` row exists) rather than a coarser status check, so the previous owner stays frozen through the "acknowledged but not yet assigned" gap. `AttachmentService.upload_attachment` has never been updated to pass this repository, so it still uses the older, coarser check — a known, accepted inconsistency.
- Reply's CC/BCC are plain optional fields with real backend delivery (`ReplyRequest.cc`/`.bcc`) but no auto-population (a former hardcoded "CC: Account Manager (auto)" chip was removed).

## 8. Decision Points
- Recipients given on an internal note? → real delivery vs. stakeholder fallback.
- Is the acting agent the escalation's previous (frozen) owner? → action blocked if acceptance hasn't completed.

## 9. Database Changes
`interactions` (reply/note rows), `tickets.current_priority`/`.ticket_type` (category change), `resolution_slas.due_at` (priority change), `attachments`, `ticket_relations`.

## 10. APIs Involved
See [07-api/tickets.md](../../07-api/tickets.md) for the full endpoint table.

## 11. Services / Components Involved
`InteractionService`, `TicketService`, `AttachmentService`, `SLAService`.

## 12. External Integrations
Outbound reply dispatch goes through the same mail provider as inbound (Graph or mock).

## 13. Notifications
`CLIENT_REPLY` equivalent (agent-side reply doesn't notify the agent; a *client* reply notifies the assignee — see [communication workflows](../communication/)), internal-note recipient notifications, category/priority-change notifications where wired.

## 14. Audit Events
`REPLY_SENT`, `NOTE_ADDED`, `PRIORITY_CHANGED`, `CATEGORY_TRANSFERRED`, attachment-related events (verify exact `AuditEventType` members against `app/ticketing/enums/audit_enums.py`).

## 15. Failure Scenarios
Acting on a frozen (escalation-owned-but-not-yet-accepted) ticket returns a 403 rather than allowing the action.

## 16. Edge Cases
- `test_scoped_ticket_access_visibility.py` covers a ticket-scoped permission override bypassing the normal category restriction for exactly the one granted ticket.

## 17. Postconditions
The ticket's Timeline reflects the new activity; SLA/audit state is consistent with the action taken.

## 18. Relevant Source Files
- `unified-backend/app/ticketing/api/ticket.py`
- `unified-backend/app/ticketing/services/{interaction_service,ticket_service,attachment_service}.py`
- `unified-backend/app/ticketing/services/access_control.py`

## 19. Example Scenario
A Staff member replies to a client on an in-progress ticket. `InteractionService` creates the outbound Interaction, dispatches it via Graph, and — since this is the thread's first agent reply — completes the First Response SLA clock with `completion_reason="AGENT_REPLY"` (exact string not independently re-confirmed against code; verify in `sla_service.py`).
