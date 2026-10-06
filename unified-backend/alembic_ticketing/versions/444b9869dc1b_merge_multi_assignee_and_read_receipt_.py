"""merge multi assignee and read receipt heads

Revision ID: 444b9869dc1b
Revises: c3e5a7b9d1f3, c4e6a8b0d2f7
Create Date: 2026-10-07 03:04:54.789263

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



# revision identifiers, used by Alembic.
revision: str = '444b9869dc1b'
down_revision: Union[str, None] = ('c3e5a7b9d1f3', 'c4e6a8b0d2f7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass