"""merge impersonation and distribution-list branches

Revision ID: 186504e67918
Revises: c5f7b9d1e3a6, c7e9a1b3d5f8
Create Date: 2026-08-23 12:39:06.040179

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



# revision identifiers, used by Alembic.
revision: str = '186504e67918'
down_revision: Union[str, None] = ('c5f7b9d1e3a6', 'c7e9a1b3d5f8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass