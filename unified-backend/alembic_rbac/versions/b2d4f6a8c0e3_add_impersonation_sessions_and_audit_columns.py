"""add impersonation_sessions table and audit_logs impersonator columns

Revision ID: b2d4f6a8c0e3
Revises: a4c6e8b0d2f5
Create Date: 2026-08-22 00:00:00.000000

Adds the database-backed session behind Super Admin "Login as User"
impersonation (see app/rbac/models/impersonation_session.py and
app/rbac/services/impersonation_service.py) — a stateless JWT alone
can't be revoked before its own exp, so app/dependencies/auth.py checks
this table on every request carrying an impersonation_session_id
claim, in addition to normal token validation.

Also adds impersonator_id/impersonator_name to this chain's own
audit_logs table, so a user.*/role.*/permission.*/auth.* row written
while a Super Admin is impersonating someone records the real actor
too, not just the target whose identity actually governed the request
(actor_id/actor_name-equivalent columns keep their existing meaning
unchanged). alembic_ticketing's own ticket_audit_logs table gets the
identical two columns via a separate migration in that chain.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b2d4f6a8c0e3'
down_revision: Union[str, None] = 'a4c6e8b0d2f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'impersonation_sessions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('actor_user_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('target_user_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='ACTIVE'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['actor_user_id'], ['users.user_id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['target_user_id'], ['users.user_id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_impersonation_sessions_actor_user_id'),
        'impersonation_sessions', ['actor_user_id'], unique=False,
    )
    op.create_index(
        op.f('ix_impersonation_sessions_target_user_id'),
        'impersonation_sessions', ['target_user_id'], unique=False,
    )

    op.add_column(
        'audit_logs',
        sa.Column('impersonator_id', postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        'audit_logs',
        sa.Column('impersonator_name', sa.String(length=255), nullable=True),
    )
    op.create_foreign_key(
        'fk_audit_logs_impersonator_id_users',
        'audit_logs', 'users',
        ['impersonator_id'], ['user_id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_audit_logs_impersonator_id_users', 'audit_logs', type_='foreignkey')
    op.drop_column('audit_logs', 'impersonator_name')
    op.drop_column('audit_logs', 'impersonator_id')

    op.drop_index(op.f('ix_impersonation_sessions_target_user_id'), table_name='impersonation_sessions')
    op.drop_index(op.f('ix_impersonation_sessions_actor_user_id'), table_name='impersonation_sessions')
    op.drop_table('impersonation_sessions')
