"""replace category_name_enum values with the real org's processes

Revision ID: d3f5a7b9c1e3
Revises: a8c0e2f4b6d9
Create Date: 2026-08-06 00:00:00.000000

Part of the real-org-data migration (see scripts/org_seed/): the 7
original category names (Eligibility, Patient Calling, AR, Payment
Posting, PA, Charge Entry, Claims) don't match any of the real
organization's "Process" values except AR and Payment Posting.
Approved to be replaced outright with the 8 real process names (AR,
Referral, Authorization, IV, Credentialing, Coding, Payment Posting,
Quality) rather than layered on top of the dummy set.

Postgres has no ALTER TYPE ... DROP VALUE, so this clears every row
that references the old values first (safe: this table and its
consumers hold only dummy data at this point in the migration
history), then drops and recreates the enum type under the same name,
then reseeds the 8 new categories with fixed UUIDs (same pattern as
cc5cf10fe410_add_categories_table_and_user_category_id.py).
"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd3f5a7b9c1e3'
down_revision: Union[str, None] = 'a8c0e2f4b6d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_CATEGORY_NAMES = (
    "Eligibility",
    "Patient Calling",
    "AR",
    "Payment Posting",
    "PA",
    "Charge Entry",
    "Claims",
)

NEW_CATEGORY_SEED = [
    (uuid.UUID("1a2b3c4d-0001-4a00-8000-000000000001"), "AR"),
    (uuid.UUID("1a2b3c4d-0001-4a00-8000-000000000002"), "Referral"),
    (uuid.UUID("1a2b3c4d-0001-4a00-8000-000000000003"), "Authorization"),
    (uuid.UUID("1a2b3c4d-0001-4a00-8000-000000000004"), "IV"),
    (uuid.UUID("1a2b3c4d-0001-4a00-8000-000000000005"), "Credentialing"),
    (uuid.UUID("1a2b3c4d-0001-4a00-8000-000000000006"), "Coding"),
    (uuid.UUID("1a2b3c4d-0001-4a00-8000-000000000007"), "Payment Posting"),
    (uuid.UUID("1a2b3c4d-0001-4a00-8000-000000000008"), "Quality"),
]

NEW_CATEGORY_NAMES = tuple(name for _, name in NEW_CATEGORY_SEED)

old_category_name_enum = postgresql.ENUM(*OLD_CATEGORY_NAMES, name="category_name_enum")
new_category_name_enum = postgresql.ENUM(*NEW_CATEGORY_NAMES, name="category_name_enum")

categories_table = sa.table(
    'categories',
    sa.column('category_id', sa.UUID()),
    sa.column('category_name', sa.String()),
)


def upgrade() -> None:
    # Clear every row that references the old enum values — this
    # database holds only dummy data at this point in the migration
    # history (see scripts/org_seed/import_org_data.py, which re-seeds
    # real users/categories immediately after migrations run).
    op.execute("UPDATE users SET category_id = NULL")
    op.execute("DELETE FROM reporting_manager_teams")
    op.execute("DELETE FROM categories")

    op.execute(
        "ALTER TABLE categories ALTER COLUMN category_name TYPE VARCHAR(100) USING category_name::text"
    )
    old_category_name_enum.drop(op.get_bind(), checkfirst=True)
    new_category_name_enum.create(op.get_bind(), checkfirst=True)
    op.execute(
        "ALTER TABLE categories ALTER COLUMN category_name TYPE category_name_enum "
        "USING category_name::category_name_enum"
    )

    op.bulk_insert(
        categories_table,
        [{"category_id": cid, "category_name": name} for cid, name in NEW_CATEGORY_SEED],
    )


def downgrade() -> None:
    op.execute("UPDATE users SET category_id = NULL")
    op.execute("DELETE FROM reporting_manager_teams")
    op.execute("DELETE FROM categories")

    op.execute(
        "ALTER TABLE categories ALTER COLUMN category_name TYPE VARCHAR(100) USING category_name::text"
    )
    new_category_name_enum.drop(op.get_bind(), checkfirst=True)
    old_category_name_enum.create(op.get_bind(), checkfirst=True)
    op.execute(
        "ALTER TABLE categories ALTER COLUMN category_name TYPE category_name_enum "
        "USING category_name::category_name_enum"
    )
