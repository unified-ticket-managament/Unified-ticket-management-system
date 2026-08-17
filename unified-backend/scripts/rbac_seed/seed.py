import asyncio

from sqlalchemy import select

from app.auth.password import get_password_hash
from app.database.session import AsyncSessionLocal, engine
from app.rbac.models import (
    Base,
    Category,
    Permission,
    ReportingManagerTeam,
    Role,
    RolePermission,
    User,
)

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
    # Roles-page Client tab — gates VIEWING a client company's own
    # detail fields (organization email, account manager name/active,
    # contact emails) via the dedicated GET /clients/{id}/details
    # endpoint, independent of role:view/user:view. Added as a
    # compensating control alongside widening GET /roles/{id}/users
    # from a hardcoded role allow-list to a plain user:view check (see
    # that route's own docstring) — that widening also opened the
    # Roles page itself to Team Lead/Staff/Client for the first time,
    # and this permission is what stops those roles from also seeing
    # the page's Client-tab details, which Super Admin/Site
    # Lead/Account Manager already saw unrestricted before. A normal,
    # independent permission row — role:view does not imply it, and it
    # implies nothing else in turn.
    ("client:view", "View a client company's organization email, account manager, and contact emails"),
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
    ("communication:attach_to_ticket", "Attach a communication to an existing ticket"),
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
    ("ticket:reply", "Reply to tickets"),
    ("ticket:editown_ticket", "Edit tickets assigned to yourself"),
    ("ticket:editother_ticket", "Edit tickets assigned to other agents — lets more than one person work the same ticket"),
    ("ticket:update_status", "Change ticket status"),
    ("ticket:close_ticket", "Close a ticket"),
    ("ticket:reopen", "Reopen a closed ticket"),
    ("ticket:escalate", "Flag a ticket as needing attention from someone more senior"),
    ("ticket:upload_attachment", "Upload a ticket attachment"),
    ("ticket:archive_attachment", "Delete/archive a ticket attachment"),
    ("ticket:hide_interaction", "Hide (soft-delete) a ticket interaction"),
    ("ticket:view_audit_trail", "View a ticket's own audit trail"),
    ("ticket:view_global_audit_log", "View the global ticket audit log"),
    ("ticket:view_dashboard_kpis", "View ticket workspace dashboard KPIs"),
    ("ticket:view_escalated", "View Escalated Tickets"),
    ("ticket:acknowledge_escalation", "Acknowledge an escalated ticket"),
    ("ticket:manage_agents", "Activate or deactivate agent accounts"),
    ("ticket:manage_roles_permissions", "Manage roles and permissions for the ticket workspace"),
    ("ticket:system_config", "Configure ticket system and storage settings"),
    # SLA policy admin — company-wide First Response/Resolution SLA
    # targets per priority, distinct from the existing (unenforced)
    # ticket:change_sla, which is about adjusting one ticket's own
    # target rather than editing the global policy matrix. Granted to
    # Site Lead/Super Admin only by default (see DEFAULT_ROLES below) —
    # SLA targets are a contractual/operational setting, not per-team
    # config.
    ("sla:manage_policies", "Edit company-wide SLA policy targets (First Response / Resolution minutes per priority)"),
    # Organization Structure — assigning/revoking an Account Manager's
    # "Reporting Manager" responsibility for a business category (see
    # root CLAUDE.md's "Organization Structure" section and
    # ReportingManagerTeam). Granted to Super Admin/Site Lead only by
    # default — this is an org-design/admin action, not a day-to-day
    # Account Manager capability.
    ("org:manage_reporting_managers", "Assign or revoke an Account Manager's Reporting Manager responsibility for a category"),
    # Mail/OTP Rules engine — creating, editing, enabling/disabling,
    # reordering, or deleting an automation rule. Granted to Super
    # Admin/Site Lead only by default (see SITE_LEAD_PERMISSIONS below)
    # — mirrors sla:manage_policies/org:manage_reporting_managers'own
    # "company-wide config, not day-to-day agent capability" reasoning.
    # Reading the rule list (GET /rules) needs no permission at all,
    # same "read is open, write is gated" bias as SLA policies.
    ("rule:manage", "Create, edit, enable/disable, reorder, or delete a Mail/OTP Rule"),
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
# Team Lead > Staff. Client (renamed from "Viewer") sits outside this
# hierarchy entirely (client-facing, unchanged). Grants below reflect
# only what a role gets *by default* ("Full" in the RBAC redesign doc)
# — everything a role doesn't hold by default is meant to be reachable
# later via a scoped, expiring permission override, not by widening
# these lists.
DEFAULT_ROLES = {
    "Super Admin": "all",
    "Site Lead": SITE_LEAD_PERMISSIONS,
    "Account Manager": [
        # Communication — full ownership of the client-facing inbox.
        "communication:create", "communication:view_all", "communication:view_assigned",
        "communication:reply_external", "communication:reply_internal", "communication:forward",
        "communication:convert_to_ticket", "communication:attach_to_ticket", "communication:merge",
        "communication:archive",
        "communication:view_timeline", "communication:assign", "communication:override_grant",
        # Ticket — everything except deep system configuration and the
        # global (cross-ticket) audit log, which the RBAC matrix doc
        # keeps override-only even for Account Manager.
        "ticket:create", "ticket:view_own", "ticket:view_unassigned", "ticket:view_others",
        "ticket:assign", "ticket:transfer", "ticket:change_priority", "ticket:change_category",
        "ticket:change_sla", "ticket:update_status", "ticket:reply",
        "ticket:editown_ticket", "ticket:editother_ticket",
        "ticket:close_ticket", "ticket:reopen", "ticket:escalate",
        "ticket:upload_attachment", "ticket:archive_attachment", "ticket:hide_interaction",
        "ticket:view_audit_trail", "ticket:view_dashboard_kpis",
        "ticket:view_escalated", "ticket:acknowledge_escalation",
        "ticket:manage_agents", "ticket:manage_roles_permissions",
        # User management — can manage Team Leads and Staff.
        "user:view", "user:create", "user:update", "user:disable", "user:reset_password",
        # Role & permission — can view and grant/revoke scoped overrides
        # for their own reports, but not edit role definitions.
        "role:view", "permission:view", "permission:override_grant", "permission:override_revoke",
        # Roles-page Client tab — already saw this unrestricted before
        # client:view existed; kept explicit here rather than relying
        # on any other grant to imply it.
        "client:view",
        # Mail/OTP Rules engine — Account Manager is one of the four
        # roles granted access when Rules moved under Mail.
        "rule:manage",
    ],
    "Team Lead": [
        # close_ticket/reopen/hide_interaction/view_global_audit_log are
        # deliberately absent here — the RBAC matrix doc keeps Team Lead
        # override-only for all four (see REVOKED_GRANTS for the two
        # that need an explicit one-time revocation on top of this).
        "communication:view_assigned", "communication:reply_external", "communication:reply_internal",
        "communication:forward", "communication:view_timeline",
        "ticket:view_own", "ticket:view_unassigned", "ticket:view_others", "ticket:assign",
        "ticket:transfer", "ticket:update_status", "ticket:reply",
        "ticket:editown_ticket", "ticket:editother_ticket",
        "ticket:escalate", "ticket:upload_attachment",
        "ticket:view_audit_trail", "ticket:view_dashboard_kpis",
        "ticket:view_escalated", "ticket:acknowledge_escalation",
        "user:view", "user:update",
        "role:view",
        # Mail/OTP Rules engine — Team Lead is one of the four roles
        # granted access when Rules moved under Mail.
        "rule:manage",
    ],
    "Staff": [
        # hide_interaction is deliberately absent — override-only per
        # the RBAC matrix doc (see REVOKED_GRANTS for the one-time
        # revocation this needs on top of just not re-granting it here).
        "communication:reply_external", "communication:reply_internal",
        "communication:view_assigned", "communication:view_timeline",
        "ticket:view_own", "ticket:view_unassigned", "ticket:view_others",
        "ticket:update_status", "ticket:reply", "ticket:upload_attachment",
        "ticket:editown_ticket",
        "ticket:view_audit_trail", "ticket:view_dashboard_kpis",
        # Full for Staff too (was Override-only per the RBAC compliance
        # audit above) — the ticket-level escalation-visibility feature
        # needs every agent role able to hold this by default, not just
        # supervisors, since the whole point is letting someone outside
        # a ticket's normal category/client scope see it once it's
        # escalated to them specifically (see
        # TicketRepository._visibility_conditions' escalation_override
        # param and TicketService.get_by_id).
        "ticket:view_escalated",
        "user:view",
    ],
    # Renamed from "Viewer" — see root CLAUDE.md's Client-role section.
    # Same role_id, same permission grants; a data migration
    # (alembic_rbac's a8c0e2f4b6d9) renames the row in place for any
    # database seeded before this rename, so this key always resolves
    # to that same pre-existing role rather than creating a new one.
    # Deliberately NOT given ticket:view_escalated: Client sits outside
    # AGENT_ROLE_NAMES entirely (see access_control.py), so it could
    # never pass ticket-detail authorization anyway — granting it here
    # would only reach the escalated-tab list gap, not real ticket
    # access, and isn't part of this feature's intent.
    "Client": ["user:view", "role:view", "permission:view"],
}

