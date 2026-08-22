"""add content_id and is_inline to attachments

Revision ID: f6b8d0a2c4e6
Revises: a5c7e9f1b3d6
Create Date: 2026-08-22 00:00:00.000000

Supports pasted-inline-image clipboard paste (Outlook-style paste in
the Mail/Ticket composers): a screenshot pasted into an HTML message
body needs a Microsoft Graph-recognizable `contentId` so the body's
`<img src="cid:...">` reference resolves to the right uploaded
attachment, and an `is_inline` flag so it's never surfaced as a
regular downloadable attachment alongside the message.

Purely additive: two new nullable/defaulted columns, no changes to
any existing column, no backfill (this is a new capability, not a
reinterpretation of existing rows — every pre-existing attachment
correctly has content_id=NULL, is_inline=False). A unique partial
index on content_id guards against a future bug accidentally minting
a duplicate token and lets a content_id lookup use an index rather
than a sequential scan.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f6b8d0a2c4e6'
down_revision: Union[str, None] = 'a5c7e9f1b3d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "attachments",
        sa.Column("content_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "attachments",
        sa.Column(
            "is_inline",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        "ix_attachments_content_id",
        "attachments",
        ["content_id"],
        unique=True,
        postgresql_where=sa.text("content_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_attachments_content_id", table_name="attachments")
    op.drop_column("attachments", "is_inline")
    op.drop_column("attachments", "content_id")
