from uuid import UUID

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from shared_models.models import Category, CategoryName, Role, User

from app.auth.jwt import decode_token
from app.core.rbac_cache import get_rbac_cache
from app.core.request_timing import timed_stage
from app.database.session import get_db
# Deliberately ticketing's UserRepository, not rbac's, for this one
# shared dependency: its get_by_id eager-loads both User.role AND
# User.category (rbac's own UserRepository only loads .role). Every
# route in this merged app resolves its current user through here, and
# ticketing's category-scoped ticket routing needs .category already
# loaded to avoid a lazy-load in an async context. Loading .category
# for rbac's own routes is harmless — nothing there reads it, but
# nothing breaks by it being present either. rbac's own UserRepository
# (app.rbac.repositories.user_repository) is unaffected and still used
# by every rbac service for its own CRUD-style user operations.
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.services.access_control import AGENT_ROLE_NAMES

security = HTTPBearer()


def _build_transient_user(payload: dict) -> User:
    """
    Reconstructs the same shape UserRepository.get_by_id would have
    returned, straight from JWT claims, for the RBAC-cache-hit path —
    no DB round trip. Never added to a Session: these are plain Python
    objects, not query results, so nothing tries to flush or refresh
    them.

    Only populates what ticketing code actually reads off
    `current_user` (confirmed by grep before this was written):
    `.user_id`, `.name` (audit-log actor name), `.role.name`,
    `.category.category_name.value`, plus `.permissions`/
    `.scoped_permissions` (attached by the caller, same as the DB path).
    `.is_active` is unconditionally True here — a cache hit only exists
    because the last DB check confirmed it for this exact
    permission_version (see app/core/rbac_cache.py's module docstring).
    """

    user = User(
        user_id=UUID(payload["user_id"]),
        name=payload.get("name") or "",
        email=payload.get("email") or "",
        is_active=True,
        role_id=UUID(payload["role_id"]) if payload.get("role_id") else None,
        category_id=UUID(payload["category_id"]) if payload.get("category_id") else None,
        permission_version=payload.get("permission_version"),
    )
    user.role = Role(role_id=user.role_id, name=payload.get("role"))
    if payload.get("category_id") and payload.get("category"):
        user.category = Category(
            category_id=user.category_id,
            category_name=CategoryName(payload["category"]),
        )
    else:
        user.category = None
    return user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Verifies an RBAC-issued access token and returns the authenticated
    User (with .role and .category populated). Normally re-resolves
    the user from the shared `users` table so a deactivated account or
    a changed role/category is caught quickly rather than only at next
    login — but that DB round trip is now skipped whenever an in-
    memory cache (app/core/rbac_cache.py) already confirmed, within
    the last `rbac_cache_ttl_seconds`, that this exact
    (user_id, permission_version) pair is still valid. A version bump
    (role/category/team change, activation toggle, permission grant/
    revoke — see app/rbac/services/*) doesn't touch the cache; it just
    means the *next* DB-verified request for that user won't match the
    token's claimed version and gets rejected, bounding staleness to
    one cache TTL window rather than making it permanent.

    A token minted before this claim existed simply has no
    `permission_version` in its payload, which always takes the DB
    path below — degrades safely, same convention already used for
    `permissions`/`scoped_permissions`.
    """

    token = credentials.credentials

    try:
        payload = decode_token(token)

    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
        )

    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token.",
        )

    user_id = payload.get("user_id")

    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload.",
        )

    permission_version = payload.get("permission_version")
    cache = get_rbac_cache()

    with timed_stage("auth"):
        if permission_version is not None and cache.is_valid(user_id, permission_version):
            user = _build_transient_user(payload)
        else:
            user = await UserRepository(db).get_by_id(UUID(user_id))

            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User not found.",
                )

            if not user.is_active:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="User account is inactive.",
                )

            if (
                permission_version is not None
                and user.permission_version != permission_version
            ):
                # The DB has moved on to a newer authorization state
                # than this token was issued under (role/category/team
                # changed, permission granted/revoked, or the token's
                # own role's permission set changed) — reject rather
                # than silently trust stale role/category/permission
                # claims for the rest of this token's natural TTL.
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Session outdated — please sign in again.",
                )

            if permission_version is not None:
                cache.mark_valid(user_id, permission_version)

    # Transient attribute, not a mapped column — same pattern as
    # TicketService._attach_names, so SQLAlchemy never tries to
    # persist it. Defaults to [] rather than KeyError-ing so a token
    # issued before this claim existed still decodes safely.
    user.permissions = payload.get("permissions") or []

    # Ticket-scoped grants (permission_name -> list of ticket id
    # strings) — see app/auth/jwt.py's create_access_token. Same
    # degrade-safe default as .permissions above.
    user.scoped_permissions = payload.get("scoped_permissions") or {}

    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    rbac's own name for the same dependency — kept as a thin alias so
    every rbac route file's Depends(get_current_active_user) keeps
    working unchanged.
    """

    return current_user


async def get_current_agent(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Same as get_current_user, but additionally requires a role that can
    act on tickets (everyone except Viewer, RBAC's client-facing role).
    """

    if current_user.role.name not in AGENT_ROLE_NAMES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account cannot act on tickets.",
        )

    return current_user