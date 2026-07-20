"""add handling_stage_percentages to sla_policies

Revision ID: d2a4c6e8f0b3
Revises: c8f1a3e5b7d0
Create Date: 2026-07-20 00:00:02.000000

Replaces the single flat `handling_sla_percentage` with a configurable,
ordered list of per-stage percentages (stage 1 = index 0, etc.) —
`handling_sla_percentage` could only ever express "the same fraction
forever," never a decreasing/varying percentage per handling cycle,
which is the entire point of this feature. A stage beyond the
configured list's length repeats the last configured value (see
EscalationHandlingSlaService), rather than growing unboundedly or
erroring.

`handling_sla_percentage` itself is deliberately left in place, NOT
dropped or renamed, in this migration — per this session's explicit
"don't delete EscalationHandlingSLA (or its supporting config) yet,
migrate behavior first, verify, remove later" decision. New code reads
only `handling_stage_percentages` going forward; the old column is
inert but preserved for the parallel-run/verification window.

Backfilled per-row as [v, v/2, v/4] from each row's own existing
handling_sla_percentage (v) — preserves any prior admin edit via the
SLA Timing Matrix rather than silently resetting every row to a
hardcoded default. Added nullable first so the backfill UPDATE can run,
then made NOT NULL.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd2a4c6e8f0b3'
down_revision: Union[str, None] = 'c8f1a3e5b7d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'sla_policies',
        sa.Column('handling_stage_percentages', postgresql.JSONB(), nullable=True),
    )

    op.execute(
        """
        UPDATE sla_policies
        SET handling_stage_percentages = jsonb_build_array(
            handling_sla_percentage,
            handling_sla_percentage / 2,
            handling_sla_percentage / 4
        )
        """
    )

    op.alter_column('sla_policies', 'handling_stage_percentages', nullable=False)


def downgrade() -> None:
    op.drop_column('sla_policies', 'handling_stage_percentages')
