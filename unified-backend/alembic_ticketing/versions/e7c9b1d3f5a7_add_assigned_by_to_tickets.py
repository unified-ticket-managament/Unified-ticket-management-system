"""add assigned_by to tickets

Revision ID: e7c9b1d3f5a7
Revises: c4d6e8f0a2b4
Create Date: 2026-08-12 00:00:00.000000

"Assigned By" used to be derived at read time from the ticket_audit_logs
trail (the latest TICKET_CREATED/TICKET_CLAIMED/AGENT_TRANSFERRED row
whose new_values carried an agent_id). It's now a real, persisted
column, stamped explicitly by every code path that writes agent_id
(InteractionService.transfer_agent/claim_ticket,
InboxTicketService.create_ticket_from_interaction) instead of
re-derived on every read.

Nullable, no server_default — an existing ticket's assignment history
doesn't disappear (ticket_audit_logs is untouched), so this migration
backfills every ticket's assigned_by from the exact same derivation the
old read-time logic used (latest qualifying audit row's actor_id),
one time, as a plain data migration. Any ticket with no such row (e.g.
still unclaimed, or older seed data with no assignment audit trail at
all) is safely left NULL rather than guessed at.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7c9b1d3f5a7'
down_revision: Union[str, None] = 'c4d6e8f0a2b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'tickets',
        sa.Column('assigned_by', sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        'fk_tickets_assigned_by_users',
        'tickets',
        'users',
        ['assigned_by'],
        ['user_id'],
    )

    # One-time backfill — mirrors the old derivation exactly: for each
    # ticket, the most recent TICKET_CREATED/TICKET_CLAIMED/
    # AGENT_TRANSFERRED audit row whose new_values actually carries an
    # agent_id key (only TICKET_CREATED can lack one, when a ticket was
    # born unclaimed).
    op.execute(
        """
        UPDATE tickets t
        SET assigned_by = sub.actor_id
        FROM (
            SELECT DISTINCT ON (ticket_id) ticket_id, actor_id
            FROM ticket_audit_logs
            WHERE event_type IN ('TICKET_CREATED', 'TICKET_CLAIMED', 'AGENT_TRANSFERRED')
              AND (new_values ->> 'agent_id') IS NOT NULL
            ORDER BY ticket_id, created_at DESC
        ) sub
        WHERE t.ticket_id = sub.ticket_id
        """
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_tickets_assigned_by_users',
        'tickets',
        type_='foreignkey',
    )
    op.drop_column('tickets', 'assigned_by')
