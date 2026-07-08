"""add conversation_id/in_reply_to_message_id/references to interactions

Revision ID: d4f6a8b0c2e4
Revises: b2c4d6e8f0a2
Create Date: 2026-07-08 00:00:00.000000

Outlook-style threading needs to match a reply against its conversation
without deserializing `payload` JSON. `parent_interaction_id` and
`message_id` already exist; this adds the three remaining Graph-ready
threading columns the matching priority (conversation_id -> in_reply_to
-> references) reads and writes. All nullable — every pre-existing row
(and every dummy-mail-flow row until Task 1 ships real Graph data)
simply leaves them NULL.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd4f6a8b0c2e4'
down_revision: Union[str, None] = 'b2c4d6e8f0a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "interactions",
        sa.Column("conversation_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "interactions",
        sa.Column("in_reply_to_message_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "interactions",
        sa.Column("references", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index(
        "ix_interactions_conversation_id", "interactions", ["conversation_id"]
    )
    op.create_index(
        "ix_interactions_in_reply_to_message_id", "interactions", ["in_reply_to_message_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_interactions_in_reply_to_message_id", table_name="interactions")
    op.drop_index("ix_interactions_conversation_id", table_name="interactions")
    op.drop_column("interactions", "references")
    op.drop_column("interactions", "in_reply_to_message_id")
    op.drop_column("interactions", "conversation_id")
