from datetime import datetime, timedelta, timezone
from math import ceil
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    get_password_hash,
    verify_password,
)
from app.models import Role, User
from app.repositories import (
    AuditLogRepository,
    PermissionRepository,
    RefreshTokenRepository,
    RoleRepository,
    UserRepository,
    build_pagination,
)
from app.schemas import (
    AuditLogResponse,
    AuthMeResponse,
    LoginRequest,
    PaginatedResponse,
    PermissionResponse,
    ProfileUpdate,
    RoleCreate,
    RolePermissionsUpdate,
    RoleResponse,
    RoleUpdate,
    TokenResponse,
    UserCreate,
    UserResponse,
    UserUpdate,
)

settings = get_settings()


class AuditService:
    def __init__(self, db: AsyncSession):
        self.repo = AuditLogRepository(db)

    async def log(
        self,
        *,
        actor_id: UUID | None,
        action: str,
        entity_type: str,
        entity_id: str | None = None,
        old_value: dict | None = None,
        new_value: dict | None = None,
    ) -> None:
        await self.repo.create(
            user_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            old_value=old_value,
            new_value=new_value,
        )


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.users = UserRepository(db)
        self.refresh_tokens = RefreshTokenRepository(db)
        self.audit = AuditService(db)

    async def login(self, payload: LoginRequest) -> TokenResponse:
        user = await self.users.get_by_email(payload.email.lower())
        if not user or not verify_password(payload.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is inactive",
            )

        access_token = create_access_token(
            user_id=user.id,
            email=user.email,
            role=user.role.name,
        )
        refresh_token = create_refresh_token(user_id=user.id)
        expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
        await self.refresh_tokens.create(user.id, refresh_token, expires_at)

        await self.audit.log(
            actor_id=user.id,
            action="user.login",
            entity_type="user",
            entity_id=str(user.id),
        )

        return TokenResponse(access_token=access_token, refresh_token=refresh_token)

    async def refresh(self, refresh_token: str) -> TokenResponse:
        stored = await self.refresh_tokens.get_valid_token(refresh_token)
        if not stored or not stored.user or stored.user.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token",
            )
        if not stored.user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is inactive",
            )

        await self.refresh_tokens.revoke(stored)
        new_refresh = create_refresh_token(user_id=stored.user_id)
        expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
        await self.refresh_tokens.create(stored.user_id, new_refresh, expires_at)

        access_token = create_access_token(
            user_id=stored.user.id,
            email=stored.user.email,
            role=stored.user.role.name,
        )
        return TokenResponse(access_token=access_token, refresh_token=new_refresh)

    async def logout(self, user: User, refresh_token: str | None = None) -> None:
        if refresh_token:
            stored = await self.refresh_tokens.get_valid_token(refresh_token)
            if stored:
                await self.refresh_tokens.revoke(stored)
        else:
            await self.refresh_tokens.revoke_all_for_user(user.id)

        await self.audit.log(
            actor_id=user.id,
            action="user.logout",
            entity_type="user",
            entity_id=str(user.id),
        )

    async def get_me(self, user: User) -> AuthMeResponse:
        permissions = sorted({p.permission_name for p in user.role.permissions})
        return AuthMeResponse(
            id=user.id,
            name=user.name,
            email=user.email,
            role=user.role.name,
            role_id=user.role_id,
            permissions=permissions,
            is_active=user.is_active,
        )


class UserService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.users = UserRepository(db)
        self.roles = RoleRepository(db)
        self.audit = AuditService(db)

    def _serialize_user(self, user: User) -> dict:
        return {
            "id": str(user.id),
            "name": user.name,
            "email": user.email,
            "role_id": str(user.role_id),
            "is_active": user.is_active,
        }

    async def list_users(
        self,
        *,
        page: int,
        page_size: int,
        search: str | None,
        role_id: UUID | None,
        is_active: bool | None,
    ) -> PaginatedResponse[UserResponse]:
        users, total = await self.users.list_users(
            page=page,
            page_size=page_size,
            search=search,
            role_id=role_id,
            is_active=is_active,
        )
        pagination = build_pagination(total, page, page_size)
        return PaginatedResponse[UserResponse](
            items=[UserResponse.model_validate(u) for u in users],
            **pagination,
        )

    async def get_user(self, user_id: UUID) -> UserResponse:
        user = await self.users.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        return UserResponse.model_validate(user)

    async def create_user(self, payload: UserCreate, actor: User) -> UserResponse:
        if await self.users.get_by_email(payload.email.lower()):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")

        role = await self.roles.get_by_id(payload.role_id)
        if not role:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

        user = User(
            name=payload.name,
            email=payload.email.lower(),
            password_hash=get_password_hash(payload.password),
            role_id=payload.role_id,
            is_active=payload.is_active,
        )
        created = await self.users.create(user)
        await self.audit.log(
            actor_id=actor.id,
            action="user.created",
            entity_type="user",
            entity_id=str(created.id),
            new_value=self._serialize_user(created),
        )
        return UserResponse.model_validate(created)

    async def update_user(self, user_id: UUID, payload: UserUpdate, actor: User) -> UserResponse:
        user = await self.users.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        old_value = self._serialize_user(user)

        if payload.email and payload.email.lower() != user.email:
            existing = await self.users.get_by_email(payload.email.lower())
            if existing and existing.id != user.id:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")
            user.email = payload.email.lower()

        if payload.name is not None:
            user.name = payload.name
        if payload.role_id is not None:
            role = await self.roles.get_by_id(payload.role_id)
            if not role:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
            user.role_id = payload.role_id
        if payload.is_active is not None:
            user.is_active = payload.is_active
        if payload.password:
            user.password_hash = get_password_hash(payload.password)

        updated = await self.users.update(user)
        await self.audit.log(
            actor_id=actor.id,
            action="user.updated",
            entity_type="user",
            entity_id=str(updated.id),
            old_value=old_value,
            new_value=self._serialize_user(updated),
        )
        return UserResponse.model_validate(updated)

    async def delete_user(self, user_id: UUID, actor: User) -> None:
        user = await self.users.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        if user.id == actor.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete your own account",
            )

        old_value = self._serialize_user(user)
        await self.users.soft_delete(user)
        await self.audit.log(
            actor_id=actor.id,
            action="user.deleted",
            entity_type="user",
            entity_id=str(user.id),
            old_value=old_value,
        )

    async def update_profile(self, user: User, payload: ProfileUpdate) -> UserResponse:
        old_value = self._serialize_user(user)

        if payload.password:
            if not payload.current_password or not verify_password(
                payload.current_password, user.password_hash
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Current password is incorrect",
                )
            user.password_hash = get_password_hash(payload.password)

        if payload.email and payload.email.lower() != user.email:
            existing = await self.users.get_by_email(payload.email.lower())
            if existing and existing.id != user.id:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")
            user.email = payload.email.lower()

        if payload.name is not None:
            user.name = payload.name

        updated = await self.users.update(user)
        await self.audit.log(
            actor_id=user.id,
            action="user.profile_updated",
            entity_type="user",
            entity_id=str(updated.id),
            old_value=old_value,
            new_value=self._serialize_user(updated),
        )
        return UserResponse.model_validate(updated)


