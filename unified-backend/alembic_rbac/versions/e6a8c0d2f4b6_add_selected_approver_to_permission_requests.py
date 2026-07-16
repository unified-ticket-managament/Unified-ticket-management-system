"""add selected_approver_id to permission_requests, scope pending-unique index by ticket

Revision ID: e6a8c0d2f4b6
Revises: d4f6a8b0c2e4
Create Date: 2026-07-17 03:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e6a8c0d2f4b6'
down_revision: Union[str, None] = 'd4f6a8b0c2e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'permission_requests',
        sa.Column('selected_approver_id', sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        'fk_permission_requests_selected_approver_id_users',
        'permission_requests',
        'users',
        ['selected_approver_id'],
        ['user_id'],
        ondelete='SET NULL',
    )

    # Rebuild the pending-request-uniqueness index to also key off
    # scope_ticket_id (COALESCE'd to a sentinel, same pattern as
    # user_permission_overrides' own active-uniqueness index) — a
    # requester should be able to hold two concurrently-PENDING
    # requests for the same permission as long as they're scoped to
    # different tickets (e.g. editother_ticket for ticket A and,
    # separately, for ticket B); the old 2-column index blocked that.
    op.drop_index(
        'ix_permission_requests_pending_unique',
        table_name='permission_requests',
    )
    op.execute(
        """
        CREATE UNIQUE INDEX ix_permission_requests_pending_unique
        ON permission_requests (
            requester_id,
            permission_id,
            COALESCE(scope_ticket_id, '00000000-0000-0000-0000-000000000000'::uuid)
        )
        WHERE status = 'PENDING'
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS ix_permission_requests_pending_unique"
    )
    op.create_index(
        'ix_permission_requests_pending_unique',
        'permission_requests',
        ['requester_id', 'permission_id'],
        unique=True,
        postgresql_where=sa.text("status = 'PENDING'"),
    )

    op.drop_constraint(
        'fk_permission_requests_selected_approver_id_users',
        'permission_requests',
        type_='foreignkey',
    )
    op.drop_column('permission_requests', 'selected_approver_id')
