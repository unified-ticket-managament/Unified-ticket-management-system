# backfill_employee_number.py
#
# One-time, non-destructive backfill for the `employee_number` column
# added by a1c3e5f7b9d1_add_employee_number_to_users.py. Matches each
# source_data.py row to its already-imported User by email (case-
# insensitive) and sets employee_number only where currently NULL — no
# wipe, no re-seed, no UUID/relationship touched, same convention as
# backfill_designation.py.
#
# Matching is deliberately email-only, never name-based: per the task's
# own "do not blindly match by fuzzy name if a safer identifier exists,
# and do not invent an ID" rule, a source row whose email doesn't match
# any existing user is reported as UNMATCHED rather than guessed at —
# even when a name/designation/category/manager combination looks like
# an obvious match (see the known Gogineni@painmedpa.com / official
# pavan@probeps.com case in the printed report below), since correcting
# that mismatch is a separate, not-yet-confirmed decision, not something
# this script should do silently as a side effect of adding an ID.
#
# Usage (from unified-backend/, with the venv active):
#   python -m scripts.org_seed.backfill_employee_number

import asyncio

from sqlalchemy import func, select

from app.database.session import AsyncSessionLocal
from app.rbac.models import User
from scripts.org_seed import source_data


async def main() -> None:
    updated: list[tuple[int, str, str, str]] = []  # employee_id, name, email, employee_number
    already_set: list[tuple[int, str, str, str]] = []  # existing value differs or matches
    skipped_no_match: list[tuple[int, str, str]] = []
    duplicate_employee_ids: list[int] = []

    seen_employee_ids: set[int] = set()

    async with AsyncSessionLocal() as session:
        for employee_id, name, _designation, email, _reporting_manager_raw, _process in source_data.EMPLOYEES:
            if employee_id in seen_employee_ids:
                duplicate_employee_ids.append(employee_id)
                continue
            seen_employee_ids.add(employee_id)

            email = email.strip()

            user = (
                await session.execute(
                    select(User).where(func.lower(User.email) == email.lower())
                )
            ).scalar_one_or_none()

            if user is None:
                skipped_no_match.append((employee_id, name, email))
                continue

            employee_number = str(employee_id)

            if user.employee_number is None:
                user.employee_number = employee_number
                updated.append((employee_id, name, email, employee_number))
            else:
                already_set.append((employee_id, name, email, user.employee_number))

        await session.commit()

    print(f"Backfilled employee_number for {len(updated)} user(s):")
    for employee_id, name, email, employee_number in updated:
        print(f"  {employee_number:>4} | {name:30} | {email}")

    if already_set:
        print(f"\nAlready had a value, left unchanged ({len(already_set)}):")
        for employee_id, name, email, existing in already_set:
            flag = "" if existing == str(employee_id) else "  [DIFFERS FROM SOURCE — review]"
            print(f"  official={employee_id:>4} existing={existing!r} | {name:30} | {email}{flag}")

    if skipped_no_match:
        print(f"\nUNMATCHED / REQUIRES REVIEW — no user found for {len(skipped_no_match)} official employee(s):")
        for employee_id, name, email in skipped_no_match:
            print(f"  employee_id={employee_id} name={name!r} official_email={email!r}")

    if duplicate_employee_ids:
        print(f"\nDuplicate employee_id values within source_data.py itself: {duplicate_employee_ids}")

    print(f"\nTotal source rows: {len(source_data.EMPLOYEES)}")
    print(f"Matched (updated + already-set): {len(updated) + len(already_set)}")
    print(f"Unmatched: {len(skipped_no_match)}")


if __name__ == "__main__":
    asyncio.run(main())
