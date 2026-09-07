"""add signature_html to users

Revision ID: d1f3a5c7e9b1
Revises: b3e5f7a9c1d4
Create Date: 2026-09-07 00:00:00.000000

Per-user, user-editable email signature (Outlook-style). Replaces the
previous mechanism where `app/ticketing/services/email_envelope.py`'s
`build_agent_signature`/`build_agent_signature_html` computed a
signature fresh at send time from `name`/`designation`/`role.name`/
`department`/`phone_number` and appended it server-side, unconditionally,
with no way for a user to see, edit, or remove it. Those two functions
are kept, but only as (a) this migration's backfill renderer and (b) the
default seed for a brand-new user — never again on the send path.

Nullable, free-form HTML (already sanitized through the existing
`sanitize_outbound_html` before it's ever persisted — see
`AuthService.update_profile`). No `signature_updated_at`/side table:
this is a strict 1:1 per-user value, same flat-column convention as
every other Profile-module field on this table.

Backfill: every existing row gets the exact HTML
`build_agent_signature_html` would have produced for it today, computed
here (not imported from app code — migrations stay self-contained, same
convention as this chain's other data-backfill migrations) from each
row's own name/designation/role name/department/phone_number. This is
what makes the cutover invisible: nobody's outgoing mail silently stops
being signed the moment the server-side auto-append is removed.
"""
import html
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1f3a5c7e9b1'
down_revision: Union[str, None] = 'b3e5f7a9c1d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _render_signature_html(
    name: str,
    designation: str | None,
    role_name: str | None,
    department: str | None,
    phone_number: str | None,
) -> str:
    """
    Mirrors app/ticketing/services/email_envelope.py's
    build_agent_signature/build_agent_signature_html byte-for-byte, so
    the backfilled value is identical to what today's send-time
    mechanism would have produced for this same row.
    """

    divider = "-" * 40
    title = designation or role_name

    lines = [divider, "Regards,", name]
    if title:
        lines.append(title)
    lines.append("Probe Practice Solutions")
    if department:
        lines.append(department)
    if phone_number:
        lines.append(phone_number)
    lines.append(divider)

    plain = "\n".join(lines)
    return f'<div>{html.escape(plain).replace(chr(10), "<br>")}</div>'


def upgrade() -> None:
    op.add_column('users', sa.Column('signature_html', sa.Text(), nullable=True))

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT u.user_id, u.name, u.designation, u.department, u.phone_number, r.name AS role_name
            FROM users u
            LEFT JOIN roles r ON r.role_id = u.role_id
            """
        )
    ).fetchall()

    if not rows:
        return

    # One round trip for the whole backfill (a per-row UPDATE loop
    # measured ~1s/statement against this environment's DB link — see
    # root CLAUDE.md's Performance-pass section on this link's per-
    # statement latency dominating over query cost) via a single
    # UPDATE ... FROM (VALUES ...) rather than one UPDATE per user.
    values_sql_parts = []
    params: dict[str, str] = {}
    for i, row in enumerate(rows):
        signature_html = _render_signature_html(
            name=row.name,
            designation=row.designation,
            role_name=row.role_name,
            department=row.department,
            phone_number=row.phone_number,
        )
        values_sql_parts.append(f"(:uid{i}, :sig{i})")
        params[f"uid{i}"] = str(row.user_id)
        params[f"sig{i}"] = signature_html

    bind.execute(
        sa.text(
            f"""
            UPDATE users AS u
            SET signature_html = v.signature_html
            FROM (VALUES {", ".join(values_sql_parts)}) AS v(user_id, signature_html)
            WHERE u.user_id = v.user_id::uuid
            """
        ),
        params,
    )


def downgrade() -> None:
    op.drop_column('users', 'signature_html')
