"""add handling_stage fields to ticket_escalations

Revision ID: b4e7f0a2c6d9
Revises: a3c5e7f9b1d5
Create Date: 2026-07-20 00:00:00.000000

Introduces the "handling stage" concept, tracked independently of the
escalation ownership ladder (TicketEscalation.level/status): the number
of completed post-escalation "accept -> assign -> breach" cycles is not
the same fact as how far the ladder has advanced due to acknowledgment
timeouts. Escalation-ladder movement alone (evaluate_overdue) must never
touch these fields.

- handling_stage: 0 until the first genuine acceptance completes
  (EscalationService._complete_acceptance), then increments only when a
  stage's own window elapses and a NEW acceptance completes at the next
  level — never on a bare ack-timeout ladder advance.
- handling_stage_started_at / handling_stage_due_at: the current stage's
  window. Both NULL when no stage is currently running (either before
  the first acceptance, or between a stage's breach and the next
  acceptance). "Breached" is derived by comparing handling_stage_due_at
  to now — no separate boolean/breach-flag column, per the "cleaner,
  more extensible" review note; handling_stage_due_at being cleared back
  to NULL by the sweep once acted on IS the idempotency guard (a stage
  is "currently running" iff this field is non-null).

No backfill needed — every existing escalation row predates this
feature, so 0/NULL/NULL is the only correct starting value for all of
them (nullable=False with a server_default covers handling_stage; the
two timestamp columns are nullable with no default).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b4e7f0a2c6d9'
down_revision: Union[str, None] = 'a3c5e7f9b1d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'ticket_escalations',
        sa.Column(
            'handling_stage',
            sa.Integer(),
            nullable=False,
            server_default='0',
        ),
    )
    op.add_column(
        'ticket_escalations',
        sa.Column('handling_stage_started_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'ticket_escalations',
        sa.Column('handling_stage_due_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index(
        'ix_ticket_escalations_handling_stage_due_at',
        'ticket_escalations',
        ['handling_stage_due_at'],
        unique=False,
        postgresql_where=sa.text('handling_stage_due_at IS NOT NULL'),
    )


def downgrade() -> None:
    op.drop_index(
        'ix_ticket_escalations_handling_stage_due_at',
        table_name='ticket_escalations',
    )
    op.drop_column('ticket_escalations', 'handling_stage_due_at')
    op.drop_column('ticket_escalations', 'handling_stage_started_at')
    op.drop_column('ticket_escalations', 'handling_stage')
