"""add employee_number to users

Revision ID: a1c3e5f7b9d1
Revises: e8566a9089a3
Create Date: 2026-08-10 00:00:00.000000

Adds the official, human-readable Employee ID (e.g. "266", "2") from the
company's HR master data as an additional, purely display/search
identifier — `user_id` (UUID) remains the sole canonical identifier for
every relationship (assignment, ownership, audit, reporting hierarchy,
authentication); nothing about that changes here. Nullable (most demo/
system accounts have no official employee record) and unique among the
rows that do have a value (Postgres's default unique-index behavior
already treats every NULL as distinct from every other NULL, so this
needs no partial-index trick the way user_permission_overrides' active-
grant uniqueness does).

No inline data backfill here, same convention as
e8566a9089a3_add_designation_to_users.py — the official Employee ID only
ever existed as a Python literal in scripts/org_seed/source_data.py;
backfilling the already-imported real employees from that source is a
one-time, non-destructive follow-up script
(scripts/org_seed/backfill_employee_number.py), not a migration data step.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c3e5f7b9d1'
down_revision: Union[str, None] = 'e8566a9089a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('employee_number', sa.String(length=20), nullable=True))
    op.create_unique_constraint('uq_users_employee_number', 'users', ['employee_number'])


def downgrade() -> None:
    op.drop_constraint('uq_users_employee_number', 'users', type_='unique')
    op.drop_column('users', 'employee_number')
