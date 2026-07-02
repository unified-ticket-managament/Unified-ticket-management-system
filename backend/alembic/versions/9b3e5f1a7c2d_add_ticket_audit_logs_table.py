"""add ticket_audit_logs table

Revision ID: 9b3e5f1a7c2d
Revises: 7a1f9c4d2e6b
Create Date: 2026-07-02 00:00:00.000000

Named `ticket_audit_logs`, not `audit_logs` — an unrelated
`audit_logs` table (different columns, different owner) already
exists in this shared database.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '9b3e5f1a7c2d'
down_revision: Union[str, None] = '7a1f9c4d2e6b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ticket_audit_logs',
        sa.Column('audit_id', sa.UUID(), nullable=False),
        sa.Column(
            'entity_type',
            sa.Enum(
                'TICKET', 'INTERACTION', 'ATTACHMENT', 'CLIENT', 'USER',
                name='audit_entity_type_enum',
            ),
            nullable=False,
        ),
        sa.Column('entity_id', sa.UUID(), nullable=False),
        sa.Column(
            'event_type',
            sa.Enum(
                'TICKET_CREATED', 'TICKET_UPDATED', 'STATUS_CHANGED',
                'PRIORITY_CHANGED', 'AGENT_TRANSFERRED', 'INTERACTION_HIDDEN',
                'ATTACHMENT_UPLOADED', 'NOTE_ADDED', 'REPLY_ADDED',
                name='audit_event_type_enum',
            ),
            nullable=False,
        ),
        sa.Column('changed_by', sa.UUID(), nullable=True),
        sa.Column('old_values', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('new_values', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['changed_by'], ['users.user_id'],
            name='fk_ticket_audit_logs_changed_by_users',
        ),
        sa.PrimaryKeyConstraint('audit_id'),
    )

    op.execute(
        "CREATE INDEX idx_audit_entity ON ticket_audit_logs (entity_type, entity_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX idx_audit_user ON ticket_audit_logs (changed_by, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX idx_audit_event_type ON ticket_audit_logs (event_type, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_audit_event_type")
    op.execute("DROP INDEX IF EXISTS idx_audit_user")
    op.execute("DROP INDEX IF EXISTS idx_audit_entity")
    op.drop_table('ticket_audit_logs')
    op.execute("DROP TYPE IF EXISTS audit_event_type_enum")
    op.execute("DROP TYPE IF EXISTS audit_entity_type_enum")
