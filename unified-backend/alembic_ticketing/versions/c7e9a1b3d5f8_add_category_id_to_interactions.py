"""add category_id to interactions

Revision ID: c7e9a1b3d5f8
Revises: d6f8b0a2e4c7
Create Date: 2026-08-22 00:00:00.000001

CATEGORY-mailbox counterpart to the existing interactions.client_id
column. Mail landing at a category's own shared inbox
(categories.inbox_email, added alongside this in the alembic_rbac
chain) resolves to a category instead of a client — see
app/ticketing/services/email_service.py's new category-mailbox branch.

Nullable, purely additive — every existing interaction row gets NULL.
Cross-chain FK into `categories` (an alembic_rbac-owned table) mirrors
the pre-existing clients.account_manager_id -> users.user_id pattern;
both chains share one physical Postgres database.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c7e9a1b3d5f8'
down_revision: Union[str, None] = 'd6f8b0a2e4c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'interactions',
        sa.Column('category_id', sa.UUID(), nullable=True),
    )
    op.create_index(
        op.f('ix_interactions_category_id'),
        'interactions',
        ['category_id'],
    )
    op.create_foreign_key(
        'fk_interactions_category_id_categories',
        'interactions',
        'categories',
        ['category_id'],
        ['category_id'],
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_interactions_category_id_categories',
        'interactions',
        type_='foreignkey',
    )
    op.drop_index(op.f('ix_interactions_category_id'), table_name='interactions')
    op.drop_column('interactions', 'category_id')
