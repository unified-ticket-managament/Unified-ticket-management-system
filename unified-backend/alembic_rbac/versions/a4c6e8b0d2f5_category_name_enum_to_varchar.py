"""convert categories.category_name from a native enum to varchar

Revision ID: a4c6e8b0d2f5
Revises: f1a3c5e7b9d2
Create Date: 2026-08-21 00:00:00.000000

`categories.category_name` was a native Postgres ENUM
(`category_name_enum`), backed by a fixed Python `CategoryName` enum
with exactly 8 members — every new category required a code change
plus an `ALTER TYPE ... ADD VALUE` migration here. Converting to a
plain, unique, indexed VARCHAR lets an admin create a category (e.g.
PATIENTOUTREACH) at runtime through the existing Category CRUD API
with no code change or migration. Existing category rows/values are
preserved untouched by the cast.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4c6e8b0d2f5'
down_revision: Union[str, None] = 'f1a3c5e7b9d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The 8 original enum members (see the now-deleted
# shared_models.models.category.CategoryName) — only needed by
# downgrade() to recreate the type.
_ORIGINAL_CATEGORY_NAMES = [
    "AR", "Referral", "Authorization", "IV",
    "Credentialing", "Coding", "Payment Posting", "Quality",
]


def upgrade() -> None:
    op.alter_column(
        'categories',
        'category_name',
        existing_type=sa.Enum(name='category_name_enum'),
        type_=sa.String(length=150),
        postgresql_using='category_name::text',
        existing_nullable=False,
    )
    op.execute('DROP TYPE category_name_enum')


def downgrade() -> None:
    """
    Best-effort only: fails if any row holds a category_name added
    after this migration ran, since that value has no member in the
    recreated enum. There is no way to recover the original enum
    type's exact member set once new dynamic categories exist — same
    "no meaningful downgrade" convention already used elsewhere in
    this codebase for one-way data/shape changes.
    """

    category_name_enum = sa.Enum(*_ORIGINAL_CATEGORY_NAMES, name='category_name_enum')
    category_name_enum.create(op.get_bind(), checkfirst=True)

    op.alter_column(
        'categories',
        'category_name',
        existing_type=sa.String(length=150),
        type_=category_name_enum,
        postgresql_using='category_name::category_name_enum',
        existing_nullable=False,
    )
