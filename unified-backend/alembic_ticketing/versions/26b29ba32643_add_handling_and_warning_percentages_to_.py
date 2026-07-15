"""add handling and warning percentages to sla policies

Revision ID: 26b29ba32643
Revises: d33a0758e3c4
Create Date: 2026-07-14 12:32:54.406421

Adds three per-priority columns to sla_policies backing the
Super-Admin-facing SLA Timing Matrix: handling_sla_percentage (what
fraction of resolution_target_minutes the escalation-handling clock
gets once an escalation is acknowledged — previously a single hardcoded
0.25 for every priority, see EscalationHandlingSlaService), and
warning_1_percentage/warning_2_percentage (per-priority overrides for
the sweep's HALF_ELAPSED/AT_RISK elapsed-fraction thresholds —
previously a single global 0.5/0.8 for every clock, see
sla_escalation_rules.thresholds_reached). BREACHED (100%) and ESCALATED
(150%) are unaffected and stay fixed globally.

server_default values match the previous hardcoded constants exactly
(25.0 / 50.0 / 80.0), so existing rows keep today's actual behavior
with no data migration step needed, and nullable=False is safe from the
same statement.

Autogenerate also proposed dropping several indexes/columns
(ix_tickets_updated_at, ix_tickets_pool_view, ix_tickets_title_trgm,
ix_interactions_subject_trgm, idx_interactions_inbox_status,
idx_interactions_parent_visible, idx_interactions_ticket_created,
ix_interactions_inbox_base, ix_interactions_snoozed_until,
interactions.snoozed_until) — these are real, deliberately-added prior
work simply not yet declared in the current SQLAlchemy models (the same
pre-existing drift noted in d33a0758e3c4's own migration and the root
CLAUDE.md's SLA & Escalation section). Left alone and stripped out of
this migration, same as that one did.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '26b29ba32643'
down_revision: Union[str, None] = 'd33a0758e3c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'sla_policies',
        sa.Column(
            'handling_sla_percentage',
            sa.Float(),
            nullable=False,
            server_default='25.0',
        ),
    )
    op.add_column(
        'sla_policies',
        sa.Column(
            'warning_1_percentage',
            sa.Float(),
            nullable=False,
            server_default='50.0',
        ),
    )
    op.add_column(
        'sla_policies',
        sa.Column(
            'warning_2_percentage',
            sa.Float(),
            nullable=False,
            server_default='80.0',
        ),
    )


def downgrade() -> None:
    op.drop_column('sla_policies', 'warning_2_percentage')
    op.drop_column('sla_policies', 'warning_1_percentage')
    op.drop_column('sla_policies', 'handling_sla_percentage')
