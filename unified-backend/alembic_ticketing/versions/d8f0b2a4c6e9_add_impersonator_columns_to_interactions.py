"""add impersonator columns to interactions

Revision ID: d8f0b2a4c6e9
Revises: c7e9a1b3d5f8
Create Date: 2026-08-24 00:00:00.000000

Companion to b3e5a7c9d1f4 (which adds the same two columns to
ticket_audit_logs) and alembic_rbac's b2d4f6a8c0e3 (audit_logs) —
brings `interactions` in line with a column pair that had already
been added directly on a downstream database outside of migration
history. actor semantics on Interaction (performed_by) keep their
existing meaning (the target/effective performer) — these two new
columns separately record the real actor when a Super Admin is
impersonating someone. NULL for every ordinary row.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd8f0b2a4c6e9'
down_revision: Union[str, None] = 'c7e9a1b3d5f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'interactions',
        sa.Column('impersonator_id', postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        'interactions',
        sa.Column('impersonator_name', sa.String(length=255), nullable=True),
    )
    op.create_foreign_key(
        'fk_interactions_impersonator_id_users',
        'interactions', 'users',
        ['impersonator_id'], ['user_id'],
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_interactions_impersonator_id_users',
        'interactions', type_='foreignkey',
    )
    op.drop_column('interactions', 'impersonator_name')
    op.drop_column('interactions', 'impersonator_id')
