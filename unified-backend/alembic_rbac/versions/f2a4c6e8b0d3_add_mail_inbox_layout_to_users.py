"""add mail inbox layout widths to users

Revision ID: f2a4c6e8b0d3
Revises: d1f3a5c7e9b1
Create Date: 2026-09-07 00:00:00.000001

Per-user, per-account persistence for the Mail Inbox's two draggable
panel dividers (Folders | Message List | Message Details) — see
MailWorkspaceLayout.tsx. Previously only the list|detail divider was
remembered at all, and only in browser localStorage (device-local,
not tied to the account, and not isolated between users sharing a
browser profile). Both dividers now persist server-side instead.

Nullable, no backfill: every existing user has no saved preference
yet, which is the correct default state — the frontend's existing
1:1:3 ratio-based seeding already handles a null value exactly as it
does today, so this migration is purely additive with zero behavior
change for anyone until they next drag a divider.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2a4c6e8b0d3'
down_revision: Union[str, None] = 'd1f3a5c7e9b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('mail_inbox_folder_width', sa.Integer(), nullable=True))
    op.add_column('users', sa.Column('mail_inbox_list_width', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'mail_inbox_list_width')
    op.drop_column('users', 'mail_inbox_folder_width')
