"""add external-link (cloud attachment) support to attachments

Revision ID: a5c7e9f1b3d6
Revises: b5d7f9a1c3e6
Create Date: 2026-08-21 00:00:00.000000

Outlook's "Attach as cloud link" (a OneDrive/SharePoint share) was
confirmed live to create no real Microsoft Graph attachment object at
all — `hasAttachments` comes back False and the message's `attachments`
collection is empty; the only trace of the file is an <a> anchor
embedded directly in the HTML body (see
mail_mapping_service.extract_cloud_link_attachments). Recording one of
these as a normal Attachment row needs `storage_key` to be nullable
(there are no real bytes to upload), plus a place to keep the original
URL and a flag distinguishing this from a real downloadable file.

Purely additive: `storage_key` becomes nullable (loosening, not
narrowing, an existing constraint — no data loss for any existing row,
which all already have a real storage_key), and two new nullable/
defaulted columns are added. No backfill needed since this is a new
capability, not a reinterpretation of existing rows.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a5c7e9f1b3d6'
down_revision: Union[str, None] = 'b5d7f9a1c3e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "attachments",
        "storage_key",
        existing_type=sa.Text(),
        nullable=True,
    )
    op.add_column(
        "attachments",
        sa.Column("external_url", sa.Text(), nullable=True),
    )
    op.add_column(
        "attachments",
        sa.Column(
            "is_external_link",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("attachments", "is_external_link")
    op.drop_column("attachments", "external_url")
    op.alter_column(
        "attachments",
        "storage_key",
        existing_type=sa.Text(),
        nullable=False,
    )
