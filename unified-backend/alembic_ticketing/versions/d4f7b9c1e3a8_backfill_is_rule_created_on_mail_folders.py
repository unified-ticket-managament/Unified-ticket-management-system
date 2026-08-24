"""backfill is_rule_created on mail_folders

Revision ID: d4f7b9c1e3a8
Revises: c3e6a8b0d2f5
Create Date: 2026-08-24 00:00:00.000001

`is_rule_created` (c3e6a8b0d2f5) defaulted every pre-existing folder to
False, deliberately not backfilled at the time to avoid a name-based
guess. Since then, confirmed by grep that `MailFolderService.create`
(the manual POST /folders path) has zero frontend callers anywhere in
this codebase — every folder that has ever existed in this app was
actually created via rule_folder_sync.ensure_folder, i.e. by a Mail/
OTP Rule's own create_folder/move_to_folder action. Given that fact,
backfilling every existing row to True is not a guess, it's a
correction of an overly-conservative default — this is what let a
just-deleted rule's own folder (e.g. "RULE") linger forever instead of
being cleaned up by RuleService.delete, since that cleanup only ever
considers is_rule_created=True folders eligible. Purely additive/
corrective; does not touch shared_user_ids, shared_distribution_list_ids,
or any interaction data.
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd4f7b9c1e3a8'
down_revision: Union[str, None] = 'c3e6a8b0d2f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE mail_folders SET is_rule_created = true WHERE is_rule_created = false")


def downgrade() -> None:
    # Not reversible to the exact prior per-row state (that information
    # — which rows were True vs. False before this backfill — is gone
    # by design once this runs) — downgrading restores the column's
    # conservative default for every row, matching what a fresh
    # c3e6a8b0d2f5-only database would have looked like.
    op.execute("UPDATE mail_folders SET is_rule_created = false")
