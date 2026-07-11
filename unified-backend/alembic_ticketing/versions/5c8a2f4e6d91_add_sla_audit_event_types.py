"""add SLA_MANUALLY_PAUSED, SLA_MANUALLY_RESUMED, SLA_BREACH_DETECTED, SLA_ESCALATED to audit_event_type_enum

Revision ID: 5c8a2f4e6d91
Revises: 317e5570c7df
Create Date: 2026-07-11 18:05:00.000000

The Python AuditEventType enum gained four SLA-related values (the
manual pause/resume override action, and the breach sweep's own
audit rows for BREACHED/ESCALATED thresholds), but the actual Postgres
enum type was never altered to match — inserting a row with any of
these would crash with `InvalidTextRepresentationError`. This
migration only adds the new labels; nothing to backfill since no rows
could have used them before.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '5c8a2f4e6d91'
down_revision: Union[str, None] = '317e5570c7df'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside the same transaction
    # as a later statement that uses the new value, but it can run on
    # its own — Postgres 12+ allows this without AUTOCOMMIT as long as
    # it's the only DDL in the transaction, which it is here.
    op.execute("ALTER TYPE audit_event_type_enum ADD VALUE IF NOT EXISTS 'SLA_MANUALLY_PAUSED'")
    op.execute("ALTER TYPE audit_event_type_enum ADD VALUE IF NOT EXISTS 'SLA_MANUALLY_RESUMED'")
    op.execute("ALTER TYPE audit_event_type_enum ADD VALUE IF NOT EXISTS 'SLA_BREACH_DETECTED'")
    op.execute("ALTER TYPE audit_event_type_enum ADD VALUE IF NOT EXISTS 'SLA_ESCALATED'")


def downgrade() -> None:
    # Postgres has no DROP VALUE for enums — removing a label
    # requires rebuilding the type, which isn't worth it for a
    # downgrade path. Left as a no-op, matching the project's other
    # enum-widening migrations.
    pass
