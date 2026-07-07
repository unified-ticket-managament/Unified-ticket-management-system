"""Add categories table and users.category_id

Revision ID: cc5cf10fe410
Revises: 9cadc1a089a3
Create Date: 2026-07-07 00:00:00.000000

"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cc5cf10fe410'
down_revision: Union[str, None] = '9cadc1a089a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Fixed IDs (not regenerated on every run) so this migration is safe to
# read/reason about and re-run against a fresh DB deterministically.
CATEGORY_SEED = [
    (uuid.UUID("a3efa585-dbbf-418c-85fc-314b569dce23"), "Eligibility"),
    (uuid.UUID("e219cf57-8be5-4296-b495-247d7a53dfc0"), "Patient Calling"),
    (uuid.UUID("804aced2-8833-4049-b506-8a260c4e18e8"), "AR"),
    (uuid.UUID("39146d2a-bfb9-4544-a27e-96af929a6794"), "Payment Posting"),
    (uuid.UUID("d1ac4422-17c3-4f77-827d-7245a3f2b657"), "PA"),
    (uuid.UUID("b90953f7-fabb-4803-9a7f-a03471dbcd6a"), "Charge Entry"),
    (uuid.UUID("d6e00cb2-a9e9-4df0-8407-70c4a2884193"), "Claims"),
]


def upgrade() -> None:
    op.create_table(
        'categories',
        sa.Column('category_id', sa.UUID(), nullable=False),
        sa.Column('category_name', sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint('category_id'),
    )
    op.create_index(
        op.f('ix_categories_category_name'), 'categories', ['category_name'], unique=True
    )

    # Seed the initial work-specialization categories. ON CONFLICT DO
    # NOTHING makes this safe if the migration is ever re-run against a
    # DB that already has these rows (matches category_name's unique
    # index) rather than erroring.
    categories_table = sa.table(
        'categories',
        sa.column('category_id', sa.UUID()),
        sa.column('category_name', sa.String()),
    )
    op.bulk_insert(
        categories_table,
        [{"category_id": cid, "category_name": name} for cid, name in CATEGORY_SEED],
    )

    op.add_column('users', sa.Column('category_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_users_category_id_categories',
        'users',
        'categories',
        ['category_id'],
        ['category_id'],
    )


def downgrade() -> None:
    op.drop_constraint('fk_users_category_id_categories', 'users', type_='foreignkey')
    op.drop_column('users', 'category_id')
    op.drop_index(op.f('ix_categories_category_name'), table_name='categories')
    op.drop_table('categories')
