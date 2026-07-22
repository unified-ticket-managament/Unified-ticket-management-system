"""add escalation_cycle to sla breach-notification dedup key

Revision ID: e4b6d8f0a2c5
Revises: d2a4c6e8f0b3
Create Date: 2026-07-21 00:00:00.000000

Fixes a real bug: SLABreachNotification's idempotency ledger was
unique on (clock_type, clock_id, threshold) alone. EscalationService.
_complete_acceptance -> SLAService.restart_resolution_clock_for_escalation
restarts a Resolution SLA clock's due_at/target *in place* (same
resolution_sla_id) every time an escalation is accepted into a new
handling stage. Since HALF_ELAPSED/AT_RISK/BREACHED for that clock_id
were already recorded during its pre-escalation lifetime (that's what
triggered the escalation in the first place), the old two-column-plus-
threshold key permanently blocked those three notifications from ever
firing again for the rest of that ticket's life, even though the
restarted clock represents a genuinely new SLA cycle with its own
fresh due date. Only the escalation ladder's own notifications
(tracked entirely via TicketEscalation, never this ledger) kept
appearing — this is the root cause of "regular SLA notifications stop
after the first escalation."

`resolution_slas.escalation_cycle` (new, defaults 0) is bumped by
ResolutionSLARepository.restart_due_at_for_escalation on every
handling-stage restart. `sla_breach_notifications.cycle` (new, defaults
0) records which cycle a given (clock, threshold) notification belongs
to, and is folded into the unique index in place of the old
(clock_type, clock_id, threshold) key -> (clock_type, clock_id,
threshold, cycle). First Response clocks never restart, so their
notifications always use cycle=0 — this migration doesn't need to
special-case that clock type at all, the column just always reads 0
for it.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e4b6d8f0a2c5'
down_revision: Union[str, None] = 'd2a4c6e8f0b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'resolution_slas',
        sa.Column('escalation_cycle', sa.Integer(), nullable=False, server_default='0'),
    )
    op.alter_column('resolution_slas', 'escalation_cycle', server_default=None)

    op.add_column(
        'sla_breach_notifications',
        sa.Column('cycle', sa.Integer(), nullable=False, server_default='0'),
    )
    op.alter_column('sla_breach_notifications', 'cycle', server_default=None)

    op.drop_index('ix_sla_breach_notifications_unique', table_name='sla_breach_notifications')
    op.create_index(
        'ix_sla_breach_notifications_unique',
        'sla_breach_notifications',
        ['clock_type', 'clock_id', 'threshold', 'cycle'],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index('ix_sla_breach_notifications_unique', table_name='sla_breach_notifications')
    op.create_index(
        'ix_sla_breach_notifications_unique',
        'sla_breach_notifications',
        ['clock_type', 'clock_id', 'threshold'],
        unique=True,
    )

    op.drop_column('sla_breach_notifications', 'cycle')
    op.drop_column('resolution_slas', 'escalation_cycle')
