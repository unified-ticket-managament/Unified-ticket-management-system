# mapping.py
#
# Pure business-rule functions translating the raw source_data.py rows
# into application concepts (role name, category name). No DB access,
# no SQLAlchemy — kept importable by both validate.py (dry-run report)
# and import_org_data.py (the real write), so the two can never drift
# out of sync on what a given row resolves to.

SITE_LEAD_ROLE = "Site Lead"
ACCOUNT_MANAGER_ROLE = "Account Manager"
TEAM_LEAD_ROLE = "Team Lead"
STAFF_ROLE = "Staff"

# The 8 new category values, replacing the old 7 (Eligibility, Patient
# Calling, AR, Payment Posting, PA, Charge Entry, Claims) per the
# approved schema change.
NEW_CATEGORY_NAMES = [
    "AR",
    "Referral",
    "Authorization",
    "IV",
    "Credentialing",
    "Coding",
    "Payment Posting",
    "Quality",
]

# Process value (lowercased, trimmed) -> category name. Values with no
# operational category (Director/Manager/Trainer/"0") map to None.
_PROCESS_TO_CATEGORY = {
    "ar": "AR",
    "referral": "Referral",
    "authorization": "Authorization",
    "iv": "IV",
    "credentialing": "Credentialing",
    "coding": "Coding",
    "payment posting": "Payment Posting",
    "quality": "Quality",
    "director": None,
    "manager": None,
    "trainer": None,
    "0": None,
}

# "Lead - X" Process value (lowercased, trimmed) -> category name for
# the Team Lead's own category_id. "Lead - Quality and Payment Posting"
# has no single matching category; Payment Posting is picked as the
# primary per the approved plan (Yashodha S's cross-category direct
# reports are handled individually in validate.py, not by this map).
_LEAD_PROCESS_TO_CATEGORY = {
    "lead - ar": "AR",
    "lead - coding": "Coding",
    "lead - payment posting": "Payment Posting",
    "lead - referral": "Referral",
    "lead - quality and payment posting": "Payment Posting",
}


def is_lead_process(process: str) -> bool:
    return process.strip().lower() in _LEAD_PROCESS_TO_CATEGORY


def resolve_role(designation: str, process: str) -> str:
    """
    Locked business rule: Team Lead is decided ONLY by Process, never
    by Designation. Designation is consulted only for Site
    Lead/Account Manager.
    """
    designation_lower = designation.strip().lower()

    if designation_lower == "director of operations":
        return SITE_LEAD_ROLE

    if "manager" in designation_lower:
        return ACCOUNT_MANAGER_ROLE

    if is_lead_process(process):
        return TEAM_LEAD_ROLE

    return STAFF_ROLE


def resolve_category(designation: str, process: str) -> str | None:
    role = resolve_role(designation, process)
    process_key = process.strip().lower()

    if role == TEAM_LEAD_ROLE:
        return _LEAD_PROCESS_TO_CATEGORY.get(process_key)

    return _PROCESS_TO_CATEGORY.get(process_key)


# --------------------------------------------------------------------
# Client contact -> clients.inbox_email
# --------------------------------------------------------------------
# Default rule: the first contact email for a client that isn't on an
# internal probeps.com/painmedpa.com domain. These two clients need an
# explicit override because that default picks something unsuitable
# (see the plan's "Client Contacts" section for why).
PRIMARY_CONTACT_OVERRIDE = {
    "FFJ": "lisa@familyfirstjville.com",
    "PCRR": "bhargavibkola@gmail.com",
}

_INTERNAL_DOMAINS = {"probeps.com", "painmedpa.com"}


def pick_primary_contact(client_name: str, emails: list[str]) -> str:
    if client_name in PRIMARY_CONTACT_OVERRIDE:
        return PRIMARY_CONTACT_OVERRIDE[client_name]

    for email in emails:
        domain = email.strip().lower().rsplit("@", 1)[-1]
        if domain not in _INTERNAL_DOMAINS:
            return email

    return emails[0]
