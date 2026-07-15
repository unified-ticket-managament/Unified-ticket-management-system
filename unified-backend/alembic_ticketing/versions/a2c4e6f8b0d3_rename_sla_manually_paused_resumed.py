"""rename SLA_MANUALLY_PAUSED/SLA_MANUALLY_RESUMED to SLA_PAUSED/SLA_RESUMED

Revision ID: a2c4e6f8b0d3
Revises: b7f1d3e5a9c2
Create Date: 2026-07-14 18:20:00.000000

These two audit event types now fire on the automatic
WAITING_FOR_CLIENT-driven pause/resume (previously they only fired on
a supervisor's manual override), so the "MANUALLY" qualifier in the
name is no longer accurate — the manual override still logs under the
same (renamed) event, distinguished by a "trigger": "manual_override"
tag in its own new_values instead. Postgres 10+ supports RENAME VALUE
directly; existing rows show the new label automatically, nothing to
backfill.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a2c4e6f8b0d3'
down_revision: Union[str, None] = 'b7f1d3e5a9c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE audit_event_type_enum RENAME VALUE 'SLA_MANUALLY_PAUSED' TO 'SLA_PAUSED'")
    op.execute("ALTER TYPE audit_event_type_enum RENAME VALUE 'SLA_MANUALLY_RESUMED' TO 'SLA_RESUMED'")


def downgrade() -> None:
    op.execute("ALTER TYPE audit_event_type_enum RENAME VALUE 'SLA_PAUSED' TO 'SLA_MANUALLY_PAUSED'")
    op.execute("ALTER TYPE audit_event_type_enum RENAME VALUE 'SLA_RESUMED' TO 'SLA_MANUALLY_RESUMED'")
