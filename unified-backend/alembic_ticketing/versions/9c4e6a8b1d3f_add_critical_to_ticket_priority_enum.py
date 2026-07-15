"""add CRITICAL to ticket_priority_enum

Revision ID: 9c4e6a8b1d3f
Revises: 26b29ba32643
Create Date: 2026-07-14 15:00:00.000000

The Python TicketPriority enum gained CRITICAL — set automatically,
once, by the escalation workflow (never manually selectable), but the
actual Postgres enum type (ticket_priority_enum, shared by
Ticket.current_priority, ResolutionSLA.priority,
FirstResponseSLA.priority, and SLAPolicy.priority) was never altered
to match. This migration only adds the new label; nothing to backfill
since no row could have used it before. See
9c4e6a8b1d3f's follow-up migration for the new SLAPolicy row this
value needs (a separate migration, since ALTER TYPE ... ADD VALUE
cannot run in the same transaction as a later statement that uses it).
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '9c4e6a8b1d3f'
down_revision: Union[str, None] = '26b29ba32643'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside the same transaction
    # as a later statement that uses the new value, but it can run on
    # its own — Postgres 12+ allows this without AUTOCOMMIT as long as
    # it's the only DDL in the transaction, which it is here.
    op.execute("ALTER TYPE ticket_priority_enum ADD VALUE IF NOT EXISTS 'CRITICAL'")


def downgrade() -> None:
    # Postgres has no DROP VALUE for enums — removing a label requires
    # rebuilding the type, which isn't worth it for a downgrade path.
    # Left as a no-op, matching the project's other enum-widening
    # migrations.
    pass
