"""merge local and teammate impersonator-column migrations

Revision ID: e61eab76fb7d
Revises: d8f0b2a4c6e9, 186504e67918
Create Date: 2026-08-24 17:24:09.717481

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



# revision identifiers, used by Alembic.
revision: str = 'e61eab76fb7d'
down_revision: Union[str, None] = ('d8f0b2a4c6e9', '186504e67918')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass