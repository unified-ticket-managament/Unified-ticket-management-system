"""add active_target_minutes to resolution_slas

Revision ID: c8f1a3e5b7d0
Revises: b4e7f0a2c6d9
Create Date: 2026-07-20 00:00:01.000000

ResolutionSLA becomes the single stage-aware timer: once a handling
stage reshifts due_at, the target it's measured against
(original_resolution_target_minutes x handling_stage_percentage) no
longer matches any single priority's flat policy row, so it can no
longer be safely re-derived from `priority` via a policy lookup at read
time (that's exactly what the sweep/get_ticket_sla_state/frontend do
today). This column stores the resolved target directly instead,
mirroring the existing EscalationHandlingSLA.target_seconds convention
("store the resolved value, don't re-derive it from a live policy that
might change later").

Backfilled from each row's own current priority's policy target — this
preserves exactly today's behavior for every existing clock (none of
them have gone through a stage reshift yet, so their real target IS
still their priority's flat policy value) and needs no separate
migration-time data assumptions beyond "sla_policies is already seeded."
Added nullable first so the backfill UPDATE can run, then made
NOT NULL.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c8f1a3e5b7d0'
down_revision: Union[str, None] = 'b4e7f0a2c6d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'resolution_slas',
        sa.Column('active_target_minutes', sa.Integer(), nullable=True),
    )

    op.execute(
        """
        UPDATE resolution_slas
        SET active_target_minutes = sla_policies.resolution_target_minutes
        FROM sla_policies
        WHERE resolution_slas.priority = sla_policies.priority
        """
    )
    # Fallback for the (expected-empty, but not guaranteed) case of a
    # clock whose priority has no matching sla_policies row at all —
    # never leave a NOT NULL column half-backfilled.
    op.execute(
        """
        UPDATE resolution_slas
        SET active_target_minutes = 0
        WHERE active_target_minutes IS NULL
        """
    )

    op.alter_column('resolution_slas', 'active_target_minutes', nullable=False)


def downgrade() -> None:
    op.drop_column('resolution_slas', 'active_target_minutes')
