"""widen message_id and related Graph-identifier columns from 255 to 998

Revision ID: b7d9f1a3c5e7
Revises: a4c6e8b0d2f5
Create Date: 2026-09-19 00:00:00.000000

Option B for the Taral Sharma mail-ingestion incident: a schema-invalid
Microsoft Graph message (observed: an internetMessageId longer than 255
characters, from a Teams notification) used to raise a ValidationError
out of EmailRequest's construction, which — before the earlier
skip-and-continue fix (graph_mail_poller.py / mail_integration.py) —
crashed the whole poll tick before the mailbox checkpoint ever
advanced. That skip-fix remains in place unconditionally; this
migration is the separate, follow-up decision to also widen the limit
itself (255 -> 998) so a legitimately long Message-ID is stored and
processed instead of merely being safely skipped.

998 is RFC 5322 section 2.1.1's own hard limit on an unfolded header
line — the closest thing to a standards-derived ceiling for a
Message-ID value, well under PostgreSQL's B-tree single-key index size
limit (~2704 bytes).

Widened together, since they all carry either a literal RFC 5322
Message-ID value or a related Graph-derived identifier and must not
silently diverge in what they accept:
  - interactions.message_id (the dedup/idempotency column — the
    UniqueConstraint('message_id') / interactions_message_id_key
    constraint from c6f212b05143 is untouched, only the column's own
    type widens)
  - interactions.in_reply_to_message_id (must accept the same values
    as message_id, or a long original message's id could be stored
    but then never matched by a reply's own in_reply_to)
  - interactions.conversation_id and interactions.provider_message_id
    (Graph's own identifiers, not implicated by the incident, widened
    for consistency across every Graph-derived identifier field — see
    d4f6a8b0c2e4 and 0941a80891de for their original columns)
  - inbound_mail_failures.message_id (must match interactions.message_id's
    width, or a long-id message that fails for some other genuine
    reason could crash a second time trying to persist its own
    diagnostic failure record — see 32efceb96456 for the original
    column and its ux_inbound_mail_failures_message_mailbox unique
    index, which is untouched by this migration)

ALTER COLUMN TYPE VARCHAR(255) -> VARCHAR(998) is a metadata-only
operation in PostgreSQL for a widening change (no table rewrite, no
data loss, near-instant regardless of table size) — every existing
value already fits under 255 and is preserved exactly; all
constraints/indexes named above are untouched.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b7d9f1a3c5e7'
down_revision: Union[str, None] = 'a4c6e8b0d2f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'interactions', 'message_id',
        existing_type=sa.String(length=255),
        type_=sa.String(length=998),
        existing_nullable=True,
    )
    op.alter_column(
        'interactions', 'in_reply_to_message_id',
        existing_type=sa.String(length=255),
        type_=sa.String(length=998),
        existing_nullable=True,
    )
    op.alter_column(
        'interactions', 'conversation_id',
        existing_type=sa.String(length=255),
        type_=sa.String(length=998),
        existing_nullable=True,
    )
    op.alter_column(
        'interactions', 'provider_message_id',
        existing_type=sa.String(length=255),
        type_=sa.String(length=998),
        existing_nullable=True,
    )
    op.alter_column(
        'inbound_mail_failures', 'message_id',
        existing_type=sa.String(length=255),
        type_=sa.String(length=998),
        existing_nullable=False,
    )


def downgrade() -> None:
    # Narrowing back to 255 will fail if any row now holds a value
    # longer than 255 characters — an unavoidable, expected asymmetry
    # of widen-then-narrow; resolve/remove those rows first if this
    # downgrade is ever actually needed.
    op.alter_column(
        'inbound_mail_failures', 'message_id',
        existing_type=sa.String(length=998),
        type_=sa.String(length=255),
        existing_nullable=False,
    )
    op.alter_column(
        'interactions', 'provider_message_id',
        existing_type=sa.String(length=998),
        type_=sa.String(length=255),
        existing_nullable=True,
    )
    op.alter_column(
        'interactions', 'conversation_id',
        existing_type=sa.String(length=998),
        type_=sa.String(length=255),
        existing_nullable=True,
    )
    op.alter_column(
        'interactions', 'in_reply_to_message_id',
        existing_type=sa.String(length=998),
        type_=sa.String(length=255),
        existing_nullable=True,
    )
    op.alter_column(
        'interactions', 'message_id',
        existing_type=sa.String(length=998),
        type_=sa.String(length=255),
        existing_nullable=True,
    )
