"""add permission_version to users

Revision ID: b3d5f7a9c1e2
Revises: a1b2c3d4e5f6
Create Date: 2026-07-13 00:00:00.000000

Backs the in-memory RBAC cache's invalidation key (see
unified-backend/app/core/rbac_cache.py and app/dependencies/auth.py) —
bumped whenever a user's role/category/manager/teamlead/activation
state changes, whenever a personal permission override is granted or
revoked, or (bulk, one UPDATE, not a per-row loop) whenever the user's
own role's permission set changes. A stale JWT's claimed
permission_version no longer matching the DB's live value is what
rejects an outdated cached session without ever needing to scan or
actively invalidate the cache itself.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3d5f7a9c1e2'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column(
            'permission_version',
            sa.Integer(),
            nullable=False,
            server_default='1',
        ),
    )


def downgrade() -> None:
    op.drop_column('users', 'permission_version')
