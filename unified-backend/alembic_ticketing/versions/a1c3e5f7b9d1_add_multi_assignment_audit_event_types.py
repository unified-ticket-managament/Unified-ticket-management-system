"""add multi-user / multi-category assignment audit event types

Revision ID: a1c3e5f7b9d1
Revises: a7c9e1b3d5f0
Create Date: 2026-10-06 00:00:00.000001

Widens audit_event_type_enum only — same ADD VALUE IF NOT EXISTS
pattern as every earlier audit-event migration. None of these values
is used by a later migration in the same run (the backfill writes no
audit rows), so the "new enum value can't be used in the transaction
that added it" Postgres rule never bites.
"""

from typing import Sequence, Union

from alembic import op

revision: str = 'a1c3e5f7b9d1'
down_revision: Union[str, None] = 'a7c9e1b3d5f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NEW_VALUES = (
    "USER_ASSIGNED",
    "USER_UNASSIGNED",
    "PRIMARY_CHANGED",
    "ASSIGNMENT_STATUS_CHANGED",
    "CATEGORY_ADDED",
    "CATEGORY_REMOVED",
)


def upgrade() -> None:
    for value in NEW_VALUES:
        op.execute(f"ALTER TYPE audit_event_type_enum ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # Postgres has no ALTER TYPE ... DROP VALUE — no-op by convention.
    pass
