"""add parent_folder_id to mail_folders

Revision ID: a7c9e1b3d5f0
Revises: 9e3a5c7b2d4f
Create Date: 2026-10-05 00:00:00.000000

Nested (Outlook-style) folders: a nullable self-referencing FK. Purely
additive — every existing folder keeps parent_folder_id = NULL (root).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7c9e1b3d5f0'
down_revision: Union[str, None] = '9e3a5c7b2d4f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "mail_folders",
        sa.Column("parent_folder_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "mail_folders_parent_folder_id_fkey",
        "mail_folders",
        "mail_folders",
        ["parent_folder_id"],
        ["folder_id"],
    )
    op.create_check_constraint(
        "ck_mail_folders_not_own_parent",
        "mail_folders",
        "parent_folder_id IS NULL OR parent_folder_id <> folder_id",
    )
    op.create_index(
        "ix_mail_folders_parent_folder_id", "mail_folders", ["parent_folder_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_mail_folders_parent_folder_id", table_name="mail_folders")
    op.drop_constraint("ck_mail_folders_not_own_parent", "mail_folders", type_="check")
    op.drop_constraint(
        "mail_folders_parent_folder_id_fkey", "mail_folders", type_="foreignkey"
    )
    op.drop_column("mail_folders", "parent_folder_id")
