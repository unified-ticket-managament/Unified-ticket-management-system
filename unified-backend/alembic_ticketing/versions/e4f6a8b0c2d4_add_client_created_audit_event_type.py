"""add CLIENT_CREATED to audit_event_type_enum

Revision ID: e4f6a8b0c2d4
Revises: d3e5f7a9b1c3
Create Date: 2026-07-06 00:00:00.000003

The Python AuditEventType enum gained CLIENT_CREATED (logged when a
client company is onboarded), but the actual Postgres enum type must
be widened too, or the first write crashes with
InvalidTextRepresentationError. This migration only adds the new
label; nothing to backfill since no rows could have used it before.
Must run standalone (no other DDL in the same transaction) per the
add-postgres-enum-value skill.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e4f6a8b0c2d4'
down_revision: Union[str, None] = 'd3e5f7a9b1c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE audit_event_type_enum ADD VALUE IF NOT EXISTS 'CLIENT_CREATED'")


def downgrade() -> None:
    # Postgres has no DROP VALUE for enums — left as a no-op, matching
    # the project's other enum-widening migrations.
    pass
