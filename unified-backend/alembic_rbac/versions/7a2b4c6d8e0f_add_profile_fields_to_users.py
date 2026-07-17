"""add profile fields to users

Revision ID: 7a2b4c6d8e0f
Revises: 3f9efae8e1ae
Create Date: 2026-07-17 00:00:00.000000

Backs the Profile page redesign (see root CLAUDE.md's Profile module
section): every field the page displays/edits now comes from a real
`users` column instead of a client-only zustand store. `department`/
`team` are plain free-text columns, deliberately independent of the
existing `category_id` column — that one still drives real RBAC/
ticket-routing logic and is untouched by this migration or the
Profile page's own edit form.

Data migration: `department` is backfilled from the user's current
category name where one is assigned (best-effort continuity, not
fabricated data — left NULL otherwise). `language`/`date_format`/
`time_format`/`default_dashboard` get a server-side default matching
the values the old client-only store used to default to, so an
existing user's effective preference is unchanged by this becoming
DB-backed. Every other new column is left NULL for pre-existing rows
— there is no prior source of truth for date_of_birth, alternate
email, phone number, office location, team, or time zone.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7a2b4c6d8e0f'
down_revision: Union[str, None] = '3f9efae8e1ae'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('date_of_birth', sa.Date(), nullable=True))
    op.add_column('users', sa.Column('alternate_email', sa.String(length=255), nullable=True))
    op.add_column('users', sa.Column('phone_number', sa.String(length=30), nullable=True))
    op.add_column('users', sa.Column('office_location', sa.String(length=255), nullable=True))
    op.add_column('users', sa.Column('department', sa.String(length=100), nullable=True))
    op.add_column('users', sa.Column('team', sa.String(length=100), nullable=True))
    op.add_column(
        'users',
        sa.Column('language', sa.String(length=10), nullable=True, server_default='en'),
    )
    op.add_column(
        'users',
        sa.Column('date_format', sa.String(length=20), nullable=True, server_default='MM/DD/YYYY'),
    )
    op.add_column(
        'users',
        sa.Column('time_format', sa.String(length=10), nullable=True, server_default='12h'),
    )
    op.add_column('users', sa.Column('time_zone', sa.String(length=50), nullable=True))
    op.add_column(
        'users',
        sa.Column('default_dashboard', sa.String(length=50), nullable=True, server_default='Dashboard'),
    )

    # Backfill department from the user's existing category assignment
    # where one exists — the only new column with a real, non-fabricated
    # prior source of truth to draw from.
    op.execute(
        """
        UPDATE users
        SET department = categories.category_name::text
        FROM categories
        WHERE users.category_id = categories.category_id
          AND users.department IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column('users', 'default_dashboard')
    op.drop_column('users', 'time_zone')
    op.drop_column('users', 'time_format')
    op.drop_column('users', 'date_format')
    op.drop_column('users', 'language')
    op.drop_column('users', 'team')
    op.drop_column('users', 'department')
    op.drop_column('users', 'office_location')
    op.drop_column('users', 'phone_number')
    op.drop_column('users', 'alternate_email')
    op.drop_column('users', 'date_of_birth')
