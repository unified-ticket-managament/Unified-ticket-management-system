"""add EMAIL_RECEIVED to audit_event_type_enum

Revision ID: 7a2d4e9f1c3b
Revises: 3f7c9a1e5b2d
Create Date: 2026-07-02 00:00:00.000000

The Python AuditEventType enum gained EMAIL_RECEIVED (used to log
inbound client emails to the audit trail with actor_role=CLIENT),
but the actual Postgres enum type was never altered to match —
inserting a row with this value crashed with
`InvalidTextRepresentationError`. This migration only adds the new
label; nothing to backfill since no rows could have used it before.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '7a2d4e9f1c3b'
down_revision: Union[str, None] = '3f7c9a1e5b2d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside the same transaction
    # as a later statement that uses the new value, but it can run on
    # its own — Postgres 12+ allows this without AUTOCOMMIT as long as
    # it's the only DDL in the transaction, which it is here.
    op.execute("ALTER TYPE audit_event_type_enum ADD VALUE IF NOT EXISTS 'EMAIL_RECEIVED'")


def downgrade() -> None:
    # Postgres has no DROP VALUE for enums — removing a label
    # requires rebuilding the type, which isn't worth it for a
    # downgrade path. Left as a no-op, matching the project's other
    # enum-widening migrations.
    pass
