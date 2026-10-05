"""add email_signatures and email_signature_images

Revision ID: a7c9e1b3d5f8
Revises: f2a4c6e8b0d3
Create Date: 2026-10-05 00:00:00.000000

Multiple named email signatures per user (one default), replacing the
single users.signature_html column as the composer's source of truth —
see app/rbac/models/email_signature.py.

Backfill: every user with a non-empty users.signature_html gets one
"Default Signature" row, marked default, whose html is that value
followed by the company logo block the composer has always appended
after it (frontend richText.ts buildSignatureBlockHtml, now removed) —
so the first composer opened after deploy shows exactly the signature
the user had before, logo included. The logo simply becomes ordinary,
editable signature content instead of being hard-coded for everyone.

users.signature_html is deliberately NOT dropped: it stays the legacy
fallback for a user with no saved signatures (new users are still
seeded there by UserService.create_user), and keeping it makes this
migration safely reversible — downgrade just drops the new tables.

Self-contained (no app imports), same convention as this chain's other
data-backfill migrations; one INSERT ... FROM (VALUES ...) round trip
rather than a per-row loop (see d1f3a5c7e9b1 for why that matters on
this DB link), with ids generated here rather than relying on a
database-side UUID function.
"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a7c9e1b3d5f8'
down_revision: Union[str, None] = 'f2a4c6e8b0d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Must match app/ticketing/services/company_signature_logo.py's
# COMPANY_LOGO_CONTENT_ID and EmailSignatureService.COMPANY_LOGO_BLOCK_HTML.
COMPANY_LOGO_BLOCK_HTML = (
    '<div><img src="cid:company-signature-logo-v1" alt="Probe Practice Solutions" width="150"></div>'
)
BACKFILL_SIGNATURE_NAME = "Default Signature"


def upgrade() -> None:
    op.create_table(
        'email_signatures',
        sa.Column('signature_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('html', sa.Text(), nullable=False),
        sa.Column('is_default', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('signature_id'),
    )
    op.create_index(
        op.f('ix_email_signatures_user_id'), 'email_signatures', ['user_id'], unique=False,
    )
    # At most one default per user, enforced by the database itself.
    op.create_index(
        'uq_email_signatures_one_default_per_user',
        'email_signatures',
        ['user_id'],
        unique=True,
        postgresql_where=sa.text('is_default'),
    )

    op.create_table(
        'email_signature_images',
        sa.Column('image_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('mime_type', sa.String(length=100), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('storage_key', sa.Text(), nullable=False),
        sa.Column('bucket_name', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('image_id'),
        sa.UniqueConstraint('storage_key'),
    )
    op.create_index(
        op.f('ix_email_signature_images_user_id'),
        'email_signature_images', ['user_id'], unique=False,
    )

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT user_id, signature_html FROM users "
            "WHERE signature_html IS NOT NULL AND btrim(signature_html) <> ''"
        )
    ).fetchall()

    backfill = build_backfill_rows(rows)
    if not backfill:
        return

    values_sql_parts = []
    params: dict[str, str] = {"name": BACKFILL_SIGNATURE_NAME}
    for i, (signature_id, user_id, html) in enumerate(backfill):
        values_sql_parts.append(f"(CAST(:sid{i} AS uuid), CAST(:uid{i} AS uuid), :html{i})")
        params[f"sid{i}"] = signature_id
        params[f"uid{i}"] = user_id
        params[f"html{i}"] = html

    bind.execute(
        sa.text(
            f"""
            INSERT INTO email_signatures
                (signature_id, user_id, name, html, is_default, created_at, updated_at)
            SELECT v.signature_id, v.user_id, :name, v.html, true, now(), now()
            FROM (VALUES {", ".join(values_sql_parts)}) AS v(signature_id, user_id, html)
            """
        ),
        params,
    )


def build_backfill_rows(rows) -> list[tuple[str, str, str]]:
    """
    (signature_id, user_id, html) for each legacy signature row — the
    user's signature_html followed by the company logo block, exactly
    as the composer combined them before this migration.
    """

    return [
        (str(uuid.uuid4()), str(row.user_id), f"{row.signature_html}{COMPANY_LOGO_BLOCK_HTML}")
        for row in rows
        if row.signature_html and row.signature_html.strip()
    ]


def downgrade() -> None:
    op.drop_index(op.f('ix_email_signature_images_user_id'), table_name='email_signature_images')
    op.drop_table('email_signature_images')
    op.drop_index('uq_email_signatures_one_default_per_user', table_name='email_signatures')
    op.drop_index(op.f('ix_email_signatures_user_id'), table_name='email_signatures')
    op.drop_table('email_signatures')
