# Database

- [database-overview.md](database-overview.md) — one Postgres database, two independent migration histories
- [er-diagram.md](er-diagram.md) — entity relationships, visually
- [relationships.md](relationships.md) — foreign keys, especially the ones crossing the two Alembic chains
- [indexes.md](indexes.md) — indexes and constraints that encode real business rules
- [migrations.md](migrations.md) — both Alembic chains, their heads, and notable migrations
- [data-retention.md](data-retention.md) — what's soft-deleted, what's append-only, what's hard-deleted
- [tables/](tables/) — column-by-column reference for every significant table

All content here is sourced directly from the actual model files and migration history (`unified-backend/app/rbac/models/`, `app/ticketing/models/`, `shared_models/shared_models/models/`, `alembic_rbac/`, `alembic_ticketing/`) — not inferred from naming conventions alone.
