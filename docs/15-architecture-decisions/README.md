# Architecture Decision Records

Each ADR here documents a decision confirmed from actual code, migration history, or the project's own dated engineering log (root `CLAUDE.md`) — not a hypothetical rationale invented for this documentation pass.

- [ADR-001-database-architecture.md](ADR-001-database-architecture.md) — one database, two Alembic chains
- [ADR-002-authentication.md](ADR-002-authentication.md) — RBAC issues, Ticketing verifies
- [ADR-003-ticket-interaction-separation.md](ADR-003-ticket-interaction-separation.md) — one Interaction model for every communication type
- [ADR-004-sla-strategy.md](ADR-004-sla-strategy.md) — two independent clocks, never conflated
- [ADR-005-scheduler.md](ADR-005-scheduler.md) — in-process APScheduler over external cron
- [ADR-006-escalation-model.md](ADR-006-escalation-model.md) — escalation as a layer, never a clock mutator
- [ADR-007-ai-llm-boundaries.md](ADR-007-ai-llm-boundaries.md) — no AI/LLM integration exists (a non-decision, documented as such)
- [ADR-008-email-integration.md](ADR-008-email-integration.md) — Microsoft Graph with a mock-provider fallback
