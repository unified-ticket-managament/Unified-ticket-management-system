"""add actor fields to ticket_audit_logs

Revision ID: 3f7c9a1e5b2d
Revises: 9b3e5f1a7c2d
Create Date: 2026-07-02 00:00:00.000000

Renames `changed_by` -> `actor_id` and adds `actor_name` (stored at
write time, not resolved via a join) + `actor_role` (AGENT / CLIENT
/ SYSTEM). The three pre-existing rows are backfilled: actor_name
resolved from `users` where actor_id is set, "System" otherwise;
actor_role AGENT where actor_id is set, SYSTEM otherwise.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '3f7c9a1e5b2d'
down_revision: Union[str, None] = '9b3e5f1a7c2d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('ticket_audit_logs', 'changed_by', new_column_name='actor_id')

    # op.add_column() does not implicitly CREATE TYPE for enum columns
    # (only op.create_table() does that) — the type must be created
    # explicitly first, or add_column fails with UndefinedObject.
    actor_role_enum = sa.Enum('AGENT', 'CLIENT', 'SYSTEM', name='audit_actor_role_enum')
    actor_role_enum.create(op.get_bind(), checkfirst=True)

    op.add_column('ticket_audit_logs', sa.Column('actor_name', sa.String(255), nullable=True))
    op.add_column(
        'ticket_audit_logs',
        sa.Column(
            'actor_role',
            actor_role_enum,
            nullable=True,
        ),
    )

    op.execute("""
        UPDATE ticket_audit_logs
        SET actor_name = COALESCE(
                (SELECT u.name FROM users u WHERE u.user_id = ticket_audit_logs.actor_id),
                'System'
            ),
            actor_role = (CASE WHEN actor_id IS NOT NULL THEN 'AGENT' ELSE 'SYSTEM' END)::audit_actor_role_enum
        WHERE actor_name IS NULL
    """)

    op.alter_column('ticket_audit_logs', 'actor_name', nullable=False)
    op.alter_column('ticket_audit_logs', 'actor_role', nullable=False)


def downgrade() -> None:
    op.drop_column('ticket_audit_logs', 'actor_role')
    op.drop_column('ticket_audit_logs', 'actor_name')
    op.execute("DROP TYPE IF EXISTS audit_actor_role_enum")
    op.alter_column('ticket_audit_logs', 'actor_id', new_column_name='changed_by')
