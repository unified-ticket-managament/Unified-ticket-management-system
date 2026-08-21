# SLA Management Module

## Purpose
Track and enforce two independent, priority-driven time commitments per ticket, with configurable policy and graduated risk visibility.

## Responsibilities
- First Response and Resolution clock lifecycle (start, pause/resume, complete, reshift).
- Periodic breach-threshold evaluation (the sweep) and idempotent notification.
- Live-editable SLA policy per priority tier.

## Main Components
- `app/ticketing/services/{sla_service,sla_sweep_service,sla_breach_notifier}.py`
- `app/ticketing/repositories/{first_response_sla_repository,resolution_sla_repository,sla_policy_repository,sla_breach_notification_repository}.py`
- `app/ticketing/models/{first_response_sla,resolution_sla,resolution_sla_pause_interval,sla_policy,sla_breach_notification}.py`
- `app/core/sla_scheduler.py`

## Inputs
Ticket creation/priority-change events, status transitions, the periodic sweep tick.

## Outputs
`GET /tickets/{id}/sla`'s clock state; the SLA breach notification ladder.

## Business Rules
- SLA targets depend on priority alone, sourced from the live-editable `sla_policies` table.
- `resolution_slas.due_at` is a mutable, shifting value, not an accumulated-elapsed counter.
- Four thresholds (`HALF_ELAPSED`/`AT_RISK`/`BREACHED`/`ESCALATED`) per clock, each notifying exactly once per `(clock, threshold, cycle)` via an idempotency ledger.
- The sweep interval itself differs by environment: 10s local default vs. 60s production — a deliberate, not accidental, difference.

## Dependencies
`EscalationService` (auto-escalation trigger), `NotificationService`.

## Database Entities
`first_response_slas`, `resolution_slas`, `resolution_sla_pause_intervals`, `sla_policies`, `sla_breach_notifications`.

## APIs
[07-api/sla-escalation.md](../07-api/sla-escalation.md).

## Important Classes/Services
`SLAService`, `SLASweepService`.

## External Integrations
None directly (the scheduler is in-process).

## Known Limitations
- Connection-pool sizing and sweep-cadence tuning were both reactive fixes to specific past incidents, not proactive capacity planning — see [16-known-limitations/performance-limitations.md](../16-known-limitations/performance-limitations.md).
- A per-ticket SAVEPOINT was found not to fully isolate every error class from cascading into a later, unrelated ticket in the same sweep tick (historical, now fixed for the specific cause found).

## Related workflows
All of [03-business-workflows/sla](../../03-business-workflows/sla/).
