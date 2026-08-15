"""add dismissed_at to notifications

Revision ID: e5f7a9c1b3d5
Revises: c3e5a7b9d1f4
Create Date: 2026-08-15 00:00:00.000000

Backs a real, persistent "Clear All" for the notification bell — the
frontend's Clear All button used to only hide notifications locally
for the current tab session (no backend concept of "cleared" existed
at all), so a refresh/new tab/different device resurrected them,
still unread. `dismissed_at` is a soft delete, matching the codebase's
existing revoked_at-style convention (e.g. user_permission_overrides)
— a Notification row is never hard-deleted, it just stops being
returned by list_for_user/count_for_user (and therefore GET
/notifications) once set.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e5f7a9c1b3d5'
down_revision: Union[str, None] = 'c3e5a7b9d1f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "notifications",
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("notifications", "dismissed_at")
