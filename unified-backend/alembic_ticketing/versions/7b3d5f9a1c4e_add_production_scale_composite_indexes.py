"""add composite indexes for production-scale interactions/inbox query patterns

Revision ID: 7b3d5f9a1c4e
Revises: 4f7a9c2e6b8d
Create Date: 2026-07-13 00:00:00.000001

Both target real, existing query shapes — not speculative indexes:

1. `(ticket_id, created_at DESC)` on `interactions`. The paginated
   Interactions-page/Timeline query filters on `ticket_id IN (...)`
   (a narrow subset for Account-Manager/Team-Lead/Staff-scoped
   callers) then orders by `created_at DESC`. Today (73 tickets total)
   the planner satisfies this via a global backward scan of
   `ix_interactions_created_at` plus a per-row ticket membership
   check — fine when "the ticket subset" is most of the table. At
   production scale, a caller scoped to a small fraction of all
   tickets (the common case — an Account Manager owns a handful of
   clients, not the whole business) would otherwise force scanning a
   large share of the *entire* interactions table before accumulating
   `limit` matching rows. This composite index lets Postgres satisfy
   both the filter and the sort directly per ticket_id.
2. `(status, received_at DESC)` on `interactions`, partial WHERE
   `interaction_type = 'EMAIL' AND parent_interaction_id IS NULL AND
   is_visible`. `InteractionRepository.list_inbox`'s "pending" view —
   the very first thing every agent sees on login — filters on this
   exact combination. The existing `ix_interactions_inbox_base`
   partial index (migration 9d2e4f6a8c1b) covers the shared base
   filter across all Mail views; this adds `status` as a second
   covered predicate specifically for the highest-traffic view
   (pending/replied/archived all filter on `status`).

Both are additive B-tree indexes — no data changes, safe with no
downtime.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '7b3d5f9a1c4e'
down_revision: Union[str, None] = '4f7a9c2e6b8d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "idx_interactions_ticket_created",
        "interactions",
        ["ticket_id", sa.text("created_at DESC")],
    )
    op.execute(
        "CREATE INDEX idx_interactions_inbox_status "
        "ON interactions (status, received_at DESC) "
        "WHERE interaction_type = 'EMAIL' AND parent_interaction_id IS NULL "
        "AND is_visible = true"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_interactions_inbox_status")
    op.drop_index("idx_interactions_ticket_created", table_name="interactions")
