"""add message_read_receipts table for persisted unread tracking

Revision ID: 2c5e8f1a3d6b
Revises: 7b3d5f9a1c4e
Create Date: 2026-07-13 00:00:00.000002

Purely additive: a brand-new table, no changes to any existing table.
"Unread" has always been a client-side-only concept (the Mail UI's
`openedIds` React state — reset on every reload, never shared across
devices or sessions). This gives it a real, persisted home without
touching that existing behavior — nothing reads or writes this table
yet except the new opt-in write-on-open call and the `is_read`
annotation on GET /inbox responses; the frontend's own unread
rendering is untouched (see InboxItemResponse.is_read's docstring).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '2c5e8f1a3d6b'
down_revision: Union[str, None] = '7b3d5f9a1c4e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "message_read_receipts",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("interaction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "read_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"]),
        sa.ForeignKeyConstraint(["interaction_id"], ["interactions.interaction_id"]),
        sa.PrimaryKeyConstraint("user_id", "interaction_id"),
    )
    # Backs the batched "which of these interaction_ids has this user
    # already read" lookup (GET /inbox's is_read annotation, and the
    # optional unread_only filter) — a plain index on interaction_id
    # alone, since user_id is already the leading PK column.
    op.create_index(
        "idx_message_read_receipts_interaction_id",
        "message_read_receipts",
        ["interaction_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_message_read_receipts_interaction_id",
        table_name="message_read_receipts",
    )
    op.drop_table("message_read_receipts")
