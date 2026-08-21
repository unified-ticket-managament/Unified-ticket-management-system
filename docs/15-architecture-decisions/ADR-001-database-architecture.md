# ADR-001: One Database, Two Independent Migration Histories

**Status**: Accepted (implemented, in production use)
**Date**: Confirmed as of the backend consolidation (predates this documentation pass; exact original date not recorded in the repository)

## Context

UTMS began as two separate services (RBAC and Ticketing), each with its own backend and its own migration history. A backend-consolidation effort merged both into one FastAPI process (`unified-backend`) sharing one PostgreSQL database (Neon).

## Problem

Should the merge also unify the two services' Alembic migration histories into one chain?

## Options Considered

1. **Merge into one Alembic chain** — simpler mental model, one `alembic upgrade head` command.
2. **Keep two independent chains** (`alembic_rbac`, `alembic_ticketing`), each with its own `version_table`, applied in sequence against the shared database.

## Decision

Keep two independent chains (option 2).

## Reason

Each domain's migration history predates the merge and reflects real, already-applied schema evolution specific to that domain. Forcing a merge would require either rewriting history (risky against a live production database) or accepting one artificial "merge" migration with no real content. Keeping them separate also preserves each domain's ability to evolve its own schema without coordinating a single shared migration sequence number space.

## Trade-offs

- **Cost**: cross-chain foreign keys must be handled asymmetrically — a ticketing table can FK into `users` (RBAC-owned), but an RBAC table can never FK into a ticketing table, to avoid coupling migration ordering (see [06-database/relationships.md](../06-database/relationships.md)).
- **Cost**: two migrations in different chains can share an identical revision id with no practical consequence (confirmed to have happened once) — a subtle trap if ever scripting against revision ids assuming global uniqueness.
- **Benefit**: each domain's `alembic revision --autogenerate` only ever diffs its own tables (`include_object` filtering in each chain's `env.py`), keeping autogenerate output focused and reviewable.

## Consequences

Migrations must always be run in the order `alembic_rbac` then `alembic_ticketing` (documented everywhere: `scripts/start.sh`, the EC2 deploy workflow, this documentation set) — order only matters against a genuinely empty database, but the convention is followed unconditionally for safety.

## Related Components

`unified-backend/alembic_rbac/`, `unified-backend/alembic_ticketing/`, `shared_models/` (the one genuinely shared model definition both chains' domains import).
