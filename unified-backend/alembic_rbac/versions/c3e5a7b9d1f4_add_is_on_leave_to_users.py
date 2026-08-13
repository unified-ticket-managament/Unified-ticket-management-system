"""add is_on_leave to users

Revision ID: c3e5a7b9d1f4
Revises: b2d4f6a8c0e2
Create Date: 2026-08-13 00:00:00.000000

Backs the Leave toggle on the user profile/detail view — a purely
display-only indicator (see shared_models.models.User.is_on_leave's
own docstring). Not RBAC-relevant: never bumps permission_version,
never added to any eligibility/authorization check.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3e5a7b9d1f4'
down_revision: Union[str, None] = 'b2d4f6a8c0e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column(
            'is_on_leave',
            sa.Boolean(),
            nullable=False,
            server_default='false',
        ),
    )


def downgrade() -> None:
    op.drop_column('users', 'is_on_leave')
