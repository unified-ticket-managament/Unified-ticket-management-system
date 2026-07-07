import asyncio

from sqlalchemy import select

from app.auth.password import get_password_hash
from app.database.session import AsyncSessionLocal, engine
from app.models import Base, Permission, Role, RolePermission, User

DEFAULT_PERMISSIONS = [
    ("user:create", "Create users"),
    ("user:view", "View users"),
    ("user:update", "Update users"),
    ("user:delete", "Delete users"),
    ("user:disable", "Activate or deactivate a user account"),
    ("user:reset_password", "Force-reset another user's password"),
    ("role:create", "Create roles"),
    ("role:view", "View roles"),
    ("role:update", "Update roles"),
    ("role:delete", "Delete roles"),
    ("permission:view", "View permissions"),
    ("permission:update", "Update role permissions"),
    ("permission:override_grant", "Grant a one-off permission exception to a specific user"),
    ("permission:override_revoke", "Revoke a previously granted permission exception"),
    ("audit:view", "View audit logs"),
    ("audit:export", "Export the audit log"),
    # Communication capabilities (ticketing-service) — RBAC's own
    # permission records for the Communication-first workflow (every
    # client interaction starts as a Communication; only some become
    # Tickets). Like the ticket:* rows below, these aren't enforced by
    # either backend yet — they exist so roles can be provisioned ahead
    # of the Communication feature being built, matching the same
    # forward-looking pattern already used for ticket:*.
    ("communication:create", "Log a new communication"),
    ("communication:view_all", "See every communication in the system"),
    ("communication:view_assigned", "See communications assigned to you or your team"),
    ("communication:reply_external", "Reply to a communication so the client sees it"),
    ("communication:reply_internal", "Add a staff-only note on a communication"),
    ("communication:forward", "Forward a communication to someone else"),
    ("communication:convert_to_ticket", "Turn a communication into a formal ticket"),
    ("communication:merge", "Merge a communication into an existing ticket"),
    ("communication:archive", "Close out a communication without a ticket"),
    ("communication:view_timeline", "See a communication's full history"),
    ("communication:assign", "Hand a communication to a specific person or team"),
    ("communication:override_grant", "Grant a one-off communication permission exception"),
    # Ticket Management capabilities (ticketing-service) — RBAC's own
    # permission records for the ticket workspace. These aren't
    # enforced by the Ticketing backend (it authorizes purely by role
    # name — see AGENT_ROLE_NAMES/SUPERVISOR_ROLE_NAMES in
    # ticketing-service/backend/app/services/access_control.py) or by
    # RBAC's own backend (which, like the rest of this system, only
    # checks authentication server-side); they exist so Super Admin can
    # see and manage the full ticket-management capability set from
    # the Users page, and so the ticket workspace frontend has
    # `hasPermission()` checks available if finer-grained gating is
    # added there later.
    ("ticket:create", "Create tickets from inbound emails"),
    ("ticket:view_own", "View tickets assigned to you"),
    ("ticket:view_unassigned", "View unassigned tickets"),
    ("ticket:view_others", "View tickets assigned to other agents"),
    ("ticket:assign", "Hand a ticket to a specific person or team"),
    ("ticket:transfer", "Transfer a ticket to another agent"),
    ("ticket:change_priority", "Change how urgent a ticket is marked"),
    ("ticket:change_category", "Change what type of issue a ticket is filed under"),
    ("ticket:change_sla", "Adjust the response/resolution time target on a ticket"),
    ("ticket:reply", "Reply to tickets and add internal notes"),
    ("ticket:update_status", "Change ticket status"),
    ("ticket:reopen", "Reopen a closed ticket"),
    ("ticket:escalate", "Flag a ticket as needing attention from someone more senior"),
    ("ticket:manage_attachments", "Upload or delete ticket attachments"),
    ("ticket:hide_interaction", "Hide (soft-delete) a ticket interaction"),
    ("ticket:view_audit_trail", "View a ticket's own audit trail"),
    ("ticket:view_global_audit_log", "View the global ticket audit log"),
    ("ticket:view_dashboard_kpis", "View ticket workspace dashboard KPIs"),
    ("ticket:manage_agents", "Activate or deactivate agent accounts"),
    ("ticket:manage_roles_permissions", "Manage roles and permissions for the ticket workspace"),
    ("ticket:system_config", "Configure ticket system and storage settings"),
]

