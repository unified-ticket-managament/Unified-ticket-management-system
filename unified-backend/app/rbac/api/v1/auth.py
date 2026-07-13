from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.auth import get_current_active_user
from app.database.session import get_db
from app.rbac.repositories.audit_log_repository import AuditLogRepository
from app.rbac.repositories.permission_override_repository import (
    PermissionOverrideRepository,
)
from app.rbac.repositories.role_permission_repository import RolePermissionRepository
from app.rbac.repositories.user_repository import UserRepository
from app.rbac.schemas.auth import (
    ChangePasswordRequest,
    CurrentUser,
    LoginRequest,
    RefreshTokenRequest,
    TokenResponse,
    UpdateProfileRequest,
)
from app.rbac.services.audit_log_service import AuditLogService
from app.rbac.services.auth_service import AuthService
from app.rbac.services.permission_resolver import PermissionResolverService

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)


# --------------------------------------------------
# Dependency
# --------------------------------------------------


def get_auth_service(
    db: AsyncSession = Depends(get_db),
) -> AuthService:
    """
    Returns AuthService instance.
    """
    user_repository = UserRepository(db)
    role_permission_repository = RolePermissionRepository(db)
    permission_override_repository = PermissionOverrideRepository(db)

    permission_resolver = PermissionResolverService(
        role_permission_repository=role_permission_repository,
        permission_override_repository=permission_override_repository,
    )

    audit_log_service = AuditLogService(
        audit_log_repository=AuditLogRepository(db),
    )

    return AuthService(
        user_repository=user_repository,
        role_permission_repository=role_permission_repository,
        permission_resolver=permission_resolver,
        audit_log_service=audit_log_service,
    )


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


# --------------------------------------------------
# Login
# --------------------------------------------------


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Login",
)
async def login(
    login_data: LoginRequest,
    request: Request,
    service: AuthService = Depends(get_auth_service),
):
    """
    Authenticate user and generate access/refresh tokens.
    """
    return await service.login(login_data, ip_address=_client_ip(request))


# --------------------------------------------------
# Refresh Token
# --------------------------------------------------


@router.post(
    "/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Refresh Access Token",
)
async def refresh_token(
    request: RefreshTokenRequest,
    service: AuthService = Depends(get_auth_service),
):
    """
    Generate a new access token using a refresh token.
    """
    return await service.refresh_token(request)


# --------------------------------------------------
# Logout
# --------------------------------------------------


@router.post(
    "/logout",
    status_code=status.HTTP_200_OK,
    summary="Logout",
)
async def logout(
    request: Request,
    current_user=Depends(get_current_active_user),
    service: AuthService = Depends(get_auth_service),
):
    """
    Records a logout in the audit trail. Tokens are stateless JWTs —
    the client is responsible for discarding them locally; there is
    no server-side session to invalidate.
    """
    await service.logout(current_user, ip_address=_client_ip(request))

    return {"message": "Logged out successfully."}


# --------------------------------------------------
# Current User
# --------------------------------------------------


@router.get(
    "/me",
    response_model=CurrentUser,
    status_code=status.HTTP_200_OK,
    summary="Current User",
)
async def get_current_user(
    current_user=Depends(get_current_active_user),
    service: AuthService = Depends(get_auth_service),
):
    """
    Returns currently authenticated user.
    """
    return await service.get_current_user(current_user)


# --------------------------------------------------
# Update Profile
# --------------------------------------------------


@router.patch(
    "/me",
    response_model=CurrentUser,
    status_code=status.HTTP_200_OK,
    summary="Update Profile",
)
async def update_profile(
    profile_data: UpdateProfileRequest,
    current_user=Depends(get_current_active_user),
    service: AuthService = Depends(get_auth_service),
):
    """
    Update the authenticated user's name, email, and/or password.
    """
    return await service.update_profile(
        current_user,
        profile_data,
    )


# --------------------------------------------------
# Change Password
# --------------------------------------------------


@router.post(
    "/change-password",
    status_code=status.HTTP_200_OK,
    summary="Change Password",
)
async def change_password(
    password_data: ChangePasswordRequest,
    request: Request,
    current_user=Depends(get_current_active_user),
    service: AuthService = Depends(get_auth_service),
):
    """
    Change the password of the authenticated user.
    """
    await service.change_password(
        current_user,
        password_data,
        ip_address=_client_ip(request),
    )

    return {
        "message": "Password changed successfully."
    }