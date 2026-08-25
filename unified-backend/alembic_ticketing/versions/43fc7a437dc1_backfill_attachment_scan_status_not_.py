"""backfill attachment scan status not scanned

Revision ID: 43fc7a437dc1
Revises: 32efceb96456
Create Date: 2026-08-25 11:15:30.656302

Phase 2 hardening: Attachment.scan_status's default changed from
"pending" (implying an AV scan is in progress/will happen — none
exists anywhere in this codebase) to the static, honest "not_scanned".
Data-only migration: no DDL change (still String(20), no server_default
at the DB level — the "pending" default was always applied client-side
by SQLAlchemy/Pydantic, never a Postgres server_default), just a
one-time backfill of every row already carrying the old literal value.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '43fc7a437dc1'
down_revision: Union[str, None] = '32efceb96456'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE attachments SET scan_status = 'not_scanned' WHERE scan_status = 'pending'")


def downgrade() -> None:
    op.execute("UPDATE attachments SET scan_status = 'pending' WHERE scan_status = 'not_scanned'")