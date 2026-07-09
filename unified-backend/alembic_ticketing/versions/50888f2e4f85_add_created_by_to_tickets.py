"""add created_by to tickets

Revision ID: 50888f2e4f85
Revises: c6f212b05143
Create Date: 2026-07-02 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '50888f2e4f85'
down_revision: Union[str, None] = 'c6f212b05143'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'tickets',
        sa.Column('created_by', sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        'fk_tickets_created_by_users',
        'tickets',
        'users',
        ['created_by'],
        ['user_id'],
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_tickets_created_by_users',
        'tickets',
        type_='foreignkey',
    )
    op.drop_column('tickets', 'created_by')
