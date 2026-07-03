"""add TICKET_RESOLVED to audit_event_type_enum

Revision ID: 4e6b8a1d3c5f
Revises: 7a2d4e9f1c3b
Create Date: 2026-07-03 00:00:00.000000

The Python AuditEventType enum gained TICKET_RESOLVED (used to log the
new dedicated "Resolve Ticket" action to the audit trail), but the
actual Postgres enum type was never altered to match — inserting a
row with this value would crash with `InvalidTextRepresentationError`.
This migration only adds the new label; nothing to backfill since no
rows could have used it before.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '4e6b8a1d3c5f'
down_revision: Union[str, None] = '7a2d4e9f1c3b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside the same transaction
    # as a later statement that uses the new value, but it can run on
    # its own — Postgres 12+ allows this without AUTOCOMMIT as long as
    # it's the only DDL in the transaction, which it is here.
    op.execute("ALTER TYPE audit_event_type_enum ADD VALUE IF NOT EXISTS 'TICKET_RESOLVED'")


def downgrade() -> None:
    # Postgres has no DROP VALUE for enums — removing a label
    # requires rebuilding the type, which isn't worth it for a
    # downgrade path. Left as a no-op, matching the project's other
    # enum-widening migrations.
    pass
