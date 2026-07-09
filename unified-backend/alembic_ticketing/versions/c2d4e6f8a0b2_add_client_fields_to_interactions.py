"""add client_id, parent_interaction_id, received_at to interactions

Revision ID: c2d4e6f8a0b2
Revises: b1c3d5e7f9a1
Create Date: 2026-07-06 00:00:00.000001

client_id / parent_interaction_id / received_at become real columns
(not payload-only) because the AM inbox query filters and orders on
them directly. received_at is backfilled from created_at so existing
rows still sort correctly under the new SLA-clock ordering.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c2d4e6f8a0b2'
down_revision: Union[str, None] = 'b1c3d5e7f9a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'interactions',
        sa.Column('client_id', sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        'fk_interactions_client_id_clients',
        'interactions',
        'clients',
        ['client_id'],
        ['client_id'],
    )

    op.add_column(
        'interactions',
        sa.Column('parent_interaction_id', sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        'fk_interactions_parent_interaction_id_interactions',
        'interactions',
        'interactions',
        ['parent_interaction_id'],
        ['interaction_id'],
    )

    op.add_column(
        'interactions',
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=True),
    )

    # Backfill: every existing row's arrival time is approximated by
    # its created_at (they were the same moment before this column
    # existed).
    op.execute("UPDATE interactions SET received_at = created_at WHERE received_at IS NULL")


def downgrade() -> None:
    op.drop_column('interactions', 'received_at')
    op.drop_constraint(
        'fk_interactions_parent_interaction_id_interactions',
        'interactions',
        type_='foreignkey',
    )
    op.drop_column('interactions', 'parent_interaction_id')
    op.drop_constraint(
        'fk_interactions_client_id_clients',
        'interactions',
        type_='foreignkey',
    )
    op.drop_column('interactions', 'client_id')
