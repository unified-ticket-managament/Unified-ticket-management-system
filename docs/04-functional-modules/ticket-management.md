# Ticket Management Module

## Purpose
Own the ticket entity itself — its lifecycle, visibility scoping, and the actions agents/supervisors take on it.

## Responsibilities
- Ticket creation from an interaction; status/priority/category changes; close/reopen.
- Visibility scoping across four views: `mine`, `pool`, `all`, `escalated`.
- Related-ticket linking, attachments, per-ticket audit trail.

## Main Components
- `app/ticketing/api/ticket.py`
- `app/ticketing/services/ticket_service.py`
- `app/ticketing/repositories/ticket_repository.py`
- `app/ticketing/models/{ticket,ticket_relation}.py`

## Inputs
Interaction to ticket from, priority/status/category change requests.

## Outputs
`TicketResponse`/`TicketListItemResponse` — including escalation-derived display fields (`is_escalated`, `escalation_level`, `is_escalation_owner`) computed via LEFT JOIN, not per-row lookups.

## Business Rules
- `ticket_number` is sequence-generated, never reused, assigned once at creation.
- `current_priority` can never be set to `CRITICAL` through the normal priority-change path — escalation-only.
- Entering `RESOLVED` does not complete the Resolution SLA clock — only `CLOSED` does.
- `view=pool` excludes any ticket with an active escalation; `view=escalated` is scoped to the escalation's *current* `owner_ids`.
- `view=mine`'s `ORDER BY` (escalated first, then HIGH priority, then nearest SLA deadline, then chosen sort, then `ticket_id` tie-break) is computed entirely in SQL.

## Dependencies
`InteractionService`, `SLAService`, `EscalationService`, `AssignmentService`, `AttachmentService`, `AuditLogService`.

## Database Entities
`tickets`, `ticket_relations`.

## APIs
[07-api/tickets.md](../07-api/tickets.md).

## Important Classes/Services
`TicketService`, `TicketRepository`.

## External Integrations
None directly.

## Known Limitations
- Related Tickets link/unlink has no permission defined in the RBAC matrix document.
- No workload-aware ranking exists for any assignment-adjacent decision on this entity.

## Related workflows
All of [03-business-workflows/ticket](../../03-business-workflows/ticket/).