# Trimmed to the one genuinely required technical/system account
# (Super Admin — no real employee in the official org data maps to
# this role at all; see root CLAUDE.md's "Organization Structure" /
# "RBAC permission compliance audit" context). Every other entry this
# list used to contain (a generic Site Lead/Account Manager/Team
# Lead/Staff placeholder login, a "category coverage" block of
# fictional Team Leads/Staff, and two Client-role demo accounts) was a
# synthetic fixture with no real-employee counterpart — removed
# outright, along with the already-created database rows they seeded,
# during the employee/user data cleanup pass once
# scripts/org_seed/import_org_data.py's real 99-employee import made
# them redundant. Do not re-add fictional demo employee/user accounts
# here; scripts/org_seed/source_data.py is the real employee source of
# truth going forward.
DEMO_USERS = [
    {
        "name": "Super Admin",
        "email": "admin@rbac.com",
        "password": "Admin@123456",
        "role": "Super Admin",
    },
]

# Demo "Reporting Manager" assignments — the Organization Structure's
# HR/people-management responsibility layered onto an existing Account
# Manager, keyed by (account_manager_email, category name). Real
# assignments are made through the admin-only /reporting-managers
# endpoints, not by editing this list. Left empty: its one entry
# referenced the now-removed manager@probeps.com demo fixture (see
# DEMO_USERS' own comment) — real reporting-manager assignments should
# be made against real employees via those endpoints instead.
DEMO_REPORTING_MANAGERS = []

