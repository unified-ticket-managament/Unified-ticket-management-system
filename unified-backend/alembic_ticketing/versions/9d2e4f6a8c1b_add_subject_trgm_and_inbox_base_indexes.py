"""add pg_trgm index on interactions.subject and a base-filter partial index for the inbox query

Revision ID: 9d2e4f6a8c1b
Revises: 6a1d3f5b7c9e
Create Date: 2026-07-13 00:00:00.000000

Two independent, additive indexes, both matching real query shapes
already in the code (no query changes needed to benefit from either):

1. `GET /tickets/interactions` and `GET /inbox` both added a `search`
   param this session that filters on `Interaction.subject.ilike(f"%{term}%")`
   — a leading-wildcard LIKE, which a plain B-tree index can never use
   regardless of table size (confirmed via EXPLAIN: currently a Seq
   Scan, cheap only because the table is small today). A pg_trgm GIN
   index lets Postgres use an index scan for this exact pattern
   instead, with no application code change — Postgres automatically
   picks it up for `ILIKE '%term%'`.
2. `InteractionRepository.list_inbox` applies `is_visible = true AND
   interaction_type = 'EMAIL' AND parent_interaction_id IS NULL`
   unconditionally, for every view (pending/replied/ticketed/archived/
   all) — this exact 3-column combination is the exact base filter of
   GET /inbox, the busiest endpoint on the Mail tab. A partial index
   scoped to precisely this condition, covering the `received_at DESC`
   order the query always sorts by, turns the base scan into an index
   scan instead of a full-table seq scan once the table is large
   enough for the planner to prefer it.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '9d2e4f6a8c1b'
down_revision: Union[str, None] = '6a1d3f5b7c9e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX ix_interactions_subject_trgm "
        "ON interactions USING gin (subject gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_interactions_inbox_base "
        "ON interactions (received_at DESC) "
        "WHERE is_visible = true AND interaction_type = 'EMAIL' "
        "AND parent_interaction_id IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX ix_interactions_inbox_base")
    op.execute("DROP INDEX ix_interactions_subject_trgm")
    # Extension left installed on downgrade — dropping it is riskier
    # than leaving an unused extension in place if anything else ever
    # comes to depend on it, and CREATE EXTENSION IF NOT EXISTS on the
    # next upgrade is a no-op either way.