# `ticket:bulk_reassign` and `ticket:configure_routing` (previously part
# of DEFAULT_PERMISSIONS) were deliberately removed as separate concepts
# during the RBAC redesign: bulk reassignment needs no dedicated
# permission beyond `ticket:assign`/`ticket:transfer` applied per item
# via a multi-select UI, and routing-rule configuration folds into
# `ticket:system_config`. `permission:view_effective` (a proposed
# "what can this person do" screen) was likewise decided to be a UI
# feature built on `permission:view`/`role:view`, not its own gate — it
# was never added here, so there's nothing to remove for it.
_ALL_PERMISSION_NAMES = [name for name, _ in DEFAULT_PERMISSIONS]

# Site Lead gets every permission except the two kept Super-Admin-only
# by design: deep system/infrastructure configuration and compliance
# audit export. Computed from the full list (rather than hand-listed)
# so it can never silently drift out of sync as permissions are added.
_SITE_LEAD_EXCLUDED = {"ticket:system_config", "audit:export"}
SITE_LEAD_PERMISSIONS = [
    name for name in _ALL_PERMISSION_NAMES if name not in _SITE_LEAD_EXCLUDED
]

# Role hierarchy: Super Admin (system/technical, "all") > Site Lead (top
# business/operational role, "all except two") > Account Manager >
# Team Lead > Staff. Viewer sits outside this hierarchy entirely
# (client-facing, unchanged). Grants below reflect only what a role
# gets *by default* ("Full" in the RBAC redesign doc) — everything a
# role doesn't hold by default is meant to be reachable later via a
# scoped, expiring permission override, not by widening these lists.
DEFAULT_ROLES = {
    "Super Admin": "all",
    "Site Lead": SITE_LEAD_PERMISSIONS,
    "Account Manager": [
        # Communication — full ownership of the client-facing inbox.
        "communication:create", "communication:view_all", "communication:view_assigned",
        "communication:reply_external", "communication:reply_internal", "communication:forward",
        "communication:convert_to_ticket", "communication:merge", "communication:archive",
        "communication:view_timeline", "communication:assign", "communication:override_grant",
        # Ticket — everything except deep system configuration.
        "ticket:create", "ticket:view_own", "ticket:view_unassigned", "ticket:view_others",
        "ticket:assign", "ticket:transfer", "ticket:change_priority", "ticket:change_category",
        "ticket:change_sla", "ticket:update_status", "ticket:reply", "ticket:reopen",
        "ticket:escalate", "ticket:manage_attachments", "ticket:hide_interaction",
        "ticket:view_audit_trail", "ticket:view_global_audit_log", "ticket:view_dashboard_kpis",
        "ticket:manage_agents", "ticket:manage_roles_permissions",
        # User management — can manage Team Leads and Staff.
        "user:view", "user:create", "user:update", "user:disable", "user:reset_password",
        # Role & permission — can view and grant/revoke scoped overrides
        # for their own reports, but not edit role definitions.
        "role:view", "permission:view", "permission:override_grant", "permission:override_revoke",
    ],
    "Team Lead": [
        "communication:view_assigned", "communication:reply_internal", "communication:forward",
        "communication:view_timeline",
        "ticket:view_own", "ticket:view_unassigned", "ticket:view_others", "ticket:assign",
        "ticket:transfer", "ticket:update_status", "ticket:reply", "ticket:escalate",
        "ticket:manage_attachments", "ticket:hide_interaction", "ticket:view_audit_trail",
        "ticket:view_global_audit_log", "ticket:view_dashboard_kpis",
        "user:view", "user:update",
        "role:view",
    ],
    "Staff": [
        "communication:reply_internal",
        "ticket:view_own", "ticket:update_status", "ticket:reply", "ticket:manage_attachments",
        "ticket:hide_interaction", "ticket:view_audit_trail", "ticket:view_dashboard_kpis",
        "user:view",
    ],
    "Viewer": ["user:view", "role:view", "permission:view"],
}

