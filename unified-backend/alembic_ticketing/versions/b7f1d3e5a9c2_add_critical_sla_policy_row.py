"""add CRITICAL sla_policies row

Revision ID: b7f1d3e5a9c2
Revises: 9c4e6a8b1d3f
Create Date: 2026-07-14 15:05:00.000000

Seeds the 4th sla_policies row for the newly-widened CRITICAL priority
(see 9c4e6a8b1d3f, applied first — ALTER TYPE ... ADD VALUE can't share
a transaction with a statement that uses the new value, hence two
migrations). Targets confirmed for this rollout, tighter than HIGH's
existing 24h first response / 3 day resolution: 5 min first response,
1 hour (60 min) resolution, 10 min escalation ack window, 25% handling
SLA, 50%/80% warning thresholds — matching every other priority's
warning/handling defaults (see 26b29ba32643).

Fixed UUID (not regenerated per run), same convention as
317e5570c7df's original three rows, so this migration is safe to
read/reason about and re-run deterministically against a fresh DB.
"""

import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b7f1d3e5a9c2'
down_revision: Union[str, None] = '9c4e6a8b1d3f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TICKET_PRIORITY_ENUM = postgresql.ENUM(
    "LOW", "MEDIUM", "HIGH", "CRITICAL", name="ticket_priority_enum", create_type=False
)

CRITICAL_POLICY_ID = uuid.UUID("a4e8c2f6-1b3d-4a5e-9c7f-2d6b8a0e4c91")


def upgrade() -> None:
    sla_policies_table = sa.table(
        'sla_policies',
        sa.column('policy_id', sa.UUID()),
        sa.column('priority', TICKET_PRIORITY_ENUM),
        sa.column('first_response_target_minutes', sa.Integer()),
        sa.column('resolution_target_minutes', sa.Integer()),
        sa.column('escalation_ack_target_minutes', sa.Integer()),
        sa.column('handling_sla_percentage', sa.Float()),
        sa.column('warning_1_percentage', sa.Float()),
        sa.column('warning_2_percentage', sa.Float()),
        sa.column('is_active', sa.Boolean()),
        sa.column('created_at', sa.DateTime(timezone=True)),
        sa.column('updated_at', sa.DateTime(timezone=True)),
    )

    now = datetime.now(timezone.utc)
    op.bulk_insert(
        sla_policies_table,
        [
            {
                "policy_id": CRITICAL_POLICY_ID,
                "priority": "CRITICAL",
                "first_response_target_minutes": 5,
                "resolution_target_minutes": 60,
                "escalation_ack_target_minutes": 10,
                "handling_sla_percentage": 25.0,
                "warning_1_percentage": 50.0,
                "warning_2_percentage": 80.0,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM sla_policies WHERE policy_id = :policy_id").bindparams(
            policy_id=str(CRITICAL_POLICY_ID)
        )
    )
