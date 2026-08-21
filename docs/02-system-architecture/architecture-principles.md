# Architecture Principles

Recurring patterns actually followed across this codebase — confirmed by repeated appearance across independent modules, not aspirational guidelines.

## 1. Layered architecture: API → Service → Repository → Model

Both `app/rbac/` and `app/ticketing/` follow the same layering. Routes hold no business logic; services hold business logic and (where present) authorization; repositories hold data access; models are plain SQLAlchemy. See [05-technical-architecture/application-layers.md](../05-technical-architecture/application-layers.md).

## 2. One write path per cross-cutting concern

- **Notifications**: every trigger across both domains calls `NotificationService.notify()` — there is exactly one function that creates a `Notification` row, publishes to SSE, and conditionally emails.
- **Permission override creation**: exactly one code path (`PermissionOverrideService.grant()`) ever creates a `UserPermissionOverride` row — even the Permission Request approval flow calls through it rather than duplicating the insert.
- **CRITICAL priority**: exactly one writer (`EscalationService._bump_priority_to_critical`).

This pattern recurs specifically because several historical bugs (missed `await`, missed notification call, forgotten audit log) came from a second, divergent path existing alongside the "real" one — see [15-architecture-decisions](../15-architecture-decisions/README.md).

## 3. Idempotency ledgers for anything that "fires once per crossing"

`SLABreachNotificationRepository.try_record_many` (a batched `INSERT ... ON CONFLICT DO NOTHING ... RETURNING`) ensures each `(clock, threshold)` pair notifies exactly once, even under concurrent sweep evaluation. The same shape (a unique index doubling as the idempotency guard) appears in `EscalationHandlingSLA`'s `breached_at`/`completed_at` partial unique index.

## 4. Additive-only permission model, soft-revocable

`user_permission_overrides` and `permission_requests` never hard-delete — every state change is a new row or a status/timestamp update, with a partial unique index enforcing "at most one active/pending instance" while preserving full history. See [08-security/authorization-rbac.md](../08-security/authorization-rbac.md).

## 5. Never let two migration chains share a foreign key

`alembic_rbac` and `alembic_ticketing` are independent histories against one database. Where a ticketing table needs to reference a user (nearly all of them do), a real FK is used because `users` is stable, cross-domain, shared infrastructure. Where an RBAC-domain table needs to reference a ticket (`scope_ticket_id` on overrides/requests), the FK is deliberately **omitted** — a plain, unconstrained UUID, validated in application code instead — specifically to avoid entangling the two chains' migration ordering. See [15-architecture-decisions/ADR-001-database-architecture.md](../15-architecture-decisions/ADR-001-database-architecture.md).

## 6. Graceful degradation on missing/old data, not hard failure

A JWT minted before a claim existed still decodes — the missing claim degrades to an empty list/dict rather than erroring. Unconfigured SMTP/Graph settings degrade to logging-only/mock providers rather than crashing at boot. This lets the system run in a partially-configured local-dev state without special-casing every caller.

## 7. In-process, single-instance state — deliberately, not by oversight

The RBAC session cache and the SSE pub/sub manager are both per-process, in-memory, no Redis. This is a real, acknowledged scaling ceiling (see [16-known-limitations/technical-limitations.md](../16-known-limitations/technical-limitations.md)), not an accident — both were built for a single-uvicorn-process deployment and would need a shared broker to scale further.

## 8. Separate, non-mutating clocks for separate concerns

The Resolution SLA clock, the internal Escalation workflow, and the Escalation Handling SLA are three genuinely independent state machines layered on top of each other, with an explicit rule (enforced by the escalation feature's own test suite) that the escalation workflow may never write to the Resolution SLA clock's own `started_at`/`due_at`/`status` columns. See [03-business-workflows/sla](../03-business-workflows/sla/) and [15-architecture-decisions/ADR-004-sla-strategy.md](../15-architecture-decisions/ADR-004-sla-strategy.md).
