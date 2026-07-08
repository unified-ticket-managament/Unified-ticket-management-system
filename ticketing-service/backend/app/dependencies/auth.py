from uuid import UUID

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from shared_models.models import User

from app.auth.jwt import decode_token
from app.database.session import get_db
from app.repositories.user_repository import UserRepository
from app.services.access_control import AGENT_ROLE_NAMES

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Verifies an RBAC-issued access token and returns the authenticated
    User (with .role loaded). Re-resolves the user from the shared
    `users` table on every request rather than trusting the token's
    embedded claims blindly — those can be up to the token's TTL stale,
    so a deactivated account is caught immediately, not just at next login.
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

    return user


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
