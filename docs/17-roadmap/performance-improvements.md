# Performance Improvements

## Already done (confirmed, not proposals)

- SLA overview tile: N+1 (`listTickets()` + per-ticket `GET /tickets/{id}/sla`) → one dedicated endpoint, ~16.3s → ~1.2-1.9s measured.
- `GET /tickets/interactions`: 9 round trips → 2.
- `GET /tickets/{id}`: N+1 fix.
- Connection pool: `pool_size=10/max_overflow=20` → `20/30`, plus explicit `pool_timeout=10` (fail fast rather than hang near the old 30s default).
- RBAC round-trip elimination via JWT claims + in-memory TTL cache — most authenticated requests now cost one DB round trip (the business query) instead of two.

See [16-known-limitations/performance-limitations.md](../16-known-limitations/performance-limitations.md) for the important caveat that these were **reactive fixes to specific incidents**, not derived from a general capacity plan.

## Genuine open opportunities (not yet done, no design work exists)

| Opportunity | Why it might matter | Related |
|---|---|---|
| A pytest marker or per-test-engine fix for the 3-file test hang | Developer velocity, not production performance, but a real friction cost | [11-testing/integration-testing.md](../11-testing/integration-testing.md) |
| Confirming Neon's own connection ceiling against the current pool size | The pool was raised reactively without first checking Neon's own limit on the connected compute | [16-known-limitations/performance-limitations.md](../16-known-limitations/performance-limitations.md) |
| Render region alignment (currently defaults to Oregon vs. Neon's `us-east-1`) | A cross-region hop on every request, acknowledged but unfixed per `unified-frontend/CLAUDE.md` | [09-deployment/infrastructure.md](../09-deployment/infrastructure.md) |
| Multi-worker-process support for the RBAC cache / SSE manager | Currently a hard ceiling on horizontal scaling — would need Redis or Postgres `LISTEN/NOTIFY` | [16-known-limitations/technical-limitations.md](../16-known-limitations/technical-limitations.md) |

## Not measured / not confirmed

No load-testing, query-plan analysis, or documented latency percentiles exist for this system beyond the specific, manually-measured fixes listed above. See [11-testing/production-smoke-tests.md](../11-testing/production-smoke-tests.md).
