"""add distribution_lists and distribution_list_members tables

Revision ID: c5e7a9f1d3b6
Revises: b3e5a7c9d1f4
Create Date: 2026-08-22 00:00:00.000002

New Distribution List / internal-group feature — see root CLAUDE.md's
"Distribution Lists" section. `name` uniqueness is enforced
case-insensitively via a functional unique index (not a plain
column-level unique=True) so "APM Support Team" and "apm support
team" can't both exist. `distribution_list_members` is a real join
table with its own surrogate PK (mirrors reporting_manager_teams'
convention), not a bare association table, since members are
added/removed individually; `UniqueConstraint(distribution_list_id,
user_id)` prevents a duplicate membership row.

Rebased onto b3e5a7c9d1f4 (add_impersonator_columns_to_ticket_audit_logs)
rather than that migration's own down_revision (a1b3c5d7e9f2) — both
were authored against the same prior head concurrently (this repo's
shared-dev-DB "teammate commits" pattern, see root CLAUDE.md), and
b3e5a7c9d1f4 landed on the live DB first, so this one is rebased to
keep the chain linear instead of leaving two heads.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c5e7a9f1d3b6'
down_revision: Union[str, None] = 'b3e5a7c9d1f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'distribution_lists',
        sa.Column('distribution_list_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.String(length=1000), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.user_id'], ),
        sa.PrimaryKeyConstraint('distribution_list_id'),
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_distribution_lists_name_lower "
        "ON distribution_lists (lower(name))"
    )

    op.create_table(
        'distribution_list_members',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('distribution_list_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['distribution_list_id'], ['distribution_lists.distribution_list_id'],
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'distribution_list_id', 'user_id', name='uq_distribution_list_member'
        ),
    )
    op.create_index(
        op.f('ix_distribution_list_members_distribution_list_id'),
        'distribution_list_members', ['distribution_list_id'], unique=False,
    )
    op.create_index(
        op.f('ix_distribution_list_members_user_id'),
        'distribution_list_members', ['user_id'], unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_distribution_list_members_user_id'),
        table_name='distribution_list_members',
    )
    op.drop_index(
        op.f('ix_distribution_list_members_distribution_list_id'),
        table_name='distribution_list_members',
    )
    op.drop_table('distribution_list_members')
    op.execute("DROP INDEX IF EXISTS ix_distribution_lists_name_lower")
    op.drop_table('distribution_lists')
