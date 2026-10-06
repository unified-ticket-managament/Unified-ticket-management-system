"""merge mail-folder hierarchy and read-receipt migration heads

Revision ID: c4e6a8b0d2f7
Revises: a7c9e1b3d5f0, f7a9c1e3b5d8
Create Date: 2026-10-06 00:00:00.000002

A pure merge: NO schema changes. Two independent branches both descended
from 9e3a5c7b2d4f:

- a7c9e1b3d5f0  add parent_folder_id to mail_folders   (mail-folder hierarchy)
- e5b7d9f1a3c8 -> f7a9c1e3b5d8  email_read_receipts + interactions.
  internet_message_id, then app_settings                (read receipts)

Neither touches the other's tables, so they commute; this revision only
reconciles the two heads into one so `alembic upgrade head` works again.
Neither parent revision is modified.
"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "c4e6a8b0d2f7"
down_revision: Union[str, Sequence[str], None] = ("a7c9e1b3d5f0", "f7a9c1e3b5d8")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Intentionally empty: reconciles two migration heads only.
    pass


def downgrade() -> None:
    # Intentionally empty: downgrading a merge simply splits the history
    # back into its two parents; each parent's own downgrade does the work.
    pass
