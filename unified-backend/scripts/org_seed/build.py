# build.py
#
# Turns source_data.py's raw rows into a fully-resolved in-memory model
# (role, category, manager_id/teamlead_id target, client ownership,
# client contacts) plus a list of ValidationIssue objects describing
# every inconsistency found along the way. Pure Python, no DB access —
# shared by validate.py (prints the report) and import_org_data.py (does
# the actual write), so a dry run and the real run can never resolve a
# row differently from each other.

from dataclasses import dataclass, field

from scripts.org_seed import mapping, source_data


@dataclass
class ValidationIssue:
    severity: str  # "error" (blocks import) | "warning" (imported as-is, flagged)
    category: str
    message: str


@dataclass
class Employee:
    employee_id: int
    name: str
    designation: str
    email: str
    process: str
    reporting_manager_raw: str
    role: str = ""
    category: str | None = None
    manager_employee_id: int | None = None  # resolved manager_id target
    teamlead_employee_id: int | None = None  # resolved teamlead_id target


@dataclass
class ClientLeadAssignment:
    client_name: str
    lead_role: str  # AR_LEAD | CODING_LEAD | POSTING_LEAD
    employee_id: int
    via_fallback: bool


@dataclass
class Client:
    name: str
    account_manager_employee_id: int
    lead_assignments: list[ClientLeadAssignment] = field(default_factory=list)
    contact_emails: list[str] = field(default_factory=list)
    # clients.inbox_email — the client's curated distribution address
    # (mapping.resolve_distribution_email), or None if it has none.
    # Deliberately never derived from contact_emails.
    inbox_email: str | None = None


@dataclass
class BuildResult:
    employees: dict[int, Employee]
    clients: dict[str, Client]
    issues: list[ValidationIssue]


def _resolve_employee_by_alias_or_name(
    raw_text: str,
    alias_map: dict[str, str | None],
    employees_by_name: dict[str, Employee],
) -> Employee | None:
    """None means "resolves to a non-person" (e.g. ProbeRCM) OR "not found"."""
    canonical_name = alias_map.get(raw_text, raw_text)
    if canonical_name is None:
        return None
    return employees_by_name.get(canonical_name)


