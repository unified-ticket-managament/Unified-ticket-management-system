"""add original_priority and has_advanced_past_starting_level to ticket_escalations

Revision ID: e5a7c9f1b3d6
Revises: 5d2efe3d49d2
Create Date: 2026-07-16 00:00:00.000000

Two new columns on ticket_escalations, fixing a real bug:
EscalationService._reshift_sla_for_escalation_acceptance used to
unconditionally reshift the Resolution SLA clock onto CRITICAL's
target the moment the FIRST escalation was accepted, even though the
clock had been running for days/hours against its original LOW/
MEDIUM/HIGH target — producing a due_at far in the past (an instant,
retroactive breach) the moment a supervisor accepted it. The reshift
is now deferred until the escalation has actually advanced past its
starting level (i.e. the first owner didn't act in time and it's
genuinely a "second time" escalation).

- original_priority: the ticket's priority as of escalation creation,
  captured before Ticket.current_priority is overwritten to CRITICAL
  (see EscalationService._set_ticket_priority_to_critical) — an
  explicit, durable record rather than relying on the audit log or on
  ResolutionSLA.priority's own mutable state.
- has_advanced_past_starting_level: flips True the moment
  evaluate_overdue/advance_for_handling_sla_breach actually moves the
  level past where the escalation started — the gate for the reshift
  described above.

Backfill note: pre-existing ticket_escalations rows have no
recoverable original_priority (the true pre-escalation value was never
stored) — best-effort backfilled from the ticket's own
current_priority, the closest available fact, since every escalated
ticket's priority is CRITICAL by the time this migration runs.
has_advanced_past_starting_level defaults False for pre-existing rows,
which may understate the two known leftover ACTIVE dev-database
escalations already documented elsewhere as having advanced to
SITE_LEAD — acceptable, same class of harmless pre-existing dev-data
drift already tolerated in this migration history, not worth a
data-driven backfill for two known rows.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e5a7c9f1b3d6'
down_revision: Union[str, None] = '5d2efe3d49d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ticket_priority_enum already exists (widened to include CRITICAL by
# 9c4e6a8b1d3f) — create_type=False so this column reuses it instead of
# trying (and failing, DuplicateObject) to CREATE TYPE again.
_TICKET_PRIORITY_ENUM = postgresql.ENUM(
    "LOW", "MEDIUM", "HIGH", "CRITICAL",
    name="ticket_priority_enum",
    create_type=False,
)


def upgrade() -> None:
    op.add_column(
        'ticket_escalations',
        sa.Column('original_priority', _TICKET_PRIORITY_ENUM, nullable=True),
    )
    op.add_column(
        'ticket_escalations',
        sa.Column(
            'has_advanced_past_starting_level',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    # Best-effort backfill for pre-existing rows — see module docstring.
    op.execute(
        """
        UPDATE ticket_escalations
        SET original_priority = tickets.current_priority
        FROM tickets
        WHERE tickets.ticket_id = ticket_escalations.ticket_id
          AND ticket_escalations.original_priority IS NULL
        """
    )

    op.alter_column('ticket_escalations', 'original_priority', nullable=False)


def downgrade() -> None:
    op.drop_column('ticket_escalations', 'has_advanced_past_starting_level')
    op.drop_column('ticket_escalations', 'original_priority')
