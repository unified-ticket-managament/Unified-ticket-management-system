"""add inbox_email to categories

Revision ID: b3e5f7a9c1d4
Revises: b2d4f6a8c0e3
Create Date: 2026-08-22 00:00:00.000000

Adds a CATEGORY shared-inbox address (e.g. apm@company.com), mirroring
the existing Client.inbox_email column/pattern in the ticketing chain.
A category with this set becomes a routable CATEGORY mailbox: inbound
mail landing on this address resolves to this category (and, via the
existing reporting_manager_teams mapping, its Account Manager(s))
instead of going through client resolution — see
app/ticketing/services/email_service.py.

Nullable/optional (most categories have no mailbox of their own) and
unique among the rows that do have a value. Purely additive — every
existing category row gets NULL, no data migration needed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3e5f7a9c1d4'
down_revision: Union[str, None] = 'b2d4f6a8c0e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('categories', sa.Column('inbox_email', sa.String(length=255), nullable=True))
    op.create_unique_constraint('uq_categories_inbox_email', 'categories', ['inbox_email'])


def downgrade() -> None:
    op.drop_constraint('uq_categories_inbox_email', 'categories', type_='unique')
    op.drop_column('categories', 'inbox_email')
