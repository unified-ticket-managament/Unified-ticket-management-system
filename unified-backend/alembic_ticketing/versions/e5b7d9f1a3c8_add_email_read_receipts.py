"""add email_read_receipts table and interactions.internet_message_id

Revision ID: e5b7d9f1a3c8
Revises: 9e3a5c7b2d4f
Create Date: 2026-10-06 00:00:00.000000

Purely additive, for the Outlook-style read-receipt (MDN) feature:

- interactions.internet_message_id: the REAL Graph/Exchange RFC
  Message-ID of an outbound message (nullable; the existing unique
  interactions.message_id is a locally generated placeholder for
  outbound rows and is deliberately left untouched). Partial index —
  only rows that ever captured one.
- email_read_receipts: one row per tracked To/Cc recipient of a
  message sent with a receipt requested. UNIQUE(interaction_id,
  recipient_email) plus a partial unique index on mdn_message_id make
  receipt ingestion idempotent.

No existing table's data or constraints change; downgrade drops
exactly what upgrade created.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e5b7d9f1a3c8"
down_revision: Union[str, None] = "9e3a5c7b2d4f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "interactions",
        sa.Column("internet_message_id", sa.String(length=998), nullable=True),
    )
    op.create_index(
        "ix_interactions_internet_message_id",
        "interactions",
        ["internet_message_id"],
        postgresql_where=sa.text("internet_message_id IS NOT NULL"),
    )

    op.create_table(
        "email_read_receipts",
        sa.Column("receipt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("interaction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recipient_email", sa.String(length=320), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="REQUESTED",
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disposition", sa.Text(), nullable=True),
        sa.Column("mdn_message_id", sa.String(length=998), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["interaction_id"],
            ["interactions.interaction_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("receipt_id"),
        sa.UniqueConstraint(
            "interaction_id",
            "recipient_email",
            name="uq_email_read_receipts_interaction_recipient",
        ),
    )
    op.create_index(
        "ix_email_read_receipts_interaction_id",
        "email_read_receipts",
        ["interaction_id"],
    )
    op.create_index(
        "uq_email_read_receipts_mdn_message_id",
        "email_read_receipts",
        ["mdn_message_id"],
        unique=True,
        postgresql_where=sa.text("mdn_message_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_email_read_receipts_mdn_message_id", table_name="email_read_receipts"
    )
    op.drop_index(
        "ix_email_read_receipts_interaction_id", table_name="email_read_receipts"
    )
    op.drop_table("email_read_receipts")
    op.drop_index("ix_interactions_internet_message_id", table_name="interactions")
    op.drop_column("interactions", "internet_message_id")
