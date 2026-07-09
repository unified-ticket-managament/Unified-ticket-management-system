"""Convert categories.category_name to a native enum

Revision ID: 579d6f955206
Revises: cc5cf10fe410
Create Date: 2026-07-07 00:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '579d6f955206'
down_revision: Union[str, None] = 'cc5cf10fe410'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CATEGORY_NAMES = (
    "Eligibility",
    "Patient Calling",
    "AR",
    "Payment Posting",
    "PA",
    "Charge Entry",
    "Claims",
)

category_name_enum = postgresql.ENUM(
    *CATEGORY_NAMES,
    name="category_name_enum",
)


def upgrade() -> None:
    # Existing rows (seeded by cc5cf10fe410) already hold exactly
    # these values, so the USING cast below is a clean, lossless
    # conversion — not a fresh CREATE TABLE like TicketStatus/
    # TicketPriority got on day one.
    category_name_enum.create(op.get_bind(), checkfirst=True)

    op.execute(
        "ALTER TABLE categories "
        "ALTER COLUMN category_name TYPE category_name_enum "
        "USING category_name::category_name_enum"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE categories "
        "ALTER COLUMN category_name TYPE VARCHAR(100) "
        "USING category_name::text"
    )

    category_name_enum.drop(op.get_bind(), checkfirst=True)
