from uuid import UUID

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from shared_models.models import User

from app.auth.jwt import decode_token
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


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Verifies an RBAC-issued access token and returns the authenticated
    User (with .role and .category eager-loaded). Re-resolves the user
    from the shared `users` table on every request rather than trusting
    the token's embedded claims blindly — those can be stale up to the
    token's TTL, so a deactivated account is caught immediately, not
    just at next login.
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

    with timed_stage("auth"):
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