# ADR-004: Two Independent SLA Clocks, Never Conflated

**Status**: Accepted (implemented, in production use)

## Context

A support ticket has two genuinely different time-based commitments: how fast does an agent first respond, and how fast is the underlying issue actually resolved. These can succeed or fail independently of each other.

## Problem

Should there be one SLA clock per ticket, or two?

## Options Considered

1. **One combined SLA clock** — simpler data model, but conflates "responded promptly" with "resolved the issue," which are different business commitments with different stakeholders caring about each.
2. **Two independent clocks** — `FirstResponseSLA` (keyed to the thread-root Interaction) and `ResolutionSLA` (keyed to the Ticket) — each with its own start/pause/complete lifecycle.

## Decision

Two independent clocks (option 2).

## Reason

A ticket can have a perfectly on-time first response while still breaching its resolution target (the issue is hard, but the client was acknowledged quickly) — collapsing these into one metric would hide that distinction from both the business and from escalation logic, which specifically only escalates on Resolution SLA breaches, never First Response ones.

## Trade-offs

- **Cost**: two separate tables, two separate repositories, two separate sweep-evaluation code paths — genuinely more code than one unified clock.
- **Cost**: a First Response clock is keyed to an *Interaction* (the thread root), while Resolution is keyed to a *Ticket* — these are different foreign keys with different cardinality assumptions, adding conceptual overhead for a new developer.
- **Benefit**: each clock's completion condition can be tailored precisely — First Response completes on a human triage action *or* an automated OTP-rule match; Resolution completes only on ticket closure, deliberately not on mere resolution.

## Consequences

A separate, related decision followed from this one: the Escalation workflow (see [ADR-006](ADR-006-escalation-model.md)) was built as a third, independent state machine layered on top of Resolution SLA specifically — never allowed to write to Resolution SLA's own columns, preserving the same "don't conflate independent concerns" principle this ADR establishes.

## Related Components

`app/ticketing/models/{first_response_sla,resolution_sla}.py`, `app/ticketing/services/sla_service.py`, `app/ticketing/models/sla_policy.py`.
