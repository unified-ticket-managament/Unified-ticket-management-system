"""add reporting_manager_id to users

Revision ID: b2d4f6a8c0e2
Revises: a1c3e5f7b9d1
Create Date: 2026-08-11 00:00:00.000000

Adds `reporting_manager_id` — a new, nullable, self-referencing FK on
`users` used exclusively as the Organization Chart's source of truth
going forward (see OrganizationService). This is purely additive:
`manager_id`/`teamlead_id` are NOT removed, renamed, or reinterpreted
here, and continue to drive every existing consumer (permission-
override/permission-request scoping, ticket-assignment pickers,
SLA/escalation ownership resolution, audit-log visibility) exactly as
before. `reporting_manager_teams` is likewise untouched.

Backfilled in this same migration via one raw-SQL UPDATE, using the
confirmed precedence rule (teamlead_id wins when set, since real
org_seed-imported Staff rows routinely carry both — teamlead_id being
their real, immediate Team Lead and manager_id a redundant, denormalized
copy of that Team Lead's own manager one level further up; a Staff
member with no Team Lead in between has only manager_id set, which
becomes their reporting_manager_id directly):

    reporting_manager_id = COALESCE(teamlead_id, manager_id)

Only rows where reporting_manager_id is still NULL are touched, so this
is safe to think of as idempotent even though the column starts every
row NULL (nothing here can silently clobber a value set by some other
process before this migration runs).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b2d4f6a8c0e2'
down_revision: Union[str, None] = 'a1c3e5f7b9d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('reporting_manager_id', postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        'users_reporting_manager_id_fkey',
        'users',
        'users',
        ['reporting_manager_id'],
        ['user_id'],
    )
    op.execute(
        """
        UPDATE users
        SET reporting_manager_id = COALESCE(teamlead_id, manager_id)
        WHERE reporting_manager_id IS NULL
          AND (teamlead_id IS NOT NULL OR manager_id IS NOT NULL)
        """
    )


def downgrade() -> None:
    op.drop_constraint('users_reporting_manager_id_fkey', 'users', type_='foreignkey')
    op.drop_column('users', 'reporting_manager_id')
