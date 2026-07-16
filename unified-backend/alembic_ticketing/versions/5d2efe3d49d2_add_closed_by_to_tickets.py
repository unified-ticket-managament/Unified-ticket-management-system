"""add closed_by to tickets

Revision ID: 5d2efe3d49d2
Revises: f2e2950742ad
Create Date: 2026-07-15 00:05:00.000000

Ticket already had `closed_at`, but nothing recorded *who* closed it.
The new dedicated Close Ticket action (InteractionService.close_ticket)
stamps this alongside closed_at; Reopen Ticket clears both back to
None, matching closed_at's own existing semantics.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5d2efe3d49d2'
down_revision: Union[str, None] = 'f2e2950742ad'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'tickets',
        sa.Column('closed_by', sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        'fk_tickets_closed_by_users',
        'tickets',
        'users',
        ['closed_by'],
        ['user_id'],
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_tickets_closed_by_users',
        'tickets',
        type_='foreignkey',
    )
    op.drop_column('tickets', 'closed_by')
