# backfill_designation.py
#
# One-time, non-destructive backfill for the `designation` column added
# by e8566a9089a3_add_designation_to_users.py. The real org import
# (import_org_data.py) already ran once before that column existed, so
# the 99 real employees it created have no designation yet. This
# matches each source_data.py row to its already-imported User by
# email and sets designation only where currently NULL — no wipe, no
# re-seed, safe to run alongside the demo accounts from
# scripts/rbac_seed/seed.py that org_seed's own import never touches.
#
# Usage (from unified-backend/, with the venv active):
#   python -m scripts.org_seed.backfill_designation

import asyncio

from sqlalchemy import select

from app.database.session import AsyncSessionLocal
from app.rbac.models import User
from scripts.org_seed import source_data


async def main() -> None:
    updated = []
    skipped_no_match = []

    async with AsyncSessionLocal() as session:
        for employee_id, name, designation, email, _reporting_manager_raw, _process in source_data.EMPLOYEES:
            email = email.strip().lower()
            designation = designation.strip()

            user = (
                await session.execute(select(User).where(User.email == email))
            ).scalar_one_or_none()

            if user is None:
                skipped_no_match.append((employee_id, name, email))
                continue

            if user.designation is None:
                user.designation = designation
                updated.append((email, designation))

        await session.commit()

    print(f"Backfilled designation for {len(updated)} user(s).")
    if skipped_no_match:
        print(f"No matching user found for {len(skipped_no_match)} source row(s):")
        for employee_id, name, email in skipped_no_match:
            print(f"  employee_id={employee_id} name={name!r} email={email!r}")


if __name__ == "__main__":
    asyncio.run(main())
