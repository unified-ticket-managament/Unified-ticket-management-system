"""add inbound mail failures table

Revision ID: 32efceb96456
Revises: 96ab43631616
Create Date: 2026-08-25 10:53:25.762566

Phase 2 hardening: a persisted, queryable record of inbound-mail
processing failures (see app/ticketing/models/inbound_mail_failure.py)
— backs, but does not replace, graph_mail_poller.py's own in-memory
retry counter, which resets on every process restart and has no
counterpart at all on the webhook transport.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '32efceb96456'
down_revision: Union[str, None] = '96ab43631616'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "inbound_mail_failures",
        sa.Column("inbound_mail_failure_id", sa.UUID(), nullable=False),
        sa.Column("message_id", sa.String(length=255), nullable=False),
        sa.Column("mailbox_address", sa.String(length=255), nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("inbound_mail_failure_id"),
    )
    op.create_index(
        "ux_inbound_mail_failures_message_mailbox",
        "inbound_mail_failures",
        ["message_id", "mailbox_address"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ux_inbound_mail_failures_message_mailbox",
        table_name="inbound_mail_failures",
    )
    op.drop_table("inbound_mail_failures")