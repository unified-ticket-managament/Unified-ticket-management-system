from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app.rbac.models.permission_override import UserPermissionOverride

from .base import BaseRepository


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PermissionOverrideRepository(BaseRepository):
    """
    Repository for per-user permission override database operations.
    """

    # --------------------------------------------------
    # Create
    # --------------------------------------------------

    async def create(
        self,
        override: UserPermissionOverride,
    ) -> UserPermissionOverride:

        self.db.add(override)

        await self.db.flush()
        await self.db.refresh(override, attribute_names=["permission"])

        return override

    # --------------------------------------------------
    # Read
    # --------------------------------------------------

    async def get_by_id(
        self,
        override_id: UUID,
    ) -> UserPermissionOverride | None:

        result = await self.db.execute(
            select(UserPermissionOverride)
            .options(selectinload(UserPermissionOverride.permission))
            .where(UserPermissionOverride.override_id == override_id)
        )

        return result.scalar_one_or_none()

    async def get_active_by_user_and_permission(
        self,
        user_id: UUID,
        permission_id: UUID,
        scope_ticket_id: UUID | None = None,
    ) -> UserPermissionOverride | None:
        """
        `scope_ticket_id=None` matches an active *global* grant only —
        matches the active-override-uniqueness index, which treats a
        global grant and a per-ticket grant for the same user+
        permission as distinct rows.
        """

        result = await self.db.execute(
            select(UserPermissionOverride).where(
                UserPermissionOverride.user_id == user_id,
                UserPermissionOverride.permission_id == permission_id,
                UserPermissionOverride.scope_ticket_id == scope_ticket_id,
                UserPermissionOverride.revoked_at.is_(None),
            )
        )

        return result.scalar_one_or_none()

    async def list_active_by_user(
        self,
        user_id: UUID,
    ) -> list[UserPermissionOverride]:

        now = utc_now()

        result = await self.db.execute(
            select(UserPermissionOverride)
            .options(selectinload(UserPermissionOverride.permission))
            .where(
                UserPermissionOverride.user_id == user_id,
                UserPermissionOverride.revoked_at.is_(None),
                or_(
                    UserPermissionOverride.expires_at.is_(None),
                    UserPermissionOverride.expires_at > now,
                ),
            )
        )

        return list(result.scalars().all())

    async def list_all_by_user(
        self,
        user_id: UUID,
        include_revoked: bool = False,
    ) -> list[UserPermissionOverride]:

        query = (
            select(UserPermissionOverride)
            .options(selectinload(UserPermissionOverride.permission))
            .where(UserPermissionOverride.user_id == user_id)
        )

        if not include_revoked:
            query = query.where(UserPermissionOverride.revoked_at.is_(None))

        result = await self.db.execute(
            query.order_by(UserPermissionOverride.granted_at.desc())
        )

        return list(result.scalars().all())

    # --------------------------------------------------
    # Update
    # --------------------------------------------------

    async def revoke(
        self,
        override: UserPermissionOverride,
        revoked_by: UUID,
    ) -> UserPermissionOverride:

        override.revoked_at = utc_now()
        override.revoked_by = revoked_by

        await self.db.flush()
        await self.db.refresh(override)

        return override
