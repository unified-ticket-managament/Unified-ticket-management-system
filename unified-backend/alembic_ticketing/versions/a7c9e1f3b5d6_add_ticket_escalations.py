"""add ticket_escalations table and sla_policies.escalation_ack_target_minutes

Revision ID: a7c9e1f3b5d6
Revises: 1a3c5e7f9b2d
Create Date: 2026-07-13 00:00:00.000000

New internal escalation workflow (TicketEscalation) — deliberately a
separate table from resolution_slas/first_response_slas, not a column
added to either: the whole point of this feature is that escalating a
ticket must never touch the existing Resolution SLA clock's own
started_at/due_at/status columns, so keeping ownership/acknowledgment
tracking in its own table makes "never restarts the original SLA"
true by construction rather than by discipline.

Also adds sla_policies.escalation_ack_target_minutes (one per
priority, same row-per-TicketPriority table the two existing SLA
targets already live on) — how long a given level's owner has to
acknowledge before the sweep auto-advances to the next level. Backfilled
per-priority (HIGH gets the shortest window) rather than one global
default, mirroring how first_response/resolution targets already vary
by priority on this same table.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a7c9e1f3b5d6'
down_revision: Union[str, None] = '1a3c5e7f9b2d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TICKET_ESCALATION_LEVEL_ENUM = postgresql.ENUM(
    "TEAM_LEAD", "MANAGER", "SITE_LEAD",
    name="ticket_escalation_level_enum",
)

TICKET_ESCALATION_STATUS_ENUM = postgresql.ENUM(
    "ACTIVE", "ACKNOWLEDGED", "CLOSED",
    name="ticket_escalation_status_enum",
)

# priority -> ack window, in minutes. Shorter for HIGH since an ignored
# high-priority escalation is more costly than an ignored low-priority
# one; kept modest across the board so a demo/local sweep run can
# actually observe an auto-advance without waiting hours.
ESCALATION_ACK_TARGET_MINUTES_BY_PRIORITY = {
    "HIGH": 15,
    "MEDIUM": 30,
    "LOW": 60,
}


def upgrade() -> None:
    bind = op.get_bind()
    TICKET_ESCALATION_LEVEL_ENUM.create(bind, checkfirst=True)
    TICKET_ESCALATION_STATUS_ENUM.create(bind, checkfirst=True)

    op.create_table(
        'ticket_escalations',
        sa.Column('escalation_id', sa.UUID(), nullable=False),
        sa.Column('ticket_id', sa.UUID(), nullable=False),
        sa.Column('resolution_sla_id', sa.UUID(), nullable=True),
        sa.Column('level', postgresql.ENUM(
            "TEAM_LEAD", "MANAGER", "SITE_LEAD",
            name="ticket_escalation_level_enum", create_type=False,
        ), nullable=False),
        sa.Column('status', postgresql.ENUM(
            "ACTIVE", "ACKNOWLEDGED", "CLOSED",
            name="ticket_escalation_status_enum", create_type=False,
        ), nullable=False),
        sa.Column('owner_ids', postgresql.JSONB(), nullable=False),
        sa.Column('triggered_by', sa.String(length=20), nullable=False),
        sa.Column('triggered_by_user_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('level_started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ack_due_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('acknowledged_by', sa.UUID(), nullable=True),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('closed_reason', sa.String(length=30), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['ticket_id'], ['tickets.ticket_id']),
        sa.ForeignKeyConstraint(['resolution_sla_id'], ['resolution_slas.resolution_sla_id']),
        sa.ForeignKeyConstraint(['triggered_by_user_id'], ['users.user_id']),
        sa.ForeignKeyConstraint(['acknowledged_by'], ['users.user_id']),
        sa.PrimaryKeyConstraint('escalation_id'),
    )
    op.create_index(
        op.f('ix_ticket_escalations_ticket_id'), 'ticket_escalations', ['ticket_id'], unique=False
    )
    op.create_index(
        op.f('ix_ticket_escalations_status'), 'ticket_escalations', ['status'], unique=False
    )
    op.create_index(
        op.f('ix_ticket_escalations_ack_due_at'), 'ticket_escalations', ['ack_due_at'], unique=False
    )
    op.create_index(
        'ix_ticket_escalations_status_ack_due_at',
        'ticket_escalations', ['status', 'ack_due_at'], unique=False,
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_ticket_escalations_one_active_per_ticket "
        "ON ticket_escalations (ticket_id) WHERE status != 'CLOSED'"
    )

    op.add_column(
        'sla_policies',
        sa.Column('escalation_ack_target_minutes', sa.Integer(), nullable=True),
    )
    sla_policies = sa.table(
        'sla_policies',
        sa.column('priority', sa.String()),
        sa.column('escalation_ack_target_minutes', sa.Integer()),
    )
    for priority, minutes in ESCALATION_ACK_TARGET_MINUTES_BY_PRIORITY.items():
        op.execute(
            sla_policies.update()
            .where(sla_policies.c.priority == priority)
            .values(escalation_ack_target_minutes=minutes)
        )
    op.alter_column('sla_policies', 'escalation_ack_target_minutes', nullable=False)


def downgrade() -> None:
    op.drop_column('sla_policies', 'escalation_ack_target_minutes')

    op.execute("DROP INDEX ix_ticket_escalations_one_active_per_ticket")
    op.drop_index('ix_ticket_escalations_status_ack_due_at', table_name='ticket_escalations')
    op.drop_index(op.f('ix_ticket_escalations_ack_due_at'), table_name='ticket_escalations')
    op.drop_index(op.f('ix_ticket_escalations_status'), table_name='ticket_escalations')
    op.drop_index(op.f('ix_ticket_escalations_ticket_id'), table_name='ticket_escalations')
    op.drop_table('ticket_escalations')

    bind = op.get_bind()
    TICKET_ESCALATION_STATUS_ENUM.drop(bind, checkfirst=True)
    TICKET_ESCALATION_LEVEL_ENUM.drop(bind, checkfirst=True)
