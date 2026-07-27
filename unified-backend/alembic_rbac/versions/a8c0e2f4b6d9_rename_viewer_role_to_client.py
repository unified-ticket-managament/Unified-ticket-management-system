"""rename Viewer role to Client

Revision ID: a8c0e2f4b6d9
Revises: 7a2b4c6d8e0f
Create Date: 2026-07-27 00:00:00.000000

Data-only rename: the client-facing "Viewer" role is renamed to
"Client" in place. `role_id` (primary key), every `role_permissions`
row, and every `users.role_id` FK reference are all untouched — every
user currently holding this role keeps the exact same role_id and the
exact same permission grants, and simply reads as "Client" from here
on. No new role is created and no existing role is deleted.

Guarded with `WHERE NOT EXISTS` so re-running this against a database
that's already been renamed (or a fresh install whose seed script
already created the role as "Client" directly) is a safe no-op rather
than an error.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a8c0e2f4b6d9'
down_revision: Union[str, None] = '7a2b4c6d8e0f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE roles
        SET name = 'Client'
        WHERE name = 'Viewer'
          AND NOT EXISTS (SELECT 1 FROM roles WHERE name = 'Client')
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE roles
        SET name = 'Viewer'
        WHERE name = 'Client'
          AND NOT EXISTS (SELECT 1 FROM roles WHERE name = 'Viewer')
        """
    )
