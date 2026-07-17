"""add reporting_manager_teams table

Revision ID: 3f9efae8e1ae
Revises: e6a8c0d2f4b6
Create Date: 2026-07-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '3f9efae8e1ae'
down_revision: Union[str, None] = 'e6a8c0d2f4b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'reporting_manager_teams',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('account_manager_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('category_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('assigned_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('assigned_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['account_manager_id'], ['users.user_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['category_id'], ['categories.category_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['assigned_by'], ['users.user_id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('account_manager_id', 'category_id', name='uq_reporting_manager_team'),
    )
    op.create_index(
        op.f('ix_reporting_manager_teams_account_manager_id'),
        'reporting_manager_teams', ['account_manager_id'], unique=False,
    )
    op.create_index(
        op.f('ix_reporting_manager_teams_category_id'),
        'reporting_manager_teams', ['category_id'], unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_reporting_manager_teams_category_id'), table_name='reporting_manager_teams')
    op.drop_index(op.f('ix_reporting_manager_teams_account_manager_id'), table_name='reporting_manager_teams')
    op.drop_table('reporting_manager_teams')
