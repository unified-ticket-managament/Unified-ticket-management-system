"""add indexes for the ticket-list page's real server-side pagination/sort/search

Revision ID: 1a3c5e7f9b2d
Revises: 8e1c4a6f2d9b
Create Date: 2026-07-13 00:00:00.000000

The ticket-list page (TicketsListPage.tsx) used to fetch every visible
ticket unbounded and sort/filter/paginate entirely client-side — this
session moved it to real server-side pagination
(TicketRepository.list_visible_page), which means three query shapes
that were previously never actually executed against the database are
now live, real, per-request queries:

1. `ORDER BY updated_at DESC` — the page's default sort, and also used
   by the Dashboard's "recent tickets" query. `tickets` already has a
   plain index on `created_at` (see b8d0f2a4c6e8) but nothing on
   `updated_at`, the column actually sorted by default.
2. The "Open Pool" tab's exact filter — `agent_id IS NULL AND
   current_status = 'OPEN'`, ordered by `updated_at DESC` — is now a
   real, frequently-hit query (every agent's default landing tab), not
   dead code. A partial index scoped to precisely this condition,
   covering the sort column, turns it into an index scan instead of a
   sequential scan once the table is large enough for the planner to
   prefer that.
3. `title ILIKE '%term%'` — the ticket-list search box, now wired to a
   real backend query (`Ticket.title.ilike(...)`) instead of being
   silently unused (the frontend never sent a `search` param before
   this session). A leading-wildcard ILIKE can't use a plain B-tree
   index regardless of table size; a pg_trgm GIN index lets Postgres
   pick an index scan for this exact pattern instead, same idiom as
   9d2e4f6a8c1b's `interactions.subject` trigram index (pg_trgm is
   already enabled by that migration, so this one only adds the index
   itself, not the extension).
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '1a3c5e7f9b2d'
down_revision: Union[str, None] = '8e1c4a6f2d9b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_tickets_updated_at ON tickets (updated_at DESC)"
    )
    op.execute(
        "CREATE INDEX ix_tickets_pool_view ON tickets (updated_at DESC) "
        "WHERE agent_id IS NULL AND current_status = 'OPEN'"
    )
    op.execute(
        "CREATE INDEX ix_tickets_title_trgm ON tickets USING gin (title gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX ix_tickets_title_trgm")
    op.execute("DROP INDEX ix_tickets_pool_view")
    op.execute("DROP INDEX ix_tickets_updated_at")
