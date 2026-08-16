"""add user_categories table

Revision ID: f1a3c5e7b9d2
Revises: e5f7a9c1b3d5
Create Date: 2026-08-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f1a3c5e7b9d2'
down_revision: Union[str, None] = 'e5f7a9c1b3d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'user_categories',
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('category_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('assigned_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('assigned_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['category_id'], ['categories.category_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['assigned_by'], ['users.user_id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('user_id', 'category_id'),
    )
    op.create_index(
        op.f('ix_user_categories_category_id'),
        'user_categories', ['category_id'], unique=False,
    )

    # Backfill: every existing user's current single category becomes
    # their first (and, pre-existing-data-wise, only) row in the new
    # join table. `users.category_id` itself is left completely
    # untouched — this table is additive, not a migration off of it.
    # ON CONFLICT DO NOTHING makes this safe to re-run.
    op.execute(
        """
        INSERT INTO user_categories (user_id, category_id, assigned_at)
        SELECT user_id, category_id, now()
        FROM users
        WHERE category_id IS NOT NULL
        ON CONFLICT (user_id, category_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_user_categories_category_id'), table_name='user_categories')
    op.drop_table('user_categories')