DEMO_USERS = [
    {
        "name": "Super Admin",
        "email": "admin@rbac.com",
        "password": "Admin@123456",
        "role": "Super Admin",
    },
    {
        "name": "Site Lead",
        "email": "sitelead@probeps.com",
        "password": "SiteLead@123",
        "role": "Site Lead",
    },
    {
        "name": "Account Manager",
        "email": "manager@probeps.com",
        "password": "Manager@123",
        "role": "Account Manager",
    },
    {
        "name": "Team Lead",
        "email": "teamlead@probeps.com",
        "password": "TeamLead@123",
        "role": "Team Lead",
        "manager_email": "manager@probeps.com",
    },
    {
        "name": "Priya Nair",
        "email": "priya.nair@probeps.com",
        "password": "Welcome@123",
        "role": "Team Lead",
        "manager_email": "manager@probeps.com",
    },
    {
        "name": "Staff",
        "email": "staff@probeps.com",
        "password": "Staff@123",
        "role": "Staff",
        "manager_email": "manager@probeps.com",
        "teamlead_email": "teamlead@probeps.com",
    },
    {
        "name": "John Carter",
        "email": "john.carter@probeps.com",
        "password": "Welcome@123",
        "role": "Staff",
        "manager_email": "manager@probeps.com",
        "teamlead_email": "teamlead@probeps.com",
    },
    {
        "name": "Emma Watts",
        "email": "emma.watts@probeps.com",
        "password": "Welcome@123",
        "role": "Staff",
        "manager_email": "manager@probeps.com",
        "teamlead_email": "priya.nair@probeps.com",
    },
    {
        "name": "Liam Brooks",
        "email": "liam.brooks@probeps.com",
        "password": "Welcome@123",
        "role": "Staff",
        "manager_email": "manager@probeps.com",
        "teamlead_email": "priya.nair@probeps.com",
    },
    {
        "name": "Viewer",
        "email": "viewer@probeps.com",
        "password": "Viewer@123",
        "role": "Viewer",
    },
    {
        "name": "Sophia Turner",
        "email": "sophia.turner@probeps.com",
        "password": "Welcome@123",
        "role": "Viewer",
    },
]

# Emails used by an earlier seed run that email-validator rejects
# (reserved/special-use TLDs). Renamed in place if found.
LEGACY_EMAIL_FIXES = {
    "admin@rbac.local": "admin@rbac.com",
}

# Display names left over from before the "Manager" -> "Account Manager"
# role rename. Fixed in place the same way LEGACY_EMAIL_FIXES is, keyed
# by email since that's the stable identifier across reseeds.
LEGACY_NAME_FIXES = {
    "manager@probeps.com": "Account Manager",
}

# Permissions removed entirely as concepts during the RBAC redesign
# (not moved to override-only — deleted). Role -> Permission grants
# referencing them are revoked first, then the Permission rows
# themselves are deleted, so no orphaned role_permissions row can
# reference a permission_id that no longer exists.
DEPRECATED_PERMISSIONS = ["ticket:bulk_reassign", "ticket:configure_routing"]

# Specific (role, permission) grants that existed under the old
# capability matrix but were deliberately downgraded to override-only
# in the new one. The main seeding loop below is additive-only (it
# never revokes a grant just because a role's default list changed),
# by design — so these particular, deliberate downgrades need an
# explicit one-time revocation instead of relying on that loop.
REVOKED_GRANTS = [
    ("Staff", "ticket:create"),
    ("Staff", "ticket:view_unassigned"),
    ("Staff", "ticket:transfer"),
    ("Staff", "ticket:reopen"),
    ("Staff", "user:update"),
    ("Team Lead", "ticket:reopen"),
]


