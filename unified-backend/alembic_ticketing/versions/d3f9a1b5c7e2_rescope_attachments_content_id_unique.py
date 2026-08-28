"""rescope attachments content_id uniqueness to per-interaction

Revision ID: d3f9a1b5c7e2
Revises: c8e0a2b4d6f8
Create Date: 2026-08-27 00:00:01.000000

Root-cause fix for a confirmed inbound-mail-ingestion bug (live
`inbound_mail_failures` evidence: 3+ distinct client/category
mailboxes, dozens of retries, all `ix_attachments_content_id`
UniqueViolationErrors). The original table-wide unique index on
`attachments.content_id` (f6b8d0a2c4e6_add_content_id_and_is_inline_
to_attac.py) was designed to guard the OUTBOUND composer-paste
feature, where content_id is always a freshly server-minted token and
collision really would mean a bug — its own docstring says exactly
that. A later, separate feature (inbound Graph attachment mapping)
stores Graph's own `contentId` value verbatim instead, and Graph/
Outlook legitimately reuses the same contentId for the same inline
image (typically a signature/logo) across many unrelated messages
from the same sender — normal behavior, not malformed mail. Every
subsequent genuinely distinct email embedding that same image hit the
table-wide unique index on INSERT, and since nothing caught the
resulting IntegrityError, the entire inbound-email transaction rolled
back — the whole message silently vanished, not just its attachment,
retried and re-failing identically forever.

The actual invariant that matters — a `cid:` reference must resolve
unambiguously within one message's own body — only requires
uniqueness scoped to `(interaction_id, content_id)`, not the whole
table. This migration drops the old index and recreates it scoped
that way; the partial `WHERE content_id IS NOT NULL` condition is
preserved unchanged. Purely a constraint-shape change — no column
changes, no data migration, no rows touched.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd3f9a1b5c7e2'
down_revision: Union[str, None] = 'c8e0a2b4d6f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_attachments_content_id", table_name="attachments")
    op.create_index(
        "ix_attachments_content_id",
        "attachments",
        ["interaction_id", "content_id"],
        unique=True,
        postgresql_where=sa.text("content_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_attachments_content_id", table_name="attachments")
    op.create_index(
        "ix_attachments_content_id",
        "attachments",
        ["content_id"],
        unique=True,
        postgresql_where=sa.text("content_id IS NOT NULL"),
    )
