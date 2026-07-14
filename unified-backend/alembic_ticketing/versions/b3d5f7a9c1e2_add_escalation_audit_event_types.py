"""add ESCALATION_CREATED, ESCALATION_ACKNOWLEDGED, ESCALATION_ADVANCED, ESCALATION_CLOSED to audit_event_type_enum

Revision ID: b3d5f7a9c1e2
Revises: a7c9e1f3b5d6
Create Date: 2026-07-13 00:00:01.000000

Same gap as 5c8a2f4e6d91: the Python AuditEventType enum gained four
new values for the internal escalation workflow (TicketEscalation),
but the actual Postgres enum type was never altered to match. Adds
the new labels only; nothing to backfill.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b3d5f7a9c1e2'
down_revision: Union[str, None] = 'a7c9e1f3b5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE audit_event_type_enum ADD VALUE IF NOT EXISTS 'ESCALATION_CREATED'")
    op.execute("ALTER TYPE audit_event_type_enum ADD VALUE IF NOT EXISTS 'ESCALATION_ACKNOWLEDGED'")
    op.execute("ALTER TYPE audit_event_type_enum ADD VALUE IF NOT EXISTS 'ESCALATION_ADVANCED'")
    op.execute("ALTER TYPE audit_event_type_enum ADD VALUE IF NOT EXISTS 'ESCALATION_CLOSED'")


def downgrade() -> None:
    # Postgres has no DROP VALUE for enums — see 5c8a2f4e6d91's
    # matching note; left as a no-op.
    pass
