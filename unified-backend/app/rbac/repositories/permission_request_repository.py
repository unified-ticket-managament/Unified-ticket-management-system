from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.rbac.models.permission_request import PermissionRequest, PermissionRequestStatus

from .base import BaseRepository


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PermissionRequestRepository(BaseRepository):
    """
    Repository for permission-request database operations.
    """

    async def create(
        self,
        request: PermissionRequest,
    ) -> PermissionRequest:

        self.db.add(request)

        await self.db.flush()
        await self.db.refresh(request, attribute_names=["permission"])

        return request

    async def get_by_id(
        self,
        request_id: UUID,
    ) -> PermissionRequest | None:

        result = await self.db.execute(
            select(PermissionRequest)
            .options(
                selectinload(PermissionRequest.permission),
                selectinload(PermissionRequest.granted_override),
            )
            .where(PermissionRequest.request_id == request_id)
        )

        return result.scalar_one_or_none()

    async def get_pending_by_requester_and_permission(
        self,
        requester_id: UUID,
        permission_id: UUID,
    ) -> PermissionRequest | None:

        result = await self.db.execute(
            select(PermissionRequest).where(
                PermissionRequest.requester_id == requester_id,
                PermissionRequest.permission_id == permission_id,
                PermissionRequest.status == PermissionRequestStatus.PENDING,
            )
        )

        return result.scalar_one_or_none()

    async def list_by_requester(
        self,
        requester_id: UUID,
    ) -> list[PermissionRequest]:

        result = await self.db.execute(
            select(PermissionRequest)
            .options(
                selectinload(PermissionRequest.permission),
                selectinload(PermissionRequest.granted_override),
            )
            .where(PermissionRequest.requester_id == requester_id)
            .order_by(PermissionRequest.created_at.desc())
        )

        return list(result.scalars().all())

    async def list_pending_by_role(
        self,
        requested_role: str | None = None,
    ) -> list[PermissionRequest]:
        """
        `requested_role=None` returns every pending request regardless
        of who it's addressed to — used for roles with unconditional
        review authority (Super Admin/Site Lead); passing a role name
        narrows to requests addressed to exactly that role.
        """

        query = (
            select(PermissionRequest)
            .options(selectinload(PermissionRequest.permission))
            .where(PermissionRequest.status == PermissionRequestStatus.PENDING)
        )

        if requested_role is not None:
            query = query.where(PermissionRequest.requested_role == requested_role)

        result = await self.db.execute(query.order_by(PermissionRequest.created_at.asc()))

        return list(result.scalars().all())

    async def approve(
        self,
        request: PermissionRequest,
        reviewed_by: UUID,
        review_comment: str | None,
        expires_at: datetime | None,
        granted_override_id: UUID,
    ) -> PermissionRequest:

        request.status = PermissionRequestStatus.APPROVED
        request.reviewed_by = reviewed_by
        request.reviewed_at = utc_now()
        request.review_comment = review_comment
        request.expires_at = expires_at
        request.granted_override_id = granted_override_id

        await self.db.flush()
        await self.db.refresh(request)

        return request

    async def reject(
        self,
        request: PermissionRequest,
        reviewed_by: UUID,
        review_comment: str | None,
    ) -> PermissionRequest:

        request.status = PermissionRequestStatus.REJECTED
        request.reviewed_by = reviewed_by
        request.reviewed_at = utc_now()
        request.review_comment = review_comment

        await self.db.flush()
        await self.db.refresh(request)

        return request
