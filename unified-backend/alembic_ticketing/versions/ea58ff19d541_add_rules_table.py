"""add rules table

Revision ID: ea58ff19d541
Revises: c9e1a3b5d7f0
Create Date: 2026-08-07 18:19:43.962043

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'ea58ff19d541'
down_revision: Union[str, None] = 'c9e1a3b5d7f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# NOTE: the autogenerate diff this migration started from also proposed
# dropping several unrelated indexes/server-defaults (ix_tickets_*,
# ix_interactions_*, sla_policies.*_percentage server defaults) that are
# real, deliberately-added prior work simply not yet declared on the
# current SQLAlchemy models — the same pre-existing drift the
# d33a0758e3c4/escalation_handling_slas migration already documented and
# stripped out. Left alone here too; this migration only adds `rules`.


def upgrade() -> None:
    op.create_table(
        'rules',
        sa.Column('rule_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('category', sa.String(length=20), nullable=False),
        sa.Column('is_enabled', sa.Boolean(), nullable=False),
        sa.Column('conditions', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('exceptions', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('actions', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('stop_processing', sa.Boolean(), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.user_id'], ),
        sa.PrimaryKeyConstraint('rule_id'),
    )
    op.create_index(op.f('ix_rules_category'), 'rules', ['category'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_rules_category'), table_name='rules')
    op.drop_table('rules')
