"""add composite (parent_interaction_id, is_visible) index for thread traversal

Revision ID: 8e1c4a6f2d9b
Revises: 2c5e8f1a3d6b
Create Date: 2026-07-14 00:00:00.000000

`InteractionRepository.list_thread`'s recursive CTE (added this
session — see that method's own docstring for why thread
reconstruction now walks parent_interaction_id recursively instead of
a single flat filter) runs `WHERE parent_interaction_id = :x AND
is_visible = true` once per recursion step — every reply, every level
of nesting. The existing single-column `ix_interactions_parent
_interaction_id` index lets Postgres find matching rows by parent, but
`is_visible` is then applied as a row-by-row filter after the index
lookup rather than as part of it (confirmed via EXPLAIN). A composite
index on both columns, in that order, lets a single index scan satisfy
both conditions directly — the same query shape this recursive step
always uses, not a speculative addition.

Superseded, not duplicated: `ix_interactions_parent_interaction_id`
(single-column) is left in place since other call sites (e.g. the
non-recursive is_visible-agnostic checks) can still use it as-is, and
a composite index's leading column already serves any query that only
needs `parent_interaction_id` on its own.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '8e1c4a6f2d9b'
down_revision: Union[str, None] = '2c5e8f1a3d6b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "idx_interactions_parent_visible",
        "interactions",
        ["parent_interaction_id", "is_visible"],
    )


def downgrade() -> None:
    op.drop_index("idx_interactions_parent_visible", table_name="interactions")