async def seed() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:

        # --------------------------------------------------
        # One-time rename: "Manager" -> "Account Manager"
        # (in place, so it keeps its role_id and every existing user,
        # role_permission grant, and manager_id/teamlead_id
        # relationship pointing at it keeps working with no further
        # migration needed)
        # --------------------------------------------------

        legacy_manager_result = await session.execute(
            select(Role).where(Role.name == "Manager")
        )
        legacy_manager_role = legacy_manager_result.scalar_one_or_none()

        if legacy_manager_role is not None:
            account_manager_result = await session.execute(
                select(Role).where(Role.name == "Account Manager")
            )
            if account_manager_result.scalar_one_or_none() is None:
                legacy_manager_role.name = "Account Manager"
                await session.flush()

        # --------------------------------------------------
        # One-time cleanup: deprecated permissions and the specific
        # grants that were downgraded to override-only (see the two
        # lists' docstrings above for why this can't just be additive)
        # --------------------------------------------------

        for permission_name in DEPRECATED_PERMISSIONS:
            deprecated_permission = (
                await session.execute(
                    select(Permission).where(Permission.permission_name == permission_name)
                )
            ).scalar_one_or_none()

            if deprecated_permission is not None:
                await session.execute(
                    RolePermission.__table__.delete().where(
                        RolePermission.permission_id == deprecated_permission.permission_id
                    )
                )
                await session.delete(deprecated_permission)

        for role_name, permission_name in REVOKED_GRANTS:
            role_for_revoke = (
                await session.execute(select(Role).where(Role.name == role_name))
            ).scalar_one_or_none()
            permission_for_revoke = (
                await session.execute(
                    select(Permission).where(Permission.permission_name == permission_name)
                )
            ).scalar_one_or_none()

            if role_for_revoke is not None and permission_for_revoke is not None:
                await session.execute(
                    RolePermission.__table__.delete().where(
                        RolePermission.role_id == role_for_revoke.role_id,
                        RolePermission.permission_id == permission_for_revoke.permission_id,
                    )
                )

        await session.flush()

        # --------------------------------------------------
        # Permissions (idempotent)
        # --------------------------------------------------

        permissions: dict[str, Permission] = {}

        for name, description in DEFAULT_PERMISSIONS:
            result = await session.execute(
                select(Permission).where(Permission.permission_name == name)
            )
            permission = result.scalar_one_or_none()

            if permission is None:
                permission = Permission(permission_name=name, description=description)
                session.add(permission)
                await session.flush()

            permissions[name] = permission

        # --------------------------------------------------
        # Roles (idempotent)
        # --------------------------------------------------

        roles: dict[str, Role] = {}

        for role_name in DEFAULT_ROLES:
            result = await session.execute(
                select(Role).where(Role.name == role_name)
            )
            role = result.scalar_one_or_none()

            if role is None:
                role = Role(name=role_name)
                session.add(role)
                await session.flush()

            roles[role_name] = role

        # --------------------------------------------------
        # Role -> Permission mappings (idempotent, additive-only —
        # never revokes a permission a role already has, even if this
        # run's default list for that role no longer includes it, so
        # any permission granted by hand or by an override mechanism
        # later is never silently clawed back by re-seeding)
        # --------------------------------------------------

        for role_name, perm_names in DEFAULT_ROLES.items():
            role = roles[role_name]

            names = (
                list(permissions.keys())
                if perm_names == "all"
                else perm_names
            )

            existing = await session.execute(
                select(RolePermission.permission_id).where(
                    RolePermission.role_id == role.role_id
                )
            )
            existing_ids = {row[0] for row in existing.all()}

            for perm_name in names:
                permission = permissions[perm_name]

                if permission.permission_id not in existing_ids:
                    session.add(
                        RolePermission(
                            role_id=role.role_id,
                            permission_id=permission.permission_id,
                        )
                    )

        # --------------------------------------------------
        # Fix emails from an earlier seed run rejected by
        # email-validator (reserved/special-use TLDs)
        # --------------------------------------------------

        for old_email, new_email in LEGACY_EMAIL_FIXES.items():
            result = await session.execute(
                select(User).where(User.email == old_email)
            )
            legacy_user = result.scalar_one_or_none()

            if legacy_user is not None:
                legacy_user.email = new_email

        # --------------------------------------------------
        # Fix display names left over from the Manager -> Account
        # Manager rename
        # --------------------------------------------------

        for email, correct_name in LEGACY_NAME_FIXES.items():
            result = await session.execute(
                select(User).where(User.email == email)
            )
            legacy_named_user = result.scalar_one_or_none()

            if legacy_named_user is not None and legacy_named_user.name != correct_name:
                legacy_named_user.name = correct_name

        await session.flush()

        # --------------------------------------------------
        # Demo users (idempotent)
        # --------------------------------------------------

        users_by_email: dict[str, User] = {}

        for demo in DEMO_USERS:
            result = await session.execute(
                select(User).where(User.email == demo["email"])
            )
            user = result.scalar_one_or_none()

            if user is None:
                user = User(
                    name=demo["name"],
                    email=demo["email"],
                    password_hash=get_password_hash(demo["password"]),
                    role_id=roles[demo["role"]].role_id,
                    is_active=True,
                )
                session.add(user)
                await session.flush()

            users_by_email[demo["email"]] = user

        # Backfill manager/team-lead reporting lines wherever they're
        # still unset. Never overwrites an existing assignment, so
        # this is safe to re-run even if a user's links were changed
        # by hand afterwards.
        for demo in DEMO_USERS:
            user = users_by_email[demo["email"]]

            manager_email = demo.get("manager_email")
            if manager_email and user.manager_id is None:
                user.manager_id = users_by_email[manager_email].user_id

            teamlead_email = demo.get("teamlead_email")
            if teamlead_email and user.teamlead_id is None:
                user.teamlead_id = users_by_email[teamlead_email].user_id

        await session.commit()

        print("Seed completed.")
        for demo in DEMO_USERS:
            print(f"{demo['role']} login: {demo['email']} / {demo['password']}")


if __name__ == "__main__":
    asyncio.run(seed())