# Emails used by an earlier seed run that email-validator rejects
# (reserved/special-use TLDs). Renamed in place if found.
LEGACY_EMAIL_FIXES = {
    "admin@rbac.local": "admin@rbac.com",
}

# Display names left over from before the "Manager" -> "Account Manager"
# role rename. Fixed in place the same way LEGACY_EMAIL_FIXES is, keyed
# by email since that's the stable identifier across reseeds. Empty
# now that the demo manager@probeps.com fixture this once corrected has
# been removed (see DEMO_USERS' own comment) — kept as a dict (not
# deleted outright) since the mechanism itself is still valid for any
# future rename needing this exact fix-in-place pattern.
LEGACY_NAME_FIXES = {}

# Permissions removed entirely as concepts during the RBAC redesign
# (not moved to override-only — deleted). Role -> Permission grants
# referencing them are revoked first, then the Permission rows
# themselves are deleted, so no orphaned role_permissions row can
# reference a permission_id that no longer exists.
DEPRECATED_PERMISSIONS = [
    "ticket:bulk_reassign",
    "ticket:configure_routing",
    # Replaced by ticket:editown_ticket + ticket:editother_ticket (see
    # DEFAULT_PERMISSIONS above) — the old single permission conflated
    # "can work my own ticket" with "can work someone else's", which
    # made it impossible to grant a Staff member scoped access to one
    # specific teammate's ticket without also handing them blanket
    # access to every ticket in scope. Deleting the row cascades to any
    # role_permissions/user_permission_overrides/permission_requests
    # rows still referencing it (ondelete="CASCADE" on each FK) — fine
    # for this dev database, but re-grant anything real before running
    # this against data that matters.
    "ticket:edit_ticket",
    # Renamed to match the RBAC matrix doc's exact permission name.
    "ticket:close",
    # Split into ticket:upload_attachment (Full for everyone per the
    # doc) + ticket:archive_attachment (Override-only for Team Lead/
    # Staff) — the combined permission couldn't express that split.
    "ticket:manage_attachments",
]

