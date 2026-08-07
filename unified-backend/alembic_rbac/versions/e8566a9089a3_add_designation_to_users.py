"""add designation to users

Revision ID: e8566a9089a3
Revises: d3f5a7b9c1e3
Create Date: 2026-08-07 00:00:00.000000

`scripts/org_seed/` (see mapping.py/build.py) already parses each real
employee's raw job title ("Designation" column in the source sheets)
to resolve their RBAC role/category, but never persisted the string
itself — there is no prior `designation` column, so it was discarded
after that one-time use. This adds it back as a plain, nullable,
display-only free-text column (independent of `role_id`/`category_id`,
same convention as `department`/`team` from
7a2b4c6d8e0f_add_profile_fields_to_users.py — carries no authorization
weight, never read by any permission/routing check).

No inline data backfill here, unlike that migration's `department`
backfill: designation has no column-based source of truth to copy
from (it only ever existed as a Python literal in
scripts/org_seed/source_data.py, already discarded once). Backfilling
the already-imported real employees from that source is a one-time,
non-destructive follow-up script, not a migration data step.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8566a9089a3'
down_revision: Union[str, None] = 'd3f5a7b9c1e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('designation', sa.String(length=150), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'designation')
