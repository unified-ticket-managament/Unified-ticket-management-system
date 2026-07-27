"""merge heads

Revision ID: b7d9f1a3c5e8
Revises: e4b6d8f0a2c5, f3a5c7e9b1d4
Create Date: 2026-07-27 00:00:00.000000

Merges two pre-existing, independently-created heads (both branching
off d2a4c6e8f0b3) — no schema impact, purely so `alembic upgrade head`
has a single target again.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7d9f1a3c5e8'
down_revision: Union[str, Sequence[str], None] = ('e4b6d8f0a2c5', 'f3a5c7e9b1d4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
