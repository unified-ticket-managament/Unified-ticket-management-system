# Escalation Management Module

## Purpose
Hand ticket ownership up a real accountability chain when SLA commitments are at risk, without ever corrupting the Resolution SLA clock's own state.

## Responsibilities
- Auto/manual escalation creation, dynamic starting-level resolution.
- Ack-window auto-advance.
- Two-step Acknowledge & Assign acceptance.
- Escalation Handling SLA (a second, independent post-acceptance clock).
- CRITICAL priority bump (escalation-only, permanent).

## Main Components
- `app/ticketing/services/{escalation_service,escalation_handling_sla_service,escalation_rules}.py`
- `app/ticketing/repositories/{ticket_escalation_repository,escalation_handling_sla_repository}.py`
- `app/ticketing/models/{ticket_escalation,escalation_handling_sla}.py`
- `app/ticketing/enums/escalation_enums.py`

## Inputs
SLA breach crossings (auto), `ticket:escalate` requests (manual), acknowledge/assign actions.

## Outputs
`TicketEscalation` state, the Escalated tab's data, `is_escalation_owner`/`is_escalated` ticket fields.

## Business Rules
- Starting level is one above the current owner — never a fixed `TEAM_LEAD` floor for an already-supervisor-owned ticket.
- CRITICAL priority is the only escalation-driven, permanent, non-reverting priority change.
- Acknowledging is not accepting — only assignment (claim/transfer/confirm-assignment) actually reshifts the Resolution SLA and starts the Handling SLA.
- Escalated-but-unclaimed tickets are excluded from the Open Pool and never auto-assigned.
- The Escalated tab/Acknowledge action is scoped to current `owner_ids` — no overseer-role bypass for Site Lead/Super Admin.
- The Handling SLA's target is always 25% of the *original* Resolution SLA target, computed once.

## Dependencies
`SLAService` (shared reshift function), `NotificationService`, `AssignmentService`-adjacent candidate resolution.

## Database Entities
`ticket_escalations`, `escalation_handling_slas`.

## APIs
[07-api/sla-escalation.md](../07-api/sla-escalation.md).

## Important Classes/Services
`EscalationService`, `EscalationHandlingSlaService`.

## External Integrations
None.

## Known Limitations
- A known, accepted test flake (`test_overdue_active_escalation_advances_without_touching_sla`) inflates its assertion against a shared, never-reset dev database.
- `AttachmentService.upload_attachment` never passes the `EscalationHandlingSlaRepository` into the freeze check — falls back to a coarser, still-safe check.
- No ongoing reconciliation mechanism exists between `Ticket.current_priority` and `ticket_escalations` — a bug that temporarily broke the CRITICAL bump would require a manual one-off backfill to catch up, as happened once already.

## Related workflows
Both of [03-business-workflows/escalation](../../03-business-workflows/escalation/).
