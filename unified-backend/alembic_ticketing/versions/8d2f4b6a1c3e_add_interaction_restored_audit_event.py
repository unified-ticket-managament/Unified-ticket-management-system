"""add INTERACTION_RESTORED to audit_event_type_enum

Revision ID: 8d2f4b6a1c3e
Revises: 7c4e9a1b2d3f
Create Date: 2026-10-05 00:00:00.000000

Mail Trash can restore a soft-deleted message; the restore is audited
with a dedicated event. Only adds the label; nothing to backfill.
"""

from typing import Sequence, Union

from alembic import op

revision: str = '8d2f4b6a1c3e'
down_revision: Union[str, None] = '7c4e9a1b2d3f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE audit_event_type_enum ADD VALUE IF NOT EXISTS 'INTERACTION_RESTORED'")


def downgrade() -> None:
    # Postgres has no DROP VALUE for enums; no-op like the project's
    # other enum-widening migrations.
    pass
