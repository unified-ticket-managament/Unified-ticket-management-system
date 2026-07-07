"""add INTERACTION_CLAIMED and INTERACTION_ARCHIVED to audit_event_type_enum

Revision ID: 9b2c4d6e8f0a
Revises: 8f1899cafaae
Create Date: 2026-07-07 00:00:00.000000

The Python AuditEventType enum gained INTERACTION_CLAIMED (the new
"Assign to me" action on a pending inbox item) and INTERACTION_ARCHIVED
(the new "Informational / Archive" reviewer decision), but the actual
Postgres enum type was never altered to match — inserting a row with
either value would crash with `InvalidTextRepresentationError`. This
migration only adds the new labels; nothing to backfill since no rows
could have used them before.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '9b2c4d6e8f0a'
down_revision: Union[str, None] = '8f1899cafaae'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside the same transaction
    # as a later statement that uses the new value, but it can run on
    # its own — Postgres 12+ allows this without AUTOCOMMIT as long as
    # it's the only DDL in the transaction, which it is here.
    op.execute("ALTER TYPE audit_event_type_enum ADD VALUE IF NOT EXISTS 'INTERACTION_CLAIMED'")
    op.execute("ALTER TYPE audit_event_type_enum ADD VALUE IF NOT EXISTS 'INTERACTION_ARCHIVED'")


def downgrade() -> None:
    # Postgres has no DROP VALUE for enums — removing a label
    # requires rebuilding the type, which isn't worth it for a
    # downgrade path. Left as a no-op, matching the project's other
    # enum-widening migrations.
    pass
