"""add edit access request audit event types

Revision ID: a7ad0a59b85f
Revises: c3e5f7a9b1d3
Create Date: 2026-07-08 20:10:05.623674

The new ticket edit-access request/approve/reject workflow needs three
new AuditEventType values. This migration only widens the Postgres
enum label set; nothing to backfill since no rows could have used
these values before.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a7ad0a59b85f'
down_revision: Union[str, None] = 'c3e5f7a9b1d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside the same transaction
    # as a later statement that uses the new value, but it can run on
    # its own — Postgres 12+ allows this without AUTOCOMMIT as long as
    # it's the only DDL in the transaction, which it is here.
    op.execute("ALTER TYPE audit_event_type_enum ADD VALUE IF NOT EXISTS 'EDIT_ACCESS_REQUESTED'")
    op.execute("ALTER TYPE audit_event_type_enum ADD VALUE IF NOT EXISTS 'EDIT_ACCESS_APPROVED'")
    op.execute("ALTER TYPE audit_event_type_enum ADD VALUE IF NOT EXISTS 'EDIT_ACCESS_REJECTED'")


def downgrade() -> None:
    # Postgres has no DROP VALUE for enums — removing a label
    # requires rebuilding the type, which isn't worth it for a
    # downgrade path. Left as a no-op, matching the project's other
    # enum-widening migrations.
    pass