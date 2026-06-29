import hashlib
import json
from datetime import datetime, timezone
from math import ceil
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import AuditLog, Permission, RefreshToken, Role, RolePermission, User


class BaseRepository:
    def __init__(self, db: AsyncSession):
        self.db = db


class UserRepository(BaseRepository):
    async def get_by_id(self, user_id: UUID, include_deleted: bool = False) -> User | None:
        query = (
            select(User)
            .options(selectinload(User.role).selectinload(Role.permissions))
            .where(User.id == user_id)
        )
        if not include_deleted:
            query = query.where(User.deleted_at.is_(None))
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        result = await self.db.execute(
            select(User)
            .options(selectinload(User.role).selectinload(Role.permissions))
            .where(User.email == email, User.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def list_users(
        self,
        *,
        page: int = 1,
        page_size: int = 10,
        search: str | None = None,
        role_id: UUID | None = None,
        is_active: bool | None = None,
    ) -> tuple[list[User], int]:
        query = (
            select(User)
            .options(selectinload(User.role))
            .where(User.deleted_at.is_(None))
        )
        count_query = select(func.count()).select_from(User).where(User.deleted_at.is_(None))

        if search:
            pattern = f"%{search}%"
            search_filter = or_(User.name.ilike(pattern), User.email.ilike(pattern))
            query = query.where(search_filter)
            count_query = count_query.where(search_filter)

        if role_id:
            query = query.where(User.role_id == role_id)
            count_query = count_query.where(User.role_id == role_id)

        if is_active is not None:
            query = query.where(User.is_active == is_active)
            count_query = count_query.where(User.is_active == is_active)

        total = (await self.db.execute(count_query)).scalar_one()
        result = await self.db.execute(
            query.order_by(User.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars().all()), total

    async def create(self, user: User) -> User:
        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user, attribute_names=["role"])
        return user

    async def update(self, user: User) -> User:
        user.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        await self.db.refresh(user, attribute_names=["role"])
        return user

    async def soft_delete(self, user: User) -> User:
        user.deleted_at = datetime.now(timezone.utc)
        user.is_active = False
        user.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        return user


class RoleRepository(BaseRepository):
    async def get_by_id(self, role_id: UUID) -> Role | None:
        result = await self.db.execute(
            select(Role)
            .options(selectinload(Role.permissions))
            .where(Role.id == role_id, Role.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Role | None:
        result = await self.db.execute(
            select(Role).where(Role.name == name, Role.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def list_roles(self) -> list[Role]:
        result = await self.db.execute(
            select(Role)
            .options(selectinload(Role.permissions))
            .where(Role.deleted_at.is_(None))
            .order_by(Role.name)
        )
        return list(result.scalars().all())

    async def create(self, role: Role) -> Role:
        self.db.add(role)
        await self.db.flush()
        await self.db.refresh(role)
        return role

    async def update(self, role: Role) -> Role:
        await self.db.flush()
        await self.db.refresh(role)
        return role

    async def soft_delete(self, role: Role) -> Role:
        role.deleted_at = datetime.now(timezone.utc)
        await self.db.flush()
        return role


class PermissionRepository(BaseRepository):
    async def list_permissions(self) -> list[Permission]:
        result = await self.db.execute(
            select(Permission).order_by(Permission.permission_name)
        )
        return list(result.scalars().all())

    async def get_by_id(self, permission_id: UUID) -> Permission | None:
        result = await self.db.execute(
            select(Permission).where(Permission.id == permission_id)
        )
        return result.scalar_one_or_none()

    async def get_by_ids(self, permission_ids: list[UUID]) -> list[Permission]:
        if not permission_ids:
            return []
        result = await self.db.execute(
            select(Permission).where(Permission.id.in_(permission_ids))
        )
        return list(result.scalars().all())

    async def set_role_permissions(self, role: Role, permissions: list[Permission]) -> Role:
        await self.db.execute(
            RolePermission.__table__.delete().where(RolePermission.role_id == role.id)
        )
        for permission in permissions:
            self.db.add(RolePermission(role_id=role.id, permission_id=permission.id))
        await self.db.flush()
        await self.db.refresh(role, attribute_names=["permissions"])
        return role


class RefreshTokenRepository(BaseRepository):
    @staticmethod
    def hash_token(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    async def create(self, user_id: UUID, token: str, expires_at: datetime) -> RefreshToken:
        refresh_token = RefreshToken(
            user_id=user_id,
            token_hash=self.hash_token(token),
            expires_at=expires_at,
        )
        self.db.add(refresh_token)
        await self.db.flush()
        return refresh_token

    async def get_valid_token(self, token: str) -> RefreshToken | None:
        result = await self.db.execute(
            select(RefreshToken)
            .options(selectinload(RefreshToken.user).selectinload(User.role).selectinload(Role.permissions))
            .where(
                RefreshToken.token_hash == self.hash_token(token),
                RefreshToken.revoked.is_(False),
                RefreshToken.expires_at > datetime.now(timezone.utc),
            )
        )
        return result.scalar_one_or_none()

    async def revoke(self, token: RefreshToken) -> None:
        token.revoked = True
        await self.db.flush()

    async def revoke_all_for_user(self, user_id: UUID) -> None:
        result = await self.db.execute(
            select(RefreshToken).where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked.is_(False),
            )
        )
        for token in result.scalars().all():
            token.revoked = True
        await self.db.flush()


class AuditLogRepository(BaseRepository):
    async def create(
        self,
        *,
        user_id: UUID | None,
        action: str,
        entity_type: str,
        entity_id: str | None = None,
        old_value: Any | None = None,
        new_value: Any | None = None,
    ) -> AuditLog:
        audit_log = AuditLog(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            old_value=json.dumps(old_value, default=str) if old_value is not None else None,
            new_value=json.dumps(new_value, default=str) if new_value is not None else None,
        )
        self.db.add(audit_log)
        await self.db.flush()
        return audit_log

    async def list_logs(
        self,
        *,
        page: int = 1,
        page_size: int = 10,
        search: str | None = None,
        action: str | None = None,
        entity_type: str | None = None,
        user_id: UUID | None = None,
    ) -> tuple[list[AuditLog], int]:
        query = select(AuditLog)
        count_query = select(func.count()).select_from(AuditLog)

        if search:
            pattern = f"%{search}%"
            search_filter = or_(
                AuditLog.action.ilike(pattern),
                AuditLog.entity_type.ilike(pattern),
                AuditLog.entity_id.ilike(pattern),
            )
            query = query.where(search_filter)
            count_query = count_query.where(search_filter)

        if action:
            query = query.where(AuditLog.action == action)
            count_query = count_query.where(AuditLog.action == action)

        if entity_type:
            query = query.where(AuditLog.entity_type == entity_type)
            count_query = count_query.where(AuditLog.entity_type == entity_type)

        if user_id:
            query = query.where(AuditLog.user_id == user_id)
            count_query = count_query.where(AuditLog.user_id == user_id)

        total = (await self.db.execute(count_query)).scalar_one()
        result = await self.db.execute(
            query.order_by(AuditLog.timestamp.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars().all()), total


def build_pagination(total: int, page: int, page_size: int) -> dict[str, int]:
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, ceil(total / page_size)) if page_size else 1,
    }
