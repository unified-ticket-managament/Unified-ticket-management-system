# Dashboard & Reporting Module

## Purpose
Give each role a landing view appropriate to their job (org oversight vs. hands-on ticket work) and surface aggregate ticket/SLA statistics.

## Responsibilities
- Per-role dashboard routing (Super Admin/Site Lead get their own dashboards; Staff/Team Lead/Account Manager land in the embedded ticket workspace).
- Ticket dashboard stat cards, SLA overview tiles.
- A Reports page (`unified-frontend/src/app/(dashboard)/reports/page.tsx`).

## Main Components
- Backend: `GET /tickets/dashboard-stats`, `GET /tickets/sla-overview-counts`, `GET /tickets/view-counts` (`app/ticketing/api/ticket.py`, `TicketRepository`).
- Frontend: `src/components/dashboard/{site-lead-dashboard,viewer-dashboard}.tsx`, `src/ticket-workspace/pages/Dashboard.tsx`, `src/app/(dashboard)/reports/page.tsx`, `ModernStatCard.tsx`/`ModernBarListCard.tsx`.

## Inputs
Ticket/SLA state across the caller's visibility scope.

## Outputs
Dashboard stat cards, SLA overview tiles, report views.

## Business Rules
- The SLA overview tile computation was rewritten from an N+1 pattern (`listTickets()` + per-ticket `GET /tickets/{id}/sla`) to one dedicated endpoint, cutting measured load time from ~16.3s to ~1.2–1.9s — a real, confirmed performance fix, not a hypothetical one.
- Landing dashboard is role-determined, not user-configurable beyond the `default_dashboard` profile preference field (verify whether that preference is actually consulted at routing time — **not independently confirmed** in this pass).

## Dependencies
`TicketRepository` (aggregate SQL queries).

## Database Entities
Reads across `tickets`, `resolution_slas`, `first_response_slas`, `ticket_escalations` — no dedicated reporting table exists.

## APIs
[07-api/tickets.md](../07-api/tickets.md) (`/dashboard-stats`, `/sla-overview-counts`, `/view-counts`).

## Important Classes/Services
`TicketRepository` (the aggregate query methods), no dedicated `ReportingService` was found — reporting logic lives inside `TicketRepository`/`TicketService`.

## External Integrations
None.

## Known Limitations
- The depth/completeness of the Reports page's own data aggregation was **not independently verified** in this documentation pass — treat its exact contents as unconfirmed until read directly.
- No load-testing/performance-benchmark data exists beyond the one confirmed SLA-overview fix above.

## Related workflows
Not a dedicated workflow document in the required structure — this module aggregates state produced by [ticket](../../03-business-workflows/ticket/) and [sla](../../03-business-workflows/sla/) workflows rather than being a workflow itself.
