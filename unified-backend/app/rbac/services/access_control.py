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
from shared_models.models import User


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
