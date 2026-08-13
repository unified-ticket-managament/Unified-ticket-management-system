"""fix client inbox_email to be the real distribution address

Revision ID: a4c6e8f0b2d4
Revises: e7c9b1d3f5a7
Create Date: 2026-08-13 00:00:00.000000

`clients.inbox_email` was being populated by auto-selecting one of a
client's configured contact emails (scripts/org_seed/mapping.py's old
`pick_primary_contact` — "the first contact not on an internal
probeps.com/painmedpa.com domain", with two hardcoded overrides) —
never the client's actual official distribution/intake address. That
root cause is fixed in the same commit as this migration
(mapping.py's new `resolve_distribution_email`, reading a curated,
explicit `source_data.DISTRIBUTION_EMAILS` map) — this migration is
the one-time correction of data already written under the old, wrong
rule, plus the schema change that makes a client with no configured
distribution email representable at all (previously `inbox_email` was
NOT NULL, forcing every client to have *something* in it).

For each of the 16 real client-hierarchy names (plus "Alleviate",
covered by the same distribution-email mapping even though it isn't
one of the 16 today):
  - If the client's current inbox_email doesn't match its correct
    distribution email (or it has none), the *old* value — a real
    employee/contact address, wrongly promoted — is preserved by
    moving it into client_contacts (skipped if already stored there,
    so a re-run or a partially-correct row never creates a dupe).
  - inbox_email is then set to the correct distribution address, or
    NULL for the three clients (East West Pain Institute, CPC, Sekel
    Health) with no configured distribution email at all.

Any other client row (e.g. scripts/ticketing_seed/seed_clients.py's
unrelated demo clients — ABC Clinic, XYZ Medical Group, etc., whose
inbox_email was always hand-set directly, never derived from a
contact list) is completely untouched: this migration only ever
touches rows whose name matches the list below. No client_id changes,
no rows are deleted, and no valid employee email is discarded — a
demoted inbox_email always survives as a client_contacts row unless
it was already there.
"""

from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy import table, column


# revision identifiers, used by Alembic.
revision: str = 'a4c6e8f0b2d4'
down_revision: Union[str, None] = 'e7c9b1d3f5a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Mirrors scripts/org_seed/source_data.py's DISTRIBUTION_EMAILS exactly
# (duplicated, not imported — a migration must stay a frozen snapshot
# of what it did, independent of that module's content changing
# later). Keep the two in sync if this mapping is ever revised again;
# a future correction should be its own new migration, not an edit to
# this one.
DISTRIBUTION_EMAILS: dict[str, str] = {
    "PCRR": "pcrrpractices@probeps.com",
    "CTFS": "ctfs@probeps.com",
    "ATX 360 PM": "atx360@probeps.com",
    "APM": "apm@probeps.com",
    "Taral Sharma MD PA": "dr.sharma@probeps.com",
    "Compassionate Womens health": "cwh@probeps.com",
    "Cameron pediatrics": "cameron@probeps.com",
    "FFJ": "familyfirst@probeps.com",
    "Nexus Pain care LLC": "nexuspain@painmedpa.com",
    "LEFC": "lefc@probeps.com",
    "HEEL & SOLE FOOT & ANKLE, PLLC": "heelsolefa@probeps.com",
    "MMC": "metroplex@probeps.com",
    "Performance Ortho": "performanceortho@painmedpa.com",
    "Alleviate": "alleviatepain@painmedpa.com",
}

# Every client name this migration is allowed to touch — the 16 real
# client-hierarchy names (source_data.CLIENTS) plus "Alleviate". Three
# of the 16 (East West Pain Institute, CPC, Sekel Health) deliberately
# have no DISTRIBUTION_EMAILS entry -> inbox_email becomes NULL for
# them. Any client name not in this list (demo/manually-onboarded
# clients) is left completely alone.
KNOWN_CLIENT_NAMES = [
    "APM", "East West Pain Institute", "FFJ", "CPC", "MMC", "PCRR",
    "HEEL & SOLE FOOT & ANKLE, PLLC", "Sekel Health", "CTFS", "ATX 360 PM",
    "Taral Sharma MD PA", "Nexus Pain care LLC", "Compassionate Womens health",
    "Cameron pediatrics", "LEFC", "Performance Ortho", "Alleviate",
]


def upgrade() -> None:
    op.alter_column("clients", "inbox_email", existing_type=sa.String(255), nullable=True)

    bind = op.get_bind()

    clients_t = table(
        "clients",
        column("client_id", sa.UUID()),
        column("name", sa.String()),
        column("inbox_email", sa.String()),
    )
    contacts_t = table(
        "client_contacts",
        column("contact_id", sa.UUID()),
        column("client_id", sa.UUID()),
        column("email", sa.String()),
        column("is_primary", sa.Boolean()),
        column("created_at", sa.DateTime(timezone=True)),
        column("updated_at", sa.DateTime(timezone=True)),
    )

    for name in KNOWN_CLIENT_NAMES:
        correct_email = DISTRIBUTION_EMAILS.get(name)  # None -> NULL

        rows = bind.execute(
            sa.select(clients_t.c.client_id, clients_t.c.inbox_email).where(
                sa.func.lower(clients_t.c.name) == name.lower()
            )
        ).fetchall()

        for client_id, current_inbox_email in rows:
            if current_inbox_email and current_inbox_email.strip().lower() != (correct_email or ""):
                old_email = current_inbox_email.strip().lower()

                already_a_contact = bind.execute(
                    sa.select(contacts_t.c.contact_id).where(
                        contacts_t.c.client_id == client_id,
                        sa.func.lower(contacts_t.c.email) == old_email,
                    )
                ).first()

                if already_a_contact is None:
                    bind.execute(
                        contacts_t.insert().values(
                            contact_id=uuid.uuid4(),
                            client_id=client_id,
                            email=old_email,
                            is_primary=False,
                            created_at=sa.func.now(),
                            updated_at=sa.func.now(),
                        )
                    )

            bind.execute(
                clients_t.update()
                .where(clients_t.c.client_id == client_id)
                .values(inbox_email=correct_email)
            )


def downgrade() -> None:
    # No meaningful downgrade: the pre-migration inbox_email values
    # were themselves wrong (auto-picked contact emails, not the real
    # distribution address), and this migration doesn't retain them
    # anywhere it could restore from — same "nothing sensible to
    # revert to" precedent as
    # c4d6e8f0a2b4_renumber_tickets_contiguous.py. Re-tightening the
    # NOT NULL constraint would also immediately fail against the
    # clients this migration intentionally set to NULL.
    pass
