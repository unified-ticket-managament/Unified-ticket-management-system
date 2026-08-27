"""add mailbox_poll_state table

Revision ID: e5a2c4f6b8d1
Revises: d3f9a1b5c7e2
Create Date: 2026-08-27 00:00:02.000000

Persisted counterpart to graph_mail_poller.py's in-memory-only
`_PollState.checkpoints`/`failure_counts` — see MailboxPollState's own
docstring for the full rationale. Purely additive: one new table, no
changes to any existing table.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e5a2c4f6b8d1'
down_revision: Union[str, None] = 'd3f9a1b5c7e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mailbox_poll_state",
        sa.Column("mailbox_address", sa.String(length=255), primary_key=True),
        sa.Column("checkpoint_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "consecutive_failures",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_summary", sa.Text(), nullable=True),
        sa.Column("last_alerted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("mailbox_poll_state")