class RoleService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.roles = RoleRepository(db)
        self.audit = AuditService(db)

    def _serialize_role(self, role: Role) -> dict:
        return {
            "id": str(role.id),
            "name": role.name,
            "description": role.description,
            "permissions": [p.permission_name for p in role.permissions],
        }

    async def list_roles(self) -> list[RoleResponse]:
        roles = await self.roles.list_roles()
        return [RoleResponse.model_validate(r) for r in roles]

    async def create_role(self, payload: RoleCreate, actor: User) -> RoleResponse:
        if await self.roles.get_by_name(payload.name):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Role already exists")

        role = Role(name=payload.name, description=payload.description)
        created = await self.roles.create(role)
        await self.audit.log(
            actor_id=actor.id,
            action="role.created",
            entity_type="role",
            entity_id=str(created.id),
            new_value=self._serialize_role(created),
        )
        return RoleResponse.model_validate(created)

    async def update_role(self, role_id: UUID, payload: RoleUpdate, actor: User) -> RoleResponse:
        role = await self.roles.get_by_id(role_id)
        if not role:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

        old_value = self._serialize_role(role)

        if payload.name and payload.name != role.name:
            existing = await self.roles.get_by_name(payload.name)
            if existing and existing.id != role.id:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Role already exists")
            role.name = payload.name
        if payload.description is not None:
            role.description = payload.description

        updated = await self.roles.update(role)
        await self.audit.log(
            actor_id=actor.id,
            action="role.updated",
            entity_type="role",
            entity_id=str(updated.id),
            old_value=old_value,
            new_value=self._serialize_role(updated),
        )
        return RoleResponse.model_validate(updated)

    async def delete_role(self, role_id: UUID, actor: User) -> None:
        role = await self.roles.get_by_id(role_id)
        if not role:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
        if role.name == "Super Admin":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete Super Admin role",
            )

        old_value = self._serialize_role(role)
        await self.roles.soft_delete(role)
        await self.audit.log(
            actor_id=actor.id,
            action="role.deleted",
            entity_type="role",
            entity_id=str(role.id),
            old_value=old_value,
        )


class PermissionService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.permissions = PermissionRepository(db)
        self.roles = RoleRepository(db)
        self.audit = AuditService(db)

    async def list_permissions(self) -> list[PermissionResponse]:
        permissions = await self.permissions.list_permissions()
        return [PermissionResponse.model_validate(p) for p in permissions]

    async def get_role_permissions(self, role_id: UUID) -> list[PermissionResponse]:
        role = await self.roles.get_by_id(role_id)
        if not role:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
        return [PermissionResponse.model_validate(p) for p in role.permissions]

    async def update_role_permissions(
        self, role_id: UUID, payload: RolePermissionsUpdate, actor: User
    ) -> list[PermissionResponse]:
        role = await self.roles.get_by_id(role_id)
        if not role:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

        old_value = {"permissions": [p.permission_name for p in role.permissions]}
        permissions = await self.permissions.get_by_ids(payload.permission_ids)
        if len(permissions) != len(set(payload.permission_ids)):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="One or more permissions not found",
            )

        updated_role = await self.permissions.set_role_permissions(role, permissions)
        new_value = {"permissions": [p.permission_name for p in updated_role.permissions]}
        await self.audit.log(
            actor_id=actor.id,
            action="permission.updated",
            entity_type="role",
            entity_id=str(role.id),
            old_value=old_value,
            new_value=new_value,
        )
        return [PermissionResponse.model_validate(p) for p in updated_role.permissions]


class AuditLogService:
    def __init__(self, db: AsyncSession):
        self.repo = AuditLogRepository(db)

    async def list_logs(
        self,
        *,
        page: int,
        page_size: int,
        search: str | None,
        action: str | None,
        entity_type: str | None,
        user_id: UUID | None,
    ) -> PaginatedResponse[AuditLogResponse]:
        logs, total = await self.repo.list_logs(
            page=page,
            page_size=page_size,
            search=search,
            action=action,
            entity_type=entity_type,
            user_id=user_id,
        )
        pagination = build_pagination(total, page, page_size)
        return PaginatedResponse[AuditLogResponse](
            items=[AuditLogResponse.model_validate(log) for log in logs],
            **pagination,
        )
