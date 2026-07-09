"""add INTERACTION_SNOOZED/UNSNOOZED/TAGGED/FOLDER_CHANGED to audit_event_type_enum

Revision ID: a1b3c5d7e9f1
Revises: cdcf2019a594
Create Date: 2026-07-08 00:00:00.000000

The Python AuditEventType enum gained four new values for the Phase 2
Mail features (snooze, tags, folder assignment), but the actual
Postgres enum type was never altered to match — inserting a row with
any of these values would crash with `InvalidTextRepresentationError`.
This migration only adds the new labels; nothing to backfill since no
rows could have used them before.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1b3c5d7e9f1'
down_revision: Union[str, None] = 'cdcf2019a594'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside the same transaction
    # as a later statement that uses the new value, but it can run on
    # its own — Postgres 12+ allows this without AUTOCOMMIT as long as
    # it's the only DDL in the transaction, which it is here.
    op.execute("ALTER TYPE audit_event_type_enum ADD VALUE IF NOT EXISTS 'INTERACTION_SNOOZED'")
    op.execute("ALTER TYPE audit_event_type_enum ADD VALUE IF NOT EXISTS 'INTERACTION_UNSNOOZED'")
    op.execute("ALTER TYPE audit_event_type_enum ADD VALUE IF NOT EXISTS 'INTERACTION_TAGGED'")
    op.execute("ALTER TYPE audit_event_type_enum ADD VALUE IF NOT EXISTS 'INTERACTION_FOLDER_CHANGED'")


def downgrade() -> None:
    # Postgres has no DROP VALUE for enums — removing a label
    # requires rebuilding the type, which isn't worth it for a
    # downgrade path. Left as a no-op, matching the project's other
    # enum-widening migrations.
    pass
