"""add CATEGORY_TRANSFERRED to audit_event_type_enum

Revision ID: b5d7f9a1c3e6
Revises: d7f9b1c3e5a7
Create Date: 2026-08-17 00:00:00.000000

Cross-category ticket transfer records the ticket's category move as its
own dedicated audit event, alongside (not instead of) the existing
AGENT_TRANSFERRED event a transfer already writes for the assignment
change. This migration only adds the new label; nothing to backfill
since no rows could have used it before.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b5d7f9a1c3e6'
down_revision: Union[str, None] = 'd7f9b1c3e5a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside the same transaction
    # as a later statement that uses the new value, but it can run on
    # its own — Postgres 12+ allows this without AUTOCOMMIT as long as
    # it's the only DDL in the transaction, which it is here.
    op.execute("ALTER TYPE audit_event_type_enum ADD VALUE IF NOT EXISTS 'CATEGORY_TRANSFERRED'")


def downgrade() -> None:
    # Postgres has no DROP VALUE for enums — removing a label
    # requires rebuilding the type, which isn't worth it for a
    # downgrade path. Left as a no-op, matching the project's other
    # enum-widening migrations.
    pass
