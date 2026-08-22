"""add impersonator columns to ticket_audit_logs

Revision ID: b3e5a7c9d1f4
Revises: a1b3c5d7e9f2
Create Date: 2026-08-22 00:00:00.000000

Companion to alembic_rbac's b2d4f6a8c0e3 (which adds the same two
columns to that chain's own audit_logs table, plus the new
impersonation_sessions table) — see
app/core/impersonation_context.py and
app/ticketing/repositories/audit_log_repository.py for how these are
populated. actor_id/actor_name keep their existing meaning (the
target/effective performer, whoever's identity actually governed the
request) — these two new columns separately record the real actor
when a Super Admin is impersonating someone. NULL for every ordinary
row.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b3e5a7c9d1f4'
down_revision: Union[str, None] = 'a1b3c5d7e9f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'ticket_audit_logs',
        sa.Column('impersonator_id', postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        'ticket_audit_logs',
        sa.Column('impersonator_name', sa.String(length=255), nullable=True),
    )
    op.create_foreign_key(
        'fk_ticket_audit_logs_impersonator_id_users',
        'ticket_audit_logs', 'users',
        ['impersonator_id'], ['user_id'],
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_ticket_audit_logs_impersonator_id_users',
        'ticket_audit_logs', type_='foreignkey',
    )
    op.drop_column('ticket_audit_logs', 'impersonator_name')
    op.drop_column('ticket_audit_logs', 'impersonator_id')
