"""
Defines which database tables are owned by the
Ticket Management service.

Alembic will generate migrations ONLY for these tables.
Shared tables such as users and roles are intentionally
excluded because they are owned by the RBAC service.
"""

OWNED_TABLES = {
    "tickets",
    "interactions",
    "attachments",
    "ticket_audit_logs",
}