def build() -> BuildResult:
    issues: list[ValidationIssue] = []

    # ------------------------------------------------------------
    # Employees: parse + duplicate checks
    # ------------------------------------------------------------

    employees: dict[int, Employee] = {}
    employees_by_name: dict[str, Employee] = {}
    seen_emails: dict[str, int] = {}

    for employee_id, name, designation, email, reporting_manager_raw, process in source_data.EMPLOYEES:
        name = name.strip()
        email = email.strip().lower()
        designation = designation.strip()
        process = process.strip()

        if employee_id in employees:
            issues.append(ValidationIssue(
                "error", "duplicate_employee_id",
                f"Employee ID {employee_id} appears more than once ({name!r}).",
            ))
            continue

        if email in seen_emails:
            issues.append(ValidationIssue(
                "error", "duplicate_email",
                f"Email {email!r} used by both employee {seen_emails[email]} and {employee_id} ({name!r}).",
            ))
        seen_emails[email] = employee_id

        if name in employees_by_name:
            issues.append(ValidationIssue(
                "error", "duplicate_employee_name",
                f"Name {name!r} used by more than one employee ({employees_by_name[name].employee_id} and {employee_id}) "
                " -  reporting-manager text matching by name will be ambiguous.",
            ))

        record = Employee(
            employee_id=employee_id,
            name=name,
            designation=designation,
            email=email,
            process=process,
            reporting_manager_raw=reporting_manager_raw.strip(),
        )
        employees[employee_id] = record
        employees_by_name[name] = record

    # ------------------------------------------------------------
    # Role / category resolution
    # ------------------------------------------------------------

    for emp in employees.values():
        emp.role = mapping.resolve_role(emp.designation, emp.process)
        emp.category = mapping.resolve_category(emp.designation, emp.process)

    # ------------------------------------------------------------
    # Resolve each employee's raw reporting-manager text to an actual
    # Employee record (or None for a non-person sentinel / unresolved).
    # ------------------------------------------------------------

    resolved_manager: dict[int, Employee | None] = {}

    for emp in employees.values():
        target = _resolve_employee_by_alias_or_name(
            emp.reporting_manager_raw, source_data.REPORTING_MANAGER_ALIASES, employees_by_name,
        )
        resolved_manager[emp.employee_id] = target

        is_sentinel = source_data.REPORTING_MANAGER_ALIASES.get(emp.reporting_manager_raw, "") is None
        if target is None and not is_sentinel and emp.role != mapping.SITE_LEAD_ROLE:
            issues.append(ValidationIssue(
                "error", "missing_reporting_manager",
                f"Employee {emp.employee_id} ({emp.name!r}) has Reporting Manager "
                f"{emp.reporting_manager_raw!r}, which does not resolve to any known employee.",
            ))

    # ------------------------------------------------------------
    # Circular reporting-line check, over the raw resolved edges
    # (before manager_id/teamlead_id collapsing below).
    # ------------------------------------------------------------

    for emp in employees.values():
        seen: set[int] = set()
        current: Employee | None = emp
        while current is not None:
            if current.employee_id in seen:
                issues.append(ValidationIssue(
                    "error", "circular_reporting",
                    f"Circular reporting line detected starting at employee {emp.employee_id} ({emp.name!r}).",
                ))
                break
            seen.add(current.employee_id)
            current = resolved_manager.get(current.employee_id)

    # ------------------------------------------------------------
    # Build manager_id / teamlead_id per the role-branching rule
    # (see the plan's "Reporting Hierarchy Build Order" section).
    # Processed top-down: Site Lead -> Account Manager -> Team Lead ->
    # Staff, so a Staff row can look up its Team Lead's *already
    # resolved* manager_employee_id.
    # ------------------------------------------------------------

    def role_rank(role: str) -> int:
        return {
            mapping.SITE_LEAD_ROLE: 0,
            mapping.ACCOUNT_MANAGER_ROLE: 1,
            mapping.TEAM_LEAD_ROLE: 2,
            mapping.STAFF_ROLE: 3,
        }[role]

    for emp in sorted(employees.values(), key=lambda e: role_rank(e.role)):
        manager_record = resolved_manager.get(emp.employee_id)

        if emp.role == mapping.SITE_LEAD_ROLE:
            emp.manager_employee_id = None
            emp.teamlead_employee_id = None
            continue

        if manager_record is None:
            # Either an unresolved sentinel/typo (already flagged above)
            # or a genuine data gap — leave unset rather than guess.
            emp.manager_employee_id = None
            emp.teamlead_employee_id = None
            continue

        if emp.role == mapping.ACCOUNT_MANAGER_ROLE:
            emp.manager_employee_id = manager_record.employee_id
            emp.teamlead_employee_id = None
            if manager_record.role != mapping.SITE_LEAD_ROLE:
                issues.append(ValidationIssue(
                    "warning", "manager_role_mismatch",
                    f"Account Manager {emp.employee_id} ({emp.name!r}) reports to "
                    f"{manager_record.name!r}, whose role is {manager_record.role!r}, not Site Lead.",
                ))
            continue

        if emp.role == mapping.TEAM_LEAD_ROLE:
            emp.manager_employee_id = manager_record.employee_id
            emp.teamlead_employee_id = None
            if manager_record.role != mapping.ACCOUNT_MANAGER_ROLE:
                issues.append(ValidationIssue(
                    "warning", "team_lead_bypasses_account_manager",
                    f"Team Lead {emp.employee_id} ({emp.name!r}) reports directly to "
                    f"{manager_record.name!r} (role {manager_record.role!r}), skipping the Account "
                    "Manager layer. Imported as-is (the app's manager_id role validation is bypassed "
                    "by this direct-write seed script, same as the existing seed.py)  -  flagged as a "
                    "known limitation per the plan.",
                ))
            continue

        # Staff
        if manager_record.role == mapping.TEAM_LEAD_ROLE:
            if manager_record.category is not None and emp.category == manager_record.category:
                emp.teamlead_employee_id = manager_record.employee_id
            else:
                emp.teamlead_employee_id = None
                issues.append(ValidationIssue(
                    "warning", "teamlead_category_mismatch",
                    f"Staff {emp.employee_id} ({emp.name!r}, category {emp.category!r}) reports to "
                    f"Team Lead {manager_record.name!r} (category {manager_record.category!r})  -  "
                    "categories don't match, so teamlead_id is left unset (manager_id is still set) "
                    "per the app's teamlead/category validation rule.",
                ))
            emp.manager_employee_id = manager_record.manager_employee_id
        elif manager_record.role in (mapping.ACCOUNT_MANAGER_ROLE, mapping.SITE_LEAD_ROLE):
            emp.teamlead_employee_id = None
            emp.manager_employee_id = manager_record.employee_id
            if manager_record.role == mapping.SITE_LEAD_ROLE:
                issues.append(ValidationIssue(
                    "warning", "staff_bypasses_account_manager",
                    f"Staff {emp.employee_id} ({emp.name!r}) reports directly to "
                    f"{manager_record.name!r} (Site Lead), skipping the Account Manager layer. "
                    "Imported as-is  -  same known limitation as team_lead_bypasses_account_manager.",
                ))
        else:
            emp.teamlead_employee_id = None
            emp.manager_employee_id = manager_record.employee_id
            issues.append(ValidationIssue(
                "warning", "unexpected_manager_role",
                f"Employee {emp.employee_id} ({emp.name!r}) reports to {manager_record.name!r}, "
                f"whose role is {manager_record.role!r}  -  not Site Lead/Account Manager/Team Lead.",
            ))

    # ------------------------------------------------------------
    # Clients: resolve manager + AR/Coding/Posting lead aliases,
    # apply the fallback rule, dedupe/validate contact emails.
    # ------------------------------------------------------------

    clients: dict[str, Client] = {}

    def resolve_person(alias: str | None) -> Employee | None:
        if alias is None:
            return None
        canonical_name = source_data.CLIENT_PERSON_ALIASES.get(alias, alias)
        return employees_by_name.get(canonical_name)

    for client_name, manager_alias, ar_lead_alias, coding_lead_alias, posting_lead_alias in source_data.CLIENTS:
        manager_emp = resolve_person(manager_alias)
        if manager_emp is None:
            issues.append(ValidationIssue(
                "error", "missing_client_manager",
                f"Client {client_name!r} has Manager alias {manager_alias!r}, which does not "
                "resolve to any known employee.",
            ))
            continue

        client = Client(
            name=client_name,
            account_manager_employee_id=manager_emp.employee_id,
            inbox_email=mapping.resolve_distribution_email(client_name),
        )
        if client.inbox_email is None:
            issues.append(ValidationIssue(
                "warning", "client_with_no_distribution_email",
                f"Client {client_name!r} has no configured distribution email — "
                "its inbox_email will be NULL.",
            ))

        for lead_role, alias in (
            ("AR_LEAD", ar_lead_alias),
            ("CODING_LEAD", coding_lead_alias),
            ("POSTING_LEAD", posting_lead_alias),
        ):
            lead_emp = resolve_person(alias)
            if lead_emp is not None:
                client.lead_assignments.append(
                    ClientLeadAssignment(client_name, lead_role, lead_emp.employee_id, via_fallback=False)
                )
            else:
                if alias is not None:
                    issues.append(ValidationIssue(
                        "error", "missing_client_lead",
                        f"Client {client_name!r} has {lead_role} alias {alias!r}, which does not "
                        "resolve to any known employee. Falling back to the Account Manager.",
                    ))
                # Fallback rule: missing lead -> the client's own Account Manager.
                client.lead_assignments.append(
                    ClientLeadAssignment(client_name, lead_role, manager_emp.employee_id, via_fallback=True)
                )

        clients[client_name] = client

    # ------------------------------------------------------------
    # Client contacts: dedupe within a client, flag cross-client dupes,
    # and defensively exclude the client's own distribution email (see
    # client.inbox_email, already resolved above) should it ever
    # appear in the source contact list — it never does for today's
    # 16 clients, but a contact must never be stored again as the
    # distribution address.
    # ------------------------------------------------------------

    email_to_clients: dict[str, list[str]] = {}

    for client_name, raw_emails in source_data.CLIENT_CONTACTS.items():
        client = clients.get(client_name)
        if client is None:
            issues.append(ValidationIssue(
                "error", "orphan_client_contacts",
                f"Client_emails.pdf lists contacts for {client_name!r}, which is not one of the "
                "16 clients in the client-hierarchy sheet.",
            ))
            continue

        seen_in_client: set[str] = set()
        deduped: list[str] = []
        for raw_email in raw_emails:
            normalized = raw_email.strip().lower()
            if client.inbox_email is not None and normalized == client.inbox_email:
                issues.append(ValidationIssue(
                    "warning", "contact_matches_distribution_email",
                    f"Contact {raw_email!r} for client {client_name!r} is the same as its "
                    "distribution email — stored only as inbox_email, not duplicated as a contact.",
                ))
                continue
            if normalized in seen_in_client:
                issues.append(ValidationIssue(
                    "warning", "duplicate_client_contact",
                    f"Contact {raw_email!r} is listed more than once for client {client_name!r}.",
                ))
                continue
            seen_in_client.add(normalized)
            deduped.append(normalized)
            email_to_clients.setdefault(normalized, []).append(client_name)

        client.contact_emails = deduped

    all_client_names = {c[0] for c in source_data.CLIENTS}
    for missing_client in all_client_names - set(source_data.CLIENT_CONTACTS.keys()):
        issues.append(ValidationIssue(
            "warning", "client_with_no_contacts",
            f"Client {missing_client!r} has no rows in Client_emails.pdf.",
        ))

    for email, client_names in email_to_clients.items():
        if len(set(client_names)) > 1:
            issues.append(ValidationIssue(
                "warning", "cross_client_duplicate_contact",
                f"Contact email {email!r} appears under more than one client: {sorted(set(client_names))}.",
            ))

    # NULL is exempt from this check by design — Postgres's own unique
    # index already allows any number of NULL inbox_email rows, and
    # several of these clients are expected to have none configured.
    inbox_email_to_clients: dict[str, list[str]] = {}
    for client in clients.values():
        if client.inbox_email is None:
            continue
        inbox_email_to_clients.setdefault(client.inbox_email, []).append(client.name)
    for inbox_email, client_names in inbox_email_to_clients.items():
        if len(client_names) > 1:
            issues.append(ValidationIssue(
                "error", "duplicate_inbox_email",
                f"Distribution email {inbox_email!r} is configured for more than one client "
                f"({client_names})  -  clients.inbox_email must be unique.",
            ))

    return BuildResult(employees=employees, clients=clients, issues=issues)
