"""add storage fields to attachments

Revision ID: 7a1f9c4d2e6b
Revises: 50888f2e4f85
Create Date: 2026-07-02 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7a1f9c4d2e6b'
down_revision: Union[str, None] = '50888f2e4f85'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'attachments',
        sa.Column('bucket_name', sa.String(255), nullable=True),
    )
    op.add_column(
        'attachments',
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'attachments',
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('attachments', 'updated_at')
    op.drop_column('attachments', 'created_at')
    op.drop_column('attachments', 'bucket_name')
