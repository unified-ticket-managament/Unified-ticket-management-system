"""add is_rule_created to mail_folders

Revision ID: c3e6a8b0d2f5
Revises: b2d4f6a8c0e3
Create Date: 2026-08-24 00:00:00.000001

Backs the "delete a Mail Rule -> delete only the folder it exclusively
owns" fix: `created_by` alone can't distinguish a rule-auto-created
folder from a manually-created one (POST /folders sets created_by too),
so RuleService.delete's cleanup step used to risk either leaving
rule-created folders orphaned forever or (worse) deleting a folder a
user created by hand. `is_rule_created` is the real signal, set only
by rule_folder_sync.ensure_folder at creation time. Purely additive —
every existing folder (whichever path created it) defaults to False,
which is the safe direction: a pre-existing folder is simply never
auto-deleted by this cleanup going forward, rather than guessing.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3e6a8b0d2f5'
down_revision: Union[str, None] = 'b2d4f6a8c0e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "mail_folders",
        sa.Column(
            "is_rule_created",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("mail_folders", "is_rule_created")
