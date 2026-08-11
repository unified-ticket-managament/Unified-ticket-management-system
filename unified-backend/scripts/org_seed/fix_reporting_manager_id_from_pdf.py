# fix_reporting_manager_id_from_pdf.py
#
# One-time, non-destructive correction for the `reporting_manager_id`
# column added by b2d4f6a8c0e2_add_reporting_manager_id_to_users.py.
# That migration's own backfill (COALESCE(teamlead_id, manager_id))
# produced an incorrect value for a subset of users — most notably 17
# of Yashodha S's 23 real direct reports, whose manager_id/teamlead_id
# happened to point elsewhere (a pre-existing data quirk unrelated to
# this column) — so this script re-derives the correct value directly
# from source_data.py's own `EMPLOYEES`/`REPORTING_MANAGER_ALIASES`
# (the authoritative, hand-transcribed organization PDF), independent
# of whatever manager_id/teamlead_id currently say. Those two columns
# are never read or written here — see root CLAUDE.md's Organization
# Chart sections for why they're a separate, untouched concern.
#
# Matching priority, same "don't guess" discipline as
# backfill_employee_number.py: exact email (case-insensitive) first,
# then employee_number, then normalized full name — and only when
# exactly one candidate matches. A row that can't be confidently
# matched (employee OR their resolved manager) is reported and left
# untouched, never guessed at. The two REPORTING_MANAGER_ALIASES
# entries already declared in source_data.py (name-order/truncation
# mismatches between the "Reporting Manager" column's free text and
# that manager's own Name column) are applied as-is — they're already
# a reviewed, committed part of this codebase, not invented here.
#
# Usage (from unified-backend/, with the venv active):
#   python -m scripts.org_seed.fix_reporting_manager_id_from_pdf              # dry run, prints report only
#   python -m scripts.org_seed.fix_reporting_manager_id_from_pdf --apply      # applies + commits, transactional

import argparse
import asyncio
import re

from sqlalchemy import func, select

from app.database.session import AsyncSessionLocal
from app.rbac.models import User
from scripts.org_seed import source_data


def normalize(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


async def _find_user(session, email: str, employee_id: int, name: str) -> User | None:
    candidates = (
        (await session.execute(select(User).where(func.lower(User.email) == email.strip().lower())))
        .scalars()
        .all()
    )
    if len(candidates) == 1:
        return candidates[0]
    if candidates:
        return None  # ambiguous — never guess

    candidates = (
        (await session.execute(select(User).where(User.employee_number == str(employee_id))))
        .scalars()
        .all()
    )
    if len(candidates) == 1:
        return candidates[0]
    if candidates:
        return None

    candidates = (
        (await session.execute(select(User).where(func.lower(User.name) == normalize(name))))
        .scalars()
        .all()
    )
    if len(candidates) == 1:
        return candidates[0]
    return None


async def main(apply: bool) -> None:
    employees_by_norm_name = {normalize(e[1]): e for e in source_data.EMPLOYEES}

    already_correct = []
    updated = []
    unmatched_employee = []
    unmatched_manager = []
    root_external = []
    self_reference_rejected = []

    async with AsyncSessionLocal() as session:
        for employee_id, name, _designation, email, manager_raw, _process in source_data.EMPLOYEES:
            user = await _find_user(session, email, employee_id, name)
            if user is None:
                unmatched_employee.append((employee_id, name, email))
                continue

            resolved_manager_name = source_data.REPORTING_MANAGER_ALIASES.get(manager_raw, manager_raw)

            if resolved_manager_name is None:
                # ProbeRCM (or any other declared non-person sentinel) —
                # top of the company, no real reporting manager.
                root_external.append((name, email))
                if user.reporting_manager_id is not None:
                    if apply:
                        user.reporting_manager_id = None
                    updated.append((name, email, "<root>", str(user.reporting_manager_id), "NULL"))
                continue

            manager_row = employees_by_norm_name.get(normalize(resolved_manager_name))
            if manager_row is None:
                unmatched_manager.append((name, email, manager_raw))
                continue

            mgr_employee_id, mgr_name, _mgr_designation, mgr_email, _mgr_manager_raw, _mgr_process = manager_row
            manager_user = await _find_user(session, mgr_email, mgr_employee_id, mgr_name)
            if manager_user is None:
                unmatched_manager.append((name, email, manager_raw))
                continue

            if manager_user.user_id == user.user_id:
                self_reference_rejected.append((name, email))
                continue

            if user.reporting_manager_id == manager_user.user_id:
                already_correct.append((name, email, mgr_name))
                continue

            old_value = str(user.reporting_manager_id) if user.reporting_manager_id else "NULL"
            if apply:
                user.reporting_manager_id = manager_user.user_id
            updated.append((name, email, mgr_name, old_value, str(manager_user.user_id)))

        if apply:
            await session.commit()

    total = len(source_data.EMPLOYEES)
    print(f"Total source rows: {total}")
    print(f"Already correct:   {len(already_correct)}")
    print(f"{'Updated' if apply else 'Would update'}:{'':11}{len(updated)}")
    print(f"Root/external manager (no update needed unless stale): {len(root_external)}")
    print(f"Unmatched employee: {len(unmatched_employee)}")
    print(f"Unmatched manager:  {len(unmatched_manager)}")
    print(f"Self-reference rejected: {len(self_reference_rejected)}")

    if updated:
        print(f"\n{'UPDATED' if apply else 'WOULD UPDATE'}:")
        for name, email, mgr_name, old, new in updated:
            print(f"  {name:30} {email:32} -> reporting_manager={mgr_name:30} ({old} -> {new})")

    if unmatched_employee:
        print(f"\nUNMATCHED EMPLOYEE — not modified:")
        for employee_id, name, email in unmatched_employee:
            print(f"  employee_id={employee_id} {name!r} {email!r}")

    if unmatched_manager:
        print(f"\nUNMATCHED MANAGER — employee not modified:")
        for name, email, manager_raw in unmatched_manager:
            print(f"  {name} ({email}) -> manager {manager_raw!r} not resolvable")

    if self_reference_rejected:
        print(f"\nSELF-REFERENCE REJECTED — not modified:")
        for name, email in self_reference_rejected:
            print(f"  {name} ({email})")

    if not apply:
        print("\nDRY RUN ONLY — no database changes made. Re-run with --apply to commit.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(apply=args.apply))
