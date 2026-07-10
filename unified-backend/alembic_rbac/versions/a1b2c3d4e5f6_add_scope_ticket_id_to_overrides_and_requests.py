"""add scope_ticket_id to user_permission_overrides and permission_requests

Revision ID: a1b2c3d4e5f6
Revises: f3a7c9e1b5d2
Create Date: 2026-07-09 23:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'f3a7c9e1b5d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'user_permission_overrides',
        sa.Column('scope_ticket_id', sa.UUID(), nullable=True),
    )
    op.add_column(
        'permission_requests',
        sa.Column('scope_ticket_id', sa.UUID(), nullable=True),
    )

    # Rebuild the active-override uniqueness constraint to include
    # scope_ticket_id, COALESCE'd to a sentinel so two *global* grants
    # (scope_ticket_id IS NULL) for the same user+permission still
    # collide — a plain 3-column unique index would treat every NULL
    # as distinct from every other NULL and let duplicate global
    # grants through.
    op.drop_index(
        'ix_user_permission_overrides_active_unique',
        table_name='user_permission_overrides',
    )
    op.execute(
        """
        CREATE UNIQUE INDEX ix_user_permission_overrides_active_unique
        ON user_permission_overrides (
            user_id,
            permission_id,
            COALESCE(scope_ticket_id, '00000000-0000-0000-0000-000000000000'::uuid)
        )
        WHERE revoked_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS ix_user_permission_overrides_active_unique"
    )
    op.create_index(
        'ix_user_permission_overrides_active_unique',
        'user_permission_overrides',
        ['user_id', 'permission_id'],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    op.drop_column('permission_requests', 'scope_ticket_id')
    op.drop_column('user_permission_overrides', 'scope_ticket_id')
