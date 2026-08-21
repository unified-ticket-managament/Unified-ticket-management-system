# ADR-006: Escalation as a Layer, Never a Clock Mutator

**Status**: Accepted (implemented, in production use)

## Context

When a ticket's Resolution SLA breaches, ownership needs to move up an accountability chain (Team Lead → Account Manager → Site Lead). This is conceptually related to, but distinct from, the SLA clock itself.

## Problem

Should escalation logic live inside `ResolutionSLA` (e.g. adding `escalation_level` as a column on that same table), or as a wholly separate entity?

## Options Considered

1. **Extend `ResolutionSLA`** with escalation-tracking columns directly.
2. **A separate `TicketEscalation` entity**, riding on top of — but architecturally forbidden from mutating — the Resolution SLA clock's own `started_at`/`due_at`/`status` columns.

## Decision

Option 2 — a fully separate `TicketEscalation` model, with the "never touch the clock's own columns" rule enforced as an explicit invariant the feature's own pytest suite exists specifically to guard.

## Reason

The Resolution SLA clock answers one question ("has this ticket's time budget been exceeded") and must remain a reliable, simple source of truth for that question alone. Escalation answers a different question ("who is currently accountable for fixing that"). Conflating them (e.g. an escalation "pausing" the clock, or "resetting" it) would make the clock's own history untrustworthy for reporting purposes, and would couple two features that have genuinely independent failure modes and business owners.

## Trade-offs

- **Cost**: any code that needs to change a ticket's priority as a side effect of escalating (the CRITICAL bump) must call *back into* `SLAService`'s own reshift function rather than writing to `ResolutionSLA` directly — a deliberate friction, enforced via a deferred import specifically to avoid a circular dependency between `escalation_service.py` and `sla_service.py`.
- **Cost**: a second clock (`EscalationHandlingSLA`) was later added on top of the escalation workflow itself, for a third independent concept (time-to-resolve-after-acceptance) — three layered systems now exist where one might have seemed sufficient at a glance.
- **Benefit**: this separation is what let the Resolution SLA clock's semantics stay simple and stable across two major additions (Acknowledge & Assign, CRITICAL priority) built well after the original SLA feature shipped — neither required touching `ResolutionSLA`'s own model.

## Consequences

A real, confirmed near-miss: the original single-step "Acknowledge" flow *did* briefly reshift the Resolution SLA and start the Handling SLA directly inside the acknowledge action — this was identified as a gap (a supervisor who acknowledged but never assigned had silently restarted the clock against nobody's ownership) and fixed by moving that reshift into a separate `_complete_acceptance` step, reinforcing this ADR's own principle after an initial implementation had drifted from it.

## Related Components

`app/ticketing/models/{ticket_escalation,escalation_handling_sla}.py`, `app/ticketing/services/{escalation_service,escalation_handling_sla_service}.py`.