# Specific (role, permission) grants that existed under the old
# capability matrix but were deliberately downgraded to override-only
# in the new one. The main seeding loop below is additive-only (it
# never revokes a grant just because a role's default list changed),
# by design — so these particular, deliberate downgrades need an
# explicit one-time revocation instead of relying on that loop.
REVOKED_GRANTS = [
    ("Staff", "ticket:create"),
    ("Staff", "ticket:transfer"),
    ("Staff", "ticket:reopen"),
    ("Staff", "user:update"),
    ("Team Lead", "ticket:reopen"),
    # Account Manager/Team Lead previously had Full access to the
    # global (cross-ticket) audit log and to hide_interaction; the
    # RBAC matrix doc keeps both override-only for these two roles.
    # Explicit revocation needed on top of removing them from
    # DEFAULT_ROLES above, since the main seeding loop is
    # additive-only and never claws back an existing grant on its own.
    ("Account Manager", "ticket:view_global_audit_log"),
    ("Team Lead", "ticket:view_global_audit_log"),
    ("Team Lead", "ticket:hide_interaction"),
    ("Staff", "ticket:hide_interaction"),
    # Found granted directly in the live dev DB with no corresponding
    # entry in DEFAULT_ROLES["Staff"] above — drift introduced outside
    # this seed script (e.g. a live toggle on the Roles page), not a
    # seed change. Staff deliberately does NOT hold ticket:editother_
    # ticket by default (every other agent role does) — that's the
    # whole reason the ticket-scoped Permission Request workflow
    # exists for Staff to ask for it one ticket at a time. Revoking
    # this here restores that baseline rather than introducing a new
    # restriction.
    ("Staff", "ticket:editother_ticket"),
    # Found during an end-to-end RBAC verification pass: these three
    # grants existed live (on the dev database's role_permissions
    # table) despite never having been part of either role's
    # DEFAULT_ROLES entry above in any version of this file the
    # additive-only seeding loop has run against — leftover drift from
    # before the RBAC matrix reconciliation, never explicitly clawed
    # back. Per the matrix, ticket:close_ticket/ticket:system_config
    # are Override-only for Staff (Staff having Full access to close a
    # ticket outright, bypassing the "a supervisor must verify before
    # the SLA clock stops" requirement Module 10/close_ticket's own
    # design depends on, is the one of these three with a real,
    # active enforcement gap — access_control.ensure_can_close_ticket
    # does check this permission for Staff); communication:create is
    # Override-only for Team Lead/Staff.
    ("Staff", "ticket:close_ticket"),
    ("Staff", "ticket:system_config"),
    ("Staff", "communication:create"),
    ("Team Lead", "communication:create"),
    # Found live during the ticket-assignment-status/attachment-
    # authorization bugfix pass: Staff held ticket:editother_ticket in
    # the connected database despite Staff's own DEFAULT_ROLES entry
    # above never having included it (the whole point of the
    # editown_ticket/editother_ticket split — see root CLAUDE.md's
    # "Backend merge, and ticket-scoped permission overrides" section
    # — is that editother_ticket is "Full for every role except
    # Staff", who must go through a scoped Permission Request instead).
    # With this grant present, access_control.ensure_agent_can_act_on_
    # ticket's `elif has_permission_for_ticket(..., "ticket:editother_
    # ticket", ...)` branch let ANY Staff member reply/change status/
    # upload attachments on ANY other Staff member's ticket, not just
    # their own — confirmed live via two real accounts (Vikram Shah
    # successfully uploaded to a ticket assigned to Ananya Rao, neither
    # holding a scoped override or edit-access grant). Same leftover-
    # drift shape as the three-entry block above this one; revoking it
    # here restores the "own ticket only, unless editother_ticket/an
    # edit-access grant says otherwise" boundary the seed's own
    # DEFAULT_ROLES already intended.
    ("Staff", "ticket:editother_ticket"),
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
        # Categories — read-only here. The categories table is owned
        # and seeded by an Alembic migration (a native Postgres enum
        # column, not a freeform lookup this script should be writing
        # to), so this just resolves category_name -> Category for the
        # demo users' category_id backfill below. If the migration
        # hasn't run yet, category_id assignment is skipped with a
        # warning rather than crashing the whole seed run.
        # --------------------------------------------------

        categories_by_name: dict[str, Category] = {
            category.category_name.value: category
            for category in (await session.execute(select(Category))).scalars().all()
        }

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

        # Backfill manager/team-lead reporting lines and category
        # assignment wherever they're still unset. Never overwrites an
        # existing assignment, so this is safe to re-run even if a
        # user's links were changed by hand afterwards.
        missing_categories: set[str] = set()

        for demo in DEMO_USERS:
            user = users_by_email[demo["email"]]

            manager_email = demo.get("manager_email")
            if manager_email and user.manager_id is None:
                user.manager_id = users_by_email[manager_email].user_id

            teamlead_email = demo.get("teamlead_email")
            if teamlead_email and user.teamlead_id is None:
                user.teamlead_id = users_by_email[teamlead_email].user_id

            category_name = demo.get("category")
            if category_name and user.category_id is None:
                category = categories_by_name.get(category_name)
                if category is not None:
                    user.category_id = category.category_id
                else:
                    missing_categories.add(category_name)

        await session.commit()

        if missing_categories:
            print(
                "Warning: could not assign these categories (run "
                "`alembic upgrade head` first to seed the categories "
                f"table): {sorted(missing_categories)}"
            )

        # --------------------------------------------------
        # Demo Reporting Manager assignments (idempotent)
        # --------------------------------------------------

        for account_manager_email, category_name in DEMO_REPORTING_MANAGERS:
            account_manager = users_by_email.get(account_manager_email)
            category = categories_by_name.get(category_name)

            if account_manager is None or category is None:
                continue

            existing_mapping = (
                await session.execute(
                    select(ReportingManagerTeam).where(
                        ReportingManagerTeam.account_manager_id == account_manager.user_id,
                        ReportingManagerTeam.category_id == category.category_id,
                    )
                )
            ).scalar_one_or_none()

            if existing_mapping is None:
                session.add(
                    ReportingManagerTeam(
                        account_manager_id=account_manager.user_id,
                        category_id=category.category_id,
                    )
                )

        await session.commit()

        print("Seed completed.")
        for demo in DEMO_USERS:
            print(f"{demo['role']} login: {demo['email']} / {demo['password']}")


if __name__ == "__main__":
    asyncio.run(seed())
