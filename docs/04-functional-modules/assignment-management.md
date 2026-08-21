# Assignment Management Module

## Purpose
Resolve, validate, and enforce who may be assigned a ticket — role-scoped, category-scoped, and (for escalations) ownership-chain-scoped.

## Responsibilities
- Candidate-group resolution for the Create Ticket "Assigned To" picker and Claim/Transfer/Assign actions.
- Server-side validation that a submitted `agent_id` is actually within the caller's authority.
- Escalation-specific candidate resolution (role-scoped Acknowledge & Assign picker).

## Main Components
- `app/ticketing/services/assignment_service.py`
- `app/ticketing/api/agent.py`
- `app/ticketing/services/escalation_service.py` (`get_acknowledge_candidates`)

## Inputs
Ticket's category/client, caller's role/category/reporting scope.

## Outputs
`AssignableGroup`/`AssignableUserSummary` grouped candidate lists.

## Business Rules
- Account Manager candidate scope is deliberately wider than their real reports: every active Team Lead company-wide, plus their own reports' Staff.
- A submitted `agent_id` is always re-validated server-side (`resolve_target`) against the caller's actual authority — a crafted request can't assign outside the picker's own offered set.
- Transfer to Staff is unconditionally category-scoped (previously only enforced during an active escalation — a real, closed gap).
- The Acknowledge & Assign candidate picker is role-scoped differently from the plain assignment picker — see [03-business-workflows/escalation/escalation-handoff.md](../../03-business-workflows/escalation/escalation-handoff.md).

## Dependencies
`UserRepository` (role/category/hierarchy queries), `OrganizationService`.

## Database Entities
Reads `users`/`roles`/`categories`; writes `tickets.agent_id`/`.assigned_by`.

## APIs
[07-api/interactions-agents-attachments.md](../07-api/interactions-agents-attachments.md) (`/agents`), [07-api/tickets.md](../07-api/tickets.md) (`/transfer`, `/claim`), [07-api/sla-escalation.md](../07-api/sla-escalation.md) (`/escalation/acknowledge-candidates`).

## Important Classes/Services
`AssignmentService`.

## External Integrations
None.

## Known Limitations
- No workload-based ranking within a resolved candidate group — see [17-roadmap/v2-roadmap.md](../17-roadmap/v2-roadmap.md).
- No availability/shift-presence filtering.

## Related workflows
[03-business-workflows/ticket/ticket-assignment.md](../../03-business-workflows/ticket/ticket-assignment.md), [03-business-workflows/escalation/escalation-handoff.md](../../03-business-workflows/escalation/escalation-handoff.md).
