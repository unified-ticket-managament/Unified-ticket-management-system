"""make tickets.client_id nullable, add client_company_id

Revision ID: d3e5f7a9b1c3
Revises: c2d4e6f8a0b2
Create Date: 2026-07-06 00:00:00.000002

tickets.client_id was a NOT NULL FK to an individual `users` row —
that model no longer holds now that clients are companies, not
platform users. It's relaxed to nullable (existing rows keep their
value) and superseded by client_company_id going forward. Both
columns are kept side by side; consolidating them is out of scope
here (see plan risks/notes).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd3e5f7a9b1c3'
down_revision: Union[str, None] = 'c2d4e6f8a0b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'tickets',
        'client_id',
        existing_type=sa.UUID(),
        nullable=True,
    )

    op.add_column(
        'tickets',
        sa.Column('client_company_id', sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        'fk_tickets_client_company_id_clients',
        'tickets',
        'clients',
        ['client_company_id'],
        ['client_id'],
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_tickets_client_company_id_clients',
        'tickets',
        type_='foreignkey',
    )
    op.drop_column('tickets', 'client_company_id')

    op.alter_column(
        'tickets',
        'client_id',
        existing_type=sa.UUID(),
        nullable=False,
    )
