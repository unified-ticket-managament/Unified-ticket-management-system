# access_control.py
#
# RBAC-domain permission-check helper — mirrors
# app.ticketing.services.access_control's has_permission/
# ensure_has_permission exactly (both only ever read the flat
# `permissions` list get_current_user/get_current_active_user already
# threads onto `current_user` from the JWT's `permissions` claim, via
# the one shared app/dependencies/auth.py dependency both domains use).
# Kept as this module's own copy rather than importing ticketing's
# version directly, so app.rbac stays self-contained and doesn't reach
# across the module boundary for something this core — see the root
# CLAUDE.md's "one FastAPI app, not two" section for why that boundary
# is still worth preserving even inside one process.

from fastapi import HTTPException, status
from shared_models.models import Role, User


def has_permission(current_user: User, permission_name: str) -> bool:
    """
    Non-raising check against `current_user.permissions` (the JWT's
    `permissions` claim — role defaults union active unscoped personal
    overrides, computed by PermissionResolverService at login/refresh).
    A token issued before this claim existed degrades to an empty list
    rather than crashing, same convention as the ticketing side.
    """

    permissions = getattr(current_user, "permissions", None) or []

    return permission_name in permissions


def ensure_has_permission(current_user: User, permission_name: str) -> None:
    """Raising wrapper around has_permission — 403s if it's missing."""

    if not has_permission(current_user, permission_name):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing required permission: {permission_name}",
        )


# --------------------------------------------------------------------
# Role-permissions editor: which target roles an actor may grant/revoke
# permissions for. `permission:update` alone (checked above, at the
# route level) only proves the actor can edit *some* role's
# permissions — it says nothing about *which* role, since
# role_permissions has no notion of a target at all. A static
# allow-list, mirroring this codebase's existing role-vs-role rules
# (SUPERVISOR_ROLE_NAMES, CREATABLE_ROLES_BY_ROLE on the frontend), is
# the deliberate choice here over a new `roles.rank`/`role_level`
# column: the real rule is a curated allow-list (e.g. an Account
# Manager can't touch its own role) rather than a clean numeric
# ordering, and three entries don't justify a schema migration.
# Mirrored on the frontend by
# MANAGEABLE_PERMISSION_TARGET_ROLES_BY_ROLE in lib/role-access.ts —
# keep both in sync if this ever changes.
#
# No entry for a role name = that role can never manage any role's
# permissions (matches it never holding `permission:update` by
# default). `None` = unrestricted (any target role, including itself).
MANAGEABLE_PERMISSION_TARGET_ROLES: dict[str, set[str] | None] = {
    "Super Admin": None,
    "Site Lead": {"Account Manager", "Team Lead", "Staff"},
    "Account Manager": {"Team Lead", "Staff"},
}

# Only this role's grants (never revokes — see
# ensure_can_grant_role_permissions) are further restricted to
# permissions the actor personally holds.
PERMISSION_OWNERSHIP_SCOPED_ROLE = "Account Manager"


# --------------------------------------------------------------------
# Roles page ("Users -> Roles -> select a role") full-role-population
# visibility — GET /roles/{role_id}/users. `role:view` alone isn't a
# tight enough gate on its own: Team Lead and the client-facing
# "Client" role both hold `role:view` by default (see
# scripts/rbac_seed/seed.py's DEFAULT_ROLES), but only Super Admin/
# Site Lead/Account Manager are meant to see a role's full,
# unrestricted-by-hierarchy membership here — the same three roles
# that can already navigate to /roles at all today (mirrors
# ROLES_BUTTON_VISIBLE_ROLES in the frontend's users/page.tsx).
#
# Deliberately independent of OrganizationService.get_subordinate_
# user_ids/_build_subtree — this is a company-wide "who holds this
# role" query, not a reporting-hierarchy one, and must never be
# confused with (or fed back into) the hierarchy scoping that governs
# the Users page, the Organization Chart, or permission-override
# grant/revoke authority.
ROLES_PAGE_FULL_VISIBILITY_ROLE_NAMES: set[str] = {"Super Admin", "Site Lead", "Account Manager"}


def ensure_can_view_full_role_population(actor: User) -> None:
    """403s unless `actor`'s own role may see a role's full, company-wide membership."""

    if actor.role.name not in ROLES_PAGE_FULL_VISIBILITY_ROLE_NAMES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not permitted to view a role's full user list.",
        )


def get_manageable_permission_target_role_names(actor: User) -> set[str] | None:
    """None means unrestricted (any role, including the actor's own)."""

    return MANAGEABLE_PERMISSION_TARGET_ROLES.get(actor.role.name)


def ensure_can_manage_role_permissions(actor: User, target_role: Role) -> None:
    """
    403s unless `actor` is allowed to edit `target_role`'s permission
    set at all — independent of, and enforced in addition to, the
    caller's own `permission:update` check.
    """

    allowed = get_manageable_permission_target_role_names(actor)

    if allowed is not None and target_role.name not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"You are not permitted to manage the {target_role.name} role's permissions.",
        )


# --------------------------------------------------------------------
# Create User: which target roles an actor may assign when creating
# (or, via ensure_can_create_role's second call site in
# UserService.update_user, re-assigning) a user. This is the backend
# half of the security fix — the frontend's own CREATABLE_ROLES_BY_ROLE
# (lib/role-access.ts) only ever hid disallowed roles from the Select;
# nothing previously stopped a crafted POST /users request from
# assigning any role at all. Keep both in sync if this ever changes.
#
# No entry (Team Lead/Staff/Client) = every target role denied — matches
# those roles never holding `user:create` by default anyway (this is
# defense in depth, not the only gate). `None` = unrestricted (any of
# the six roles).
USER_CREATION_ROLE_MATRIX: dict[str, set[str] | None] = {
    "Super Admin": None,
    "Site Lead": None,
    "Account Manager": {"Team Lead", "Staff", "Client"},
}


def ensure_can_create_role(actor: User, target_role_name: str) -> None:
    """403s unless `actor`'s own role is permitted to create/assign `target_role_name`."""

    allowed = USER_CREATION_ROLE_MATRIX.get(actor.role.name, set())

    if allowed is not None and target_role_name not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"You are not permitted to create a {target_role_name} user.",
        )


def ensure_can_grant_role_permissions(actor: User, newly_granted_names: list[str]) -> None:
    """
    For PERMISSION_OWNERSHIP_SCOPED_ROLE only: 403s if any of the
    *newly added* permission names aren't ones the actor personally
    holds. Deliberately scoped to additions only, never removals — an
    Account Manager can still revoke a permission the role already has
    even if they don't personally hold it themselves; they just can't
    grant one they don't hold. Not applied to Super Admin/Site Lead at
    all (see MANAGEABLE_PERMISSION_TARGET_ROLES — this only ever runs
    for a caller whose role matches PERMISSION_OWNERSHIP_SCOPED_ROLE).
    """

    if actor.role.name != PERMISSION_OWNERSHIP_SCOPED_ROLE:
        return

    actor_permissions = set(getattr(actor, "permissions", None) or [])
    unowned = [name for name in newly_granted_names if name not in actor_permissions]

    if unowned:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"You can only grant permissions you personally hold. Missing: {', '.join(unowned)}",
        )
