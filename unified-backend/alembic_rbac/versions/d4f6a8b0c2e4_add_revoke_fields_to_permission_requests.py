"""add revoked_by/revoked_at/revoke_reason to permission_requests

Revision ID: d4f6a8b0c2e4
Revises: b3d5f7a9c1e2
Create Date: 2026-07-17 01:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4f6a8b0c2e4'
down_revision: Union[str, None] = 'b3d5f7a9c1e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'permission_requests',
        sa.Column('revoked_by', sa.UUID(), nullable=True),
    )
    op.add_column(
        'permission_requests',
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'permission_requests',
        sa.Column('revoke_reason', sa.Text(), nullable=True),
    )
    op.create_foreign_key(
        'fk_permission_requests_revoked_by_users',
        'permission_requests',
        'users',
        ['revoked_by'],
        ['user_id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_permission_requests_revoked_by_users',
        'permission_requests',
        type_='foreignkey',
    )
    op.drop_column('permission_requests', 'revoke_reason')
    op.drop_column('permission_requests', 'revoked_at')
    op.drop_column('permission_requests', 'revoked_by')
