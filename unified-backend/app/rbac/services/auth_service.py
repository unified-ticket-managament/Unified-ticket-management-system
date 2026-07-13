import json
from uuid import UUID

from fastapi import HTTPException, status

from shared_models.models import User

from app.auth.jwt import (
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.auth.password import (
    get_password_hash,
    verify_password,
)
from app.rbac.repositories.role_permission_repository import RolePermissionRepository
from app.rbac.repositories.user_repository import UserRepository
from app.rbac.schemas.audit_log import AuditLogCreate
from app.rbac.services.audit_log_service import AuditLogService
from app.rbac.services.permission_resolver import PermissionResolverService
from app.rbac.schemas.auth import (
    ChangePasswordRequest,
    CurrentUser,
    LoginRequest,
    RefreshTokenRequest,
    TokenResponse,
    UpdateProfileRequest,
)

class AuthService:
    """
    Handles authentication and authorization business logic.
    """

    def __init__(
        self,
        user_repository: UserRepository,
        role_permission_repository: RolePermissionRepository,
        permission_resolver: PermissionResolverService,
        audit_log_service: AuditLogService,
    ):
        self.user_repository = user_repository
        self.role_permission_repository = role_permission_repository
        self.permission_resolver = permission_resolver
        self.audit_log_service = audit_log_service

    # --------------------------------------------------
    # Login
    # --------------------------------------------------

    async def _log_login_failed(
        self,
        email: str,
        reason: str,
        ip_address: str | None,
        user_id: UUID | None = None,
    ) -> None:
        await self.audit_log_service.create_log(
            AuditLogCreate(
                user_id=user_id,
                action="auth.login_failed",
                entity_type="user",
                entity_id=str(user_id) if user_id else None,
                new_value=json.dumps({"email": email, "reason": reason}),
                ip_address=ip_address,
            )
        )

    async def login(
        self,
        login_data: LoginRequest,
        ip_address: str | None = None,
    ) -> TokenResponse:

        user = await self.user_repository.get_by_email(
            login_data.email,
        )

        if user is None:
            await self._log_login_failed(
                login_data.email, "invalid_email", ip_address
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password.",
            )

        if not user.is_active:
            await self._log_login_failed(
                login_data.email, "account_inactive", ip_address, user.user_id
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive.",
            )

        if not verify_password(
            login_data.password,
            user.password_hash,
        ):
            await self._log_login_failed(
                login_data.email, "invalid_password", ip_address, user.user_id
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password.",
            )

        permissions, _, scoped_permissions = (
            await self.permission_resolver.get_effective_permissions(user)
        )

        access_token = create_access_token(
            user_id=user.user_id,
            email=user.email,
            role=user.role.name,
            permissions=permissions,
            scoped_permissions=scoped_permissions,
            name=user.name,
            role_id=user.role_id,
            category_id=user.category_id,
            category=user.category.category_name.value if user.category else None,
            permission_version=user.permission_version,
        )

        refresh_token = create_refresh_token(
            user_id=user.user_id,
        )

        await self.audit_log_service.create_log(
            AuditLogCreate(
                user_id=user.user_id,
                action="auth.login",
                entity_type="user",
                entity_id=str(user.user_id),
                new_value=json.dumps({"email": user.email, "role": user.role.name}),
                ip_address=ip_address,
            )
        )

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
        )

    # --------------------------------------------------
    # Refresh Token
    # --------------------------------------------------

    async def refresh_token(
        self,
        request: RefreshTokenRequest,
    ) -> TokenResponse:

        try:
            payload = decode_token(
                request.refresh_token,
            )

        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired refresh token.",
            )

        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token.",
            )

        user_id = payload.get("user_id")

        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload.",
            )

        user = await self.user_repository.get_by_id(
            UUID(user_id),
        )

        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found.",
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive.",
            )

        permissions, _, scoped_permissions = (
            await self.permission_resolver.get_effective_permissions(user)
        )

        access_token = create_access_token(
            user_id=user.user_id,
            email=user.email,
            role=user.role.name,
            permissions=permissions,
            scoped_permissions=scoped_permissions,
            name=user.name,
            role_id=user.role_id,
            category_id=user.category_id,
            category=user.category.category_name.value if user.category else None,
            permission_version=user.permission_version,
        )

        refresh_token = create_refresh_token(
            user_id=user.user_id,
        )

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
        )

    # --------------------------------------------------
    # Current User
    # --------------------------------------------------

    async def get_current_user(
        self,
        user: User,
    ) -> CurrentUser:

        permissions, override_permissions, scoped_permissions = (
            await self.permission_resolver.get_effective_permissions(user)
        )

        return CurrentUser(
            user_id=user.user_id,
            name=user.name,
            email=user.email,
            role=user.role.name,
            role_id=user.role_id,
            is_active=user.is_active,
            permissions=permissions,
            override_permissions=override_permissions,
            scoped_permissions=scoped_permissions,
        )
    
    # --------------------------------------------------
    # Logout
    # --------------------------------------------------

    async def logout(
        self,
        user: User,
        ip_address: str | None = None,
    ) -> None:
        """
        Records a logout. Tokens are stateless JWTs with no server-side
        session to invalidate, so this is purely an audit-trail write —
        the client discards its tokens locally either way.
        """

        await self.audit_log_service.create_log(
            AuditLogCreate(
                user_id=user.user_id,
                action="auth.logout",
                entity_type="user",
                entity_id=str(user.user_id),
                ip_address=ip_address,
            )
        )

    # --------------------------------------------------
    # Change Password
    # --------------------------------------------------

    async def change_password(
        self,
        user: User,
        password_data: ChangePasswordRequest,
        ip_address: str | None = None,
    ) -> None:
        """
        Change the password for the authenticated user.
        """

        # Verify old password
        if not verify_password(
            password_data.old_password,
            user.password_hash,
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Old password is incorrect.",
            )

        # Prevent using the same password
        if verify_password(
            password_data.new_password,
            user.password_hash,
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="New password must be different from the old password.",
            )

        # Update password
        user.password_hash = get_password_hash(
            password_data.new_password,
        )

        await self.user_repository.update(user)

        await self.audit_log_service.create_log(
            AuditLogCreate(
                user_id=user.user_id,
                action="auth.change_password",
                entity_type="user",
                entity_id=str(user.user_id),
                ip_address=ip_address,
            )
        )

    # --------------------------------------------------
    # Update Profile
    # --------------------------------------------------

    async def update_profile(
        self,
        user: User,
        profile_data: UpdateProfileRequest,
    ) -> CurrentUser:
        """
        Update the name, email, and/or password of the authenticated user.
        """

        if profile_data.email and profile_data.email != user.email:

            existing = await self.user_repository.get_by_email(
                profile_data.email,
            )

            if existing and existing.user_id != user.user_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Email already exists.",
                )

            user.email = profile_data.email

        if profile_data.name:
            user.name = profile_data.name

        if profile_data.password:

            if not profile_data.current_password:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Current password is required to set a new password.",
                )

            if not verify_password(
                profile_data.current_password,
                user.password_hash,
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Current password is incorrect.",
                )

            user.password_hash = get_password_hash(
                profile_data.password,
            )

        await self.user_repository.update(user)

        return await self.get_current_user(user)