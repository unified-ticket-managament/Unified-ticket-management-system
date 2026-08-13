# validate.py
#
# Dry-run report over source_data.py, with zero DB access — run this
# and review the printed report BEFORE running any migration or the
# real import_org_data.py. Usage (from unified-backend/):
#   python -m scripts.org_seed.validate

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.org_seed import mapping  # noqa: E402
from scripts.org_seed.build import build  # noqa: E402


def main() -> None:
    result = build()
    employees = result.employees
    clients = result.clients
    issues = result.issues

    print("=" * 78)
    print("ORG DATA MIGRATION  -  VALIDATION REPORT")
    print("=" * 78)

    # ------------------------------------------------------------
    # Role mapping summary
    # ------------------------------------------------------------
    print("\n--- Role mapping summary ---")
    role_counts: dict[str, int] = {}
    for emp in employees.values():
        role_counts[emp.role] = role_counts.get(emp.role, 0) + 1
    for role in (mapping.SITE_LEAD_ROLE, mapping.ACCOUNT_MANAGER_ROLE, mapping.TEAM_LEAD_ROLE, mapping.STAFF_ROLE):
        print(f"  {role:16} {role_counts.get(role, 0)}")
    print(f"  TOTAL            {len(employees)}")
    print("  (Super Admin / Client: 0 new rows  -  no source data maps to them)")

    # ------------------------------------------------------------
    # Category summary
    # ------------------------------------------------------------
    print("\n--- Category summary ---")
    category_counts: dict[str, int] = {}
    none_count = 0
    for emp in employees.values():
        if emp.category is None:
            none_count += 1
        else:
            category_counts[emp.category] = category_counts.get(emp.category, 0) + 1
    for category in mapping.NEW_CATEGORY_NAMES:
        print(f"  {category:16} {category_counts.get(category, 0)}")
    print(f"  {'(none)':16} {none_count}")

    # ------------------------------------------------------------
    # Reporting hierarchy summary
    # ------------------------------------------------------------
    print("\n--- Reporting hierarchy (Account Managers and Team Leads) ---")
    for emp in sorted(employees.values(), key=lambda e: e.role):
        if emp.role in (mapping.SITE_LEAD_ROLE, mapping.ACCOUNT_MANAGER_ROLE, mapping.TEAM_LEAD_ROLE):
            manager = employees.get(emp.manager_employee_id) if emp.manager_employee_id else None
            print(
                f"  [{emp.role:14}] {emp.name:30} category={str(emp.category):16} "
                f"manager={(manager.name if manager else '(none  -  top of hierarchy)')}"
            )

    staff_with_teamlead = sum(1 for e in employees.values() if e.role == mapping.STAFF_ROLE and e.teamlead_employee_id)
    staff_without_teamlead = sum(1 for e in employees.values() if e.role == mapping.STAFF_ROLE and not e.teamlead_employee_id)
    print(f"\n  Staff with teamlead_id set:     {staff_with_teamlead}")
    print(f"  Staff without teamlead_id set:  {staff_without_teamlead} (report directly to an Account Manager/Site Lead, or category mismatch  -  see warnings below)")

    # ------------------------------------------------------------
    # Client ownership summary
    # ------------------------------------------------------------
    print("\n--- Client ownership summary ---")
    for client in clients.values():
        am = employees[client.account_manager_employee_id]
        print(f"\n  {client.name}")
        print(f"    account_manager_id -> {am.name}")
        for assignment in client.lead_assignments:
            lead_emp = employees[assignment.employee_id]
            fallback_note = " (fallback: no lead listed, using Account Manager)" if assignment.via_fallback else ""
            print(f"    {assignment.lead_role:14} -> {lead_emp.name}{fallback_note}")
        print(f"    inbox_email -> {client.inbox_email if client.inbox_email is not None else '(none — NULL)'}")
        print(f"    contact_emails ({len(client.contact_emails)}): {', '.join(client.contact_emails)}")

    # ------------------------------------------------------------
    # Foreign-key / completeness checks
    # ------------------------------------------------------------
    print("\n--- Foreign-key / completeness checks ---")
    print(f"  Every client has an account_manager_id: {all(c.account_manager_employee_id in employees for c in clients.values())}")
    print(f"  Every client has all 3 lead assignments: {all(len(c.lead_assignments) == 3 for c in clients.values())}")
    print(f"  Every employee has a role: {all(e.role for e in employees.values())}")

    # ------------------------------------------------------------
    # Issues
    # ------------------------------------------------------------
    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]
    orphan_contacts = [i for i in issues if i.category == "orphan_client_contacts"]
    print(f"  Clients referenced in Client_emails.pdf with no client-hierarchy row: {len(orphan_contacts)}")

    print(f"\n--- Issues found: {len(errors)} error(s), {len(warnings)} warning(s) ---")

    if errors:
        print("\n  ERRORS (must be resolved before import):")
        for issue in errors:
            print(f"    [{issue.category}] {issue.message}")

    if warnings:
        print("\n  WARNINGS (imported as-is, flagged for your awareness):")
        for issue in warnings:
            print(f"    [{issue.category}] {issue.message}")

    print("\n" + "=" * 78)
    if errors:
        print(f"RESULT: {len(errors)} error(s) found  -  DO NOT run import_org_data.py until these are resolved.")
    else:
        print("RESULT: no blocking errors. Review the warnings above, then it's safe to run import_org_data.py.")
    print("=" * 78)


if __name__ == "__main__":
    main()
