"""add + backfill subject column on interactions

Revision ID: f1a3c5e7b9d2
Revises: b8d0f2a4c6e8
Create Date: 2026-07-11 00:00:00.000000

Real column instead of extracting `subject` from payload JSON on
every read — used by the two cross-cutting list endpoints (GET
/tickets/interactions, GET /tickets/{id}/interactions) so they can
show a one-line summary without shipping full payload. Nullable at
the DB level: ATTACHMENT rows and the 5 retired-and-later-deleted
interaction types (see the follow-up cleanup migration) never carry
one, and that's fine — this column only means something for
EMAIL/REPLY/INTERNAL_NOTE rows.

Backfill for existing rows:
- EMAIL: every EMAIL payload already carries `subject` (inbound
  intake + compose_email both set it).
- REPLY: inherits its thread root's subject — a reply's own payload
  has no subject key of its own ({message, envelope, cc, bcc,
  dispatch_status} only). Replies point straight at the root, never
  at another reply, so one self-join is sufficient.
- INTERNAL_NOTE: never had a subject before this — historical rows
  get a placeholder; the mandatory-field rule this migration's
  matching code change adds is going-forward only.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f1a3c5e7b9d2'
down_revision: Union[str, None] = 'b8d0f2a4c6e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "interactions",
        sa.Column("subject", sa.String(length=500), nullable=True),
    )

    op.execute(
        """
        UPDATE interactions
        SET subject = payload->>'subject'
        WHERE interaction_type = 'EMAIL' AND payload ? 'subject'
        """
    )

    op.execute(
        """
        UPDATE interactions AS r
        SET subject = root.subject
        FROM interactions AS root
        WHERE r.interaction_type = 'REPLY'
          AND r.parent_interaction_id = root.interaction_id
          AND root.subject IS NOT NULL
        """
    )

    op.execute(
        """
        UPDATE interactions
        SET subject = '(no subject)'
        WHERE interaction_type = 'INTERNAL_NOTE' AND subject IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("interactions", "subject")